from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.store import AssuranceStore
from schemas.models import AssuranceResponse, CanonicalContract, ContractUploadResponse, RepositoryUploadResponse
from services.contract_diff import ContractDiffService
from services.migration_service import MigrationPlanner
from services.tool_registry import ToolRegistry
from services.usage_analyzer import UsageAnalyzer
from services.validation_service import ValidationService


def utcnow() -> str: return datetime.now(timezone.utc).isoformat()


class AssuranceService:
    def __init__(self,store:AssuranceStore,validation:ValidationService|None=None):
        self.store=store; self.diff=ContractDiffService(); self.usage=UsageAnalyzer(); self.migrations=MigrationPlanner(); self.tools=ToolRegistry(); self.validation=validation or ValidationService()

    def analyze(self,old_contract_id:str,new_contract_id:str,repository_id:str,allow_trusted_execution:bool=False,propagate_import_impacts:bool=True) -> AssuranceResponse:
        old_raw=self.store.get_contract(old_contract_id); new_raw=self.store.get_contract(new_contract_id); repo=self.store.get_repository(repository_id)
        if not old_raw or not new_raw or not repo: raise KeyError('One or more requested resources do not exist.')
        old=CanonicalContract.model_validate(old_raw); new=CanonicalContract.model_validate(new_raw)
        changes=self.diff.diff(old,new)
        impacts,impacted_files=self.usage.analyze(changes,repo['index'],propagate_import_impacts)
        patches=self.migrations.plan(changes,impacts)
        root=Path(repo['root_path']); tool_plan=self.tools.plan(root,repo['index']); validation=self.validation.run(root,tool_plan,allow_trusted_execution)
        gate,reasons=self._gate(changes,impacts,patches,validation)
        analysis_id='ana_'+uuid.uuid4().hex[:14]
        response=AssuranceResponse(
            analysis_id=analysis_id,created_at=utcnow(),
            old_contract=self._contract_summary(old_contract_id,old),new_contract=self._contract_summary(new_contract_id,new),
            repository=self._repo_summary(repository_id,repo),changes=changes,
            breaking_change_count=sum(c.severity=='breaking' for c in changes),usage_impacts=impacts,impacted_files=impacted_files,patch_plan=patches,
            tool_plan=tool_plan,validation=validation,release_gate=gate,release_gate_reasons=reasons,
            evidence_summary=self._evidence(changes,impacts,patches,validation),
            limitations=[
                'Python source indexing uses the standard AST. JavaScript/TypeScript/Svelte indexing uses a deterministic lexical structural analyzer; tree-sitter can be added as an optional deployment adapter for deeper language coverage.',
                'Field-usage matches outside files with a directly matched API call are deliberately low-confidence because the same property name can occur in unrelated models.',
                'Uploaded repositories are not executed unless the request explicitly authorizes trusted execution and the deployment enables an isolated local runner.',
                'Automatic patch application is restricted to human-approved, exact single-line replacements. Ambiguous or manual patches are never silently applied.',
            ],
            metadata={'old_contract_id':old_contract_id,'new_contract_id':new_contract_id,'repository_id':repository_id,'trusted_execution_requested':allow_trusted_execution,'import_impact_propagation':propagate_import_impacts,'deterministic_diff':True}
        )
        self.store.put_analysis(analysis_id,{'old_contract_id':old_contract_id,'new_contract_id':new_contract_id,'repository_id':repository_id,'allow_trusted_execution':allow_trusted_execution,'propagate_import_impacts':propagate_import_impacts},response.model_dump(mode='json'))
        return response

    def _contract_summary(self,cid:str,c:CanonicalContract) -> ContractUploadResponse:
        return ContractUploadResponse(contract_id=cid,source_name=c.source_name,sha256=c.sha256,title=c.title,version=c.version,openapi_version=c.openapi_version,operation_count=len(c.operations),warnings=c.warnings)

    def _repo_summary(self,rid:str,repo:dict[str,Any]) -> RepositoryUploadResponse:
        index=repo['index']; return RepositoryUploadResponse(repository_id=rid,filename=repo['filename'],sha256=repo['sha256'],file_count=len(index.get('files') or {}),languages=index.get('languages') or {},network_call_count=len(index.get('network_calls') or []),import_edge_count=len(index.get('import_edges') or []),warnings=index.get('warnings') or [])

    def _gate(self,changes,impacts,patches,validation):
        failed=[v for v in validation if v.status in {'failed','timeout'}]
        breaking_ids={c.id for c in changes if c.severity=='breaking'}
        direct_breaking=[i for i in impacts if i.change_id in breaking_ids and i.match_type!='dependency_propagation']
        reasons=[]
        if failed:
            reasons.extend([f'{v.tool_id} validation {v.status}.' for v in failed]); return 'blocked',reasons
        if direct_breaking:
            reasons.append(f'{len(direct_breaking)} repository usage(s) are directly affected by breaking contract changes.')
            if patches: reasons.append(f'{len(patches)} migration operation(s) require human approval before application.')
            return 'blocked',reasons
        if breaking_ids:
            reasons.append(f'{len(breaking_ids)} breaking contract change(s) were detected, but no direct usage was proven in the indexed repository.')
            reasons.append('Human review is required because dynamic or generated API calls can evade static matching.')
            return 'review_required',reasons
        potential=sum(c.severity=='potentially_breaking' for c in changes)
        if potential:
            reasons.append(f'{potential} potentially breaking change(s) require review.'); return 'review_required',reasons
        reasons.append('No breaking or potentially breaking contract changes were detected for the indexed repository.'); return 'pass',reasons

    def _evidence(self,changes,impacts,patches,validation):
        return [
            f'Canonical semantic diff produced {len(changes)} contract changes, including {sum(c.severity=="breaking" for c in changes)} breaking.',
            f'Repository structural index linked {len(impacts)} usage/dependency impacts across {len({i.file for i in impacts})} files.',
            f'Migration planner produced {len(patches)} human-reviewable patch operations.',
            f'Validation plan produced {len(validation)} tool results: '+', '.join(f'{v.tool_id}={v.status}' for v in validation)+'.',
        ]
