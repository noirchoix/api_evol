from __future__ import annotations

import hashlib
from typing import Any

from schemas.models import ContractChange, PatchOperation, UsageImpact


class MigrationPlanner:
    def plan(self,changes:list[ContractChange],impacts:list[UsageImpact]) -> list[PatchOperation]:
        by_change={c.id:c for c in changes}; patches=[]
        for impact in impacts:
            if impact.match_type=='dependency_propagation': continue
            change=by_change.get(impact.change_id)
            if not change: continue
            if change.category=='path_changed' and isinstance(change.old,dict) and isinstance(change.new,dict):
                old=str(change.old.get('path') or ''); new=str(change.new.get('path') or '')
                if old and new:
                    patches.append(self._patch(impact,'replace_path',old,new,impact.confidence,f'Contract operation path changed: {old} → {new}.',[change.id]))
            elif change.category.endswith('_property_removed') and isinstance(change.old,dict):
                old=str(change.old.get('property') or ''); candidate=''
                if isinstance(change.new,dict): candidate=str(change.new.get('rename_candidate') or '')
                if old and candidate:
                    patches.append(self._patch(impact,'replace_field',old,candidate,'medium' if impact.confidence!='high' else 'high',f'Likely field rename inferred from schema diff: {old} → {candidate}.',[change.id]))
                elif old:
                    patches.append(self._patch(impact,'manual',old,'','low',f'Field {old} was removed without a confident replacement; manual migration is required.',[change.id]))
            elif change.category in {'parameter_became_required','parameter_added','security_became_required','request_body_became_required'}:
                patches.append(self._patch(impact,'manual','','','medium',change.migration_hint or change.summary,[change.id]))
        return self._dedupe(patches)

    def _patch(self,impact:UsageImpact,kind:str,old:str,new:str,confidence:str,reason:str,change_ids:list[str]) -> PatchOperation:
        raw=f'{impact.file}|{impact.line}|{kind}|{old}|{new}|{";".join(change_ids)}'
        return PatchOperation(id='patch_'+hashlib.sha1(raw.encode()).hexdigest()[:12],file=impact.file,line=impact.line,kind=kind,old_text=old,new_text=new,confidence=confidence,reason=reason,change_ids=change_ids,requires_human_approval=True)

    def _dedupe(self,patches:list[PatchOperation]) -> list[PatchOperation]:
        unique={}
        for p in patches: unique[(p.file,p.line,p.kind,p.old_text,p.new_text)]=p
        return sorted(unique.values(),key=lambda p:(p.file,p.line or 0,p.kind))
