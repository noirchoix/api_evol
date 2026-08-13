from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from typing import Any

from schemas.models import CanonicalContract, CanonicalOperation, CanonicalParameter, CanonicalSchema, ChangeEvidence, ContractChange


def change_id(*parts: str) -> str:
    return 'chg_' + hashlib.sha1('|'.join(parts).encode()).hexdigest()[:12]


class ContractDiffService:
    def diff(self, old: CanonicalContract, new: CanonicalContract) -> list[ContractChange]:
        changes: list[ContractChange] = []
        old_ops = old.operations
        new_ops = new.operations
        matched_old: set[str] = set()
        matched_new: set[str] = set()

        new_by_operation_id = {op.operation_id: key for key, op in new_ops.items() if op.operation_id}
        for key, old_op in old_ops.items():
            if key in new_ops:
                matched_old.add(key); matched_new.add(key)
                changes.extend(self._diff_operation(old_op, new_ops[key]))
                continue
            if old_op.operation_id and old_op.operation_id in new_by_operation_id:
                new_key = new_by_operation_id[old_op.operation_id]
                new_op = new_ops[new_key]
                matched_old.add(key); matched_new.add(new_key)
                changes.append(ContractChange(
                    id=change_id('path_changed',key,new_key), severity='breaking', category='path_changed', operation_key=key,
                    summary=f'Operation path changed from {key} to {new_key} while operationId stayed {old_op.operation_id}.',
                    old={'method':old_op.method,'path':old_op.path,'operation_id':old_op.operation_id},
                    new={'method':new_op.method,'path':new_op.path,'operation_id':new_op.operation_id},
                    confidence='high', migration_hint=f'Replace calls to {old_op.path} with {new_op.path} and rerun contract tests.',
                    evidence=[self._evidence(old.source_name,f'{key} operationId={old_op.operation_id}'),self._evidence(new.source_name,f'{new_key} operationId={new_op.operation_id}')],
                ))
                changes.extend(self._diff_operation(old_op,new_op,operation_key=key))

        for key, op in old_ops.items():
            if key not in matched_old:
                changes.append(ContractChange(
                    id=change_id('endpoint_removed',key), severity='breaking', category='endpoint_removed', operation_key=key,
                    summary=f'Endpoint removed: {key}.', old={'method':op.method,'path':op.path,'operation_id':op.operation_id}, new=None,
                    migration_hint='Find all consumers of this endpoint and migrate them to a replacement operation or explicitly retire the call.',
                    evidence=[self._evidence(old.source_name,f'{key} exists in old contract'),self._evidence(new.source_name,f'{key} absent from new contract')],
                ))
        for key, op in new_ops.items():
            if key not in matched_new:
                changes.append(ContractChange(
                    id=change_id('endpoint_added',key), severity='non_breaking', category='endpoint_added', operation_key=key,
                    summary=f'Endpoint added: {key}.', old=None, new={'method':op.method,'path':op.path,'operation_id':op.operation_id},
                    migration_hint='No migration required unless consumers should adopt the new capability.',
                    evidence=[self._evidence(new.source_name,f'{key} exists in new contract')],
                ))
        return sorted(changes,key=lambda c:({'breaking':0,'potentially_breaking':1,'non_breaking':2,'info':3}[c.severity],c.operation_key,c.category))

    def _diff_operation(self, old: CanonicalOperation, new: CanonicalOperation, operation_key: str | None=None) -> list[ContractChange]:
        key=operation_key or old.key
        out: list[ContractChange]=[]
        old_params={(p.location,p.name):p for p in old.parameters}; new_params={(p.location,p.name):p for p in new.parameters}
        for pkey,p in old_params.items():
            if pkey not in new_params:
                severity='potentially_breaking' if p.required else 'info'
                out.append(self._simple(severity,'parameter_removed',key,f'{p.location} parameter removed: {p.name}.',p.model_dump(),None,'Verify whether clients still send the removed parameter and whether the server rejects unknown parameters.'))
            else:
                n=new_params[pkey]
                if p.schema_type != n.schema_type:
                    out.append(self._simple('breaking','parameter_type_changed',key,f'{p.location} parameter {p.name} changed type {p.schema_type} → {n.schema_type}.',p.model_dump(),n.model_dump(),f'Update serialization/parsing for parameter {p.name}.'))
                if not p.required and n.required:
                    out.append(self._simple('breaking','parameter_became_required',key,f'{p.location} parameter became required: {p.name}.',p.model_dump(),n.model_dump(),f'Populate required parameter {p.name} in every affected call.'))
                if p.required and not n.required:
                    out.append(self._simple('non_breaking','parameter_became_optional',key,f'{p.location} parameter became optional: {p.name}.',p.model_dump(),n.model_dump(),'No migration required.'))
                if p.enum and n.enum and set(p.enum)-set(n.enum):
                    out.append(self._simple('breaking','parameter_enum_narrowed',key,f'Allowed values were removed from parameter {p.name}.',p.enum,n.enum,f'Check consumers that send removed values for {p.name}.'))
        for pkey,p in new_params.items():
            if pkey not in old_params:
                severity='breaking' if p.required else 'non_breaking'
                out.append(self._simple(severity,'parameter_added',key,f'{p.location} parameter added: {p.name} ({"required" if p.required else "optional"}).',None,p.model_dump(),f'Populate {p.name} in affected calls.' if p.required else 'No migration required for existing consumers.'))

        if not old.request_required and new.request_required:
            out.append(self._simple('breaking','request_body_became_required',key,'Request body became required.',False,True,'Ensure every call sends a valid request body.'))
        out.extend(self._schema_diff(key,'request',old.request_schema,new.request_schema))

        old_status=set(old.responses); new_status=set(new.responses)
        for status in sorted(old_status-new_status):
            out.append(self._simple('potentially_breaking','response_status_removed',key,f'Response status/schema removed: {status}.',status,None,'Check client control flow that handles this response status.'))
        for status in sorted(new_status-old_status):
            out.append(self._simple('non_breaking','response_status_added',key,f'New response status/schema added: {status}.',None,status,'Consider handling the new response status explicitly.'))
        for status in sorted(old_status & new_status):
            out.extend(self._schema_diff(key,f'response:{status}',old.responses[status],new.responses[status]))

        if not old.security_required and new.security_required:
            out.append(self._simple('breaking','security_became_required',key,'Operation now requires security/authentication.',False,True,'Add the required authentication mechanism to all affected consumers.'))
        if old.security_required and not new.security_required:
            out.append(self._simple('non_breaking','security_became_optional',key,'Operation no longer requires security/authentication.',True,False,'No migration required for existing authenticated consumers.'))
        return out

    def _schema_diff(self,key:str,scope:str,old:CanonicalSchema|None,new:CanonicalSchema|None) -> list[ContractChange]:
        out=[]
        if old is None and new is None: return out
        if old is None and new is not None:
            severity='breaking' if scope=='request' and bool(new.required) else 'non_breaking'
            return [self._simple(severity,f'{scope}_schema_added',key,f'{scope} schema added.',None,new.model_dump(),'Review generated models and request/response handling.')]
        if old is not None and new is None:
            severity='potentially_breaking' if scope.startswith('response') else 'non_breaking'
            return [self._simple(severity,f'{scope}_schema_removed',key,f'{scope} schema removed.',old.model_dump(),None,'Review client assumptions about payload shape.')]
        assert old is not None and new is not None
        if old.type != new.type:
            out.append(self._simple('breaking',f'{scope}_type_changed',key,f'{scope} root type changed {old.type} → {new.type}.',old.type,new.type,'Update client serialization/deserialization model.'))
        removed=set(old.properties)-set(new.properties); added=set(new.properties)-set(old.properties)
        rename_candidates=self._rename_candidates(old,new,removed,added)
        for name in sorted(removed):
            candidate=rename_candidates.get(name)
            old_payload={'property':name,'type':old.properties[name],'required':name in old.required}
            new_payload={'rename_candidate':candidate} if candidate else None
            if scope.startswith('response'):
                severity='breaking'; hint=f'Replace reads of response field {name}' + (f' with {candidate}.' if candidate else ' or handle its removal.')
            else:
                severity='breaking' if name in old.required else 'potentially_breaking'; hint=f'Stop sending request field {name}' + (f' and use {candidate} if it is the replacement.' if candidate else '.')
            out.append(self._simple(severity,f'{scope}_property_removed',key,f'{scope} property removed: {name}.',old_payload,new_payload,hint))
        for name in sorted(added):
            required=name in new.required
            old_payload=None; new_payload={'property':name,'type':new.properties[name],'required':required}
            if scope=='request' and required:
                severity='breaking'; hint=f'Populate new required request field {name}.'
            else:
                severity='non_breaking'; hint='No migration required for tolerant clients; update generated models if strict.'
            out.append(self._simple(severity,f'{scope}_property_added',key,f'{scope} property added: {name}{" (required)" if required else ""}.',old_payload,new_payload,hint))
        for name in sorted(set(old.properties)&set(new.properties)):
            if old.properties[name] != new.properties[name]:
                out.append(self._simple('breaking',f'{scope}_property_type_changed',key,f'{scope} property {name} changed type {old.properties[name]} → {new.properties[name]}.',{'property':name,'type':old.properties[name]},{'property':name,'type':new.properties[name]},f'Update type handling for field {name}.'))
            if name not in old.required and name in new.required and scope=='request':
                out.append(self._simple('breaking',f'{scope}_property_became_required',key,f'{scope} property became required: {name}.',False,True,f'Populate request field {name} in all affected calls.'))
        return out

    def _rename_candidates(self,old:CanonicalSchema,new:CanonicalSchema,removed:set[str],added:set[str]) -> dict[str,str]:
        result={}
        for old_name in removed:
            best=None; best_score=0.0
            for new_name in added:
                if old.properties.get(old_name)!=new.properties.get(new_name): continue
                score=SequenceMatcher(None,old_name.lower(),new_name.lower()).ratio()
                if score>best_score: best,best_score=new_name,score
            if best and best_score>=.55: result[old_name]=best
        return result

    def _simple(self,severity:str,category:str,key:str,summary:str,old:Any,new:Any,hint:str) -> ContractChange:
        return ContractChange(id=change_id(category,key,str(old),str(new)),severity=severity,category=category,operation_key=key,summary=summary,old=old,new=new,confidence='high',migration_hint=hint,evidence=[])

    def _evidence(self,source:str,detail:str) -> ChangeEvidence:
        return ChangeEvidence(id='ce_'+hashlib.sha1(f'{source}|{detail}'.encode()).hexdigest()[:10],source=source,detail=detail)
