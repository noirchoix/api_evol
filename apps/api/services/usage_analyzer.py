from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from schemas.models import ContractChange, ImpactedFile, UsageImpact


def operation_path(change: ContractChange) -> tuple[str,str]:
    if isinstance(change.old,dict) and change.old.get('path'):
        return str(change.old.get('method') or change.operation_key.split(' ',1)[0]),str(change.old['path'])
    if ' ' in change.operation_key:
        method,path=change.operation_key.split(' ',1); return method,path
    return '',change.operation_key


def path_regex(path:str) -> re.Pattern[str]:
    pieces=[]; i=0
    for m in re.finditer(r'\{[^}]+\}',path):
        pieces.append(re.escape(path[i:m.start()])); pieces.append(r'(?:[^/?#]+|\{\})'); i=m.end()
    pieces.append(re.escape(path[i:]))
    return re.compile(''.join(pieces))


class UsageAnalyzer:
    def analyze(self,changes:list[ContractChange],repo_index:dict[str,Any],propagate:bool=True) -> tuple[list[UsageImpact],list[ImpactedFile]]:
        network=repo_index.get('network_calls') or []; files=repo_index.get('files') or {}
        impacts: list[UsageImpact]=[]; direct_by_change: dict[str,set[str]]=defaultdict(set)
        for change in changes:
            if change.severity not in {'breaking','potentially_breaking'}: continue
            method,path=operation_path(change); rx=path_regex(path)
            operation_calls=[]
            for call in network:
                if method and call.get('method') and call['method'].upper()!=method.upper(): continue
                target=call.get('target') or ''
                if rx.search(target):
                    match_type='exact_path' if target==path else 'templated_path'
                    conf='high' if call.get('literal') and match_type=='exact_path' else 'medium'
                    evidence=f"{call.get('client')} {call.get('method') or ''} call targets {target!r}."
                    impact=UsageImpact(change_id=change.id,file=call['file'],line=int(call.get('line') or 1),symbol=call.get('enclosing_symbol') or '',match_type=match_type,confidence=conf,evidence=evidence)
                    impacts.append(impact); direct_by_change[change.id].add(call['file']); operation_calls.append(call['file'])
            prop=self._changed_property(change)
            if prop:
                for file,meta in files.items():
                    for field in meta.get('fields') or []:
                        if field.get('name')!=prop: continue
                        same_operation=file in operation_calls
                        if not same_operation and len(prop)<=3: continue
                        conf='high' if same_operation else 'low'
                        impacts.append(UsageImpact(change_id=change.id,file=file,line=int(field.get('line') or 1),symbol=field.get('symbol') or '',match_type='field_usage',confidence=conf,evidence=f"Source accesses field {prop!r} as {field.get('form')}."))
                        direct_by_change[change.id].add(file)

        impacts=self._dedupe(impacts)
        direct_files=defaultdict(list)
        for impact in impacts:
            if impact.match_type!='dependency_propagation': direct_files[impact.file].append(impact)
        impacted={file:ImpactedFile(file=file,direct_impacts=len(items),propagated_distance=0,reasons=sorted({i.evidence for i in items})[:6]) for file,items in direct_files.items()}
        if propagate and impacted:
            self._propagate(repo_index,impacted,impacts)
        return impacts,sorted(impacted.values(),key=lambda x:(x.propagated_distance,-x.direct_impacts,x.file))

    def _changed_property(self,change:ContractChange) -> str|None:
        if 'property_' not in change.category and not change.category.endswith('_property_removed'): return None
        if isinstance(change.old,dict) and change.old.get('property'): return str(change.old['property'])
        return None

    def _propagate(self,repo_index:dict[str,Any],impacted:dict[str,ImpactedFile],impacts:list[UsageImpact]) -> None:
        reverse: dict[str,set[str]]=defaultdict(set)
        for edge in repo_index.get('import_edges') or []: reverse[edge['target']].add(edge['source'])
        queue=deque((f,0) for f in list(impacted)); seen=set(impacted)
        while queue:
            target,distance=queue.popleft()
            if distance>=2: continue
            for source in reverse.get(target,set()):
                nd=distance+1
                if source not in impacted:
                    impacted[source]=ImpactedFile(file=source,direct_impacts=0,propagated_distance=nd,reasons=[f'Imports impacted file {target}.'])
                else:
                    impacted[source].propagated_distance=min(impacted[source].propagated_distance or nd,nd)
                    if f'Imports impacted file {target}.' not in impacted[source].reasons: impacted[source].reasons.append(f'Imports impacted file {target}.')
                if source not in seen:
                    seen.add(source); queue.append((source,nd))
                impacts.append(UsageImpact(change_id='dependency_graph',file=source,line=1,symbol='',match_type='dependency_propagation',confidence='medium',evidence=f'Imports impacted file {target} at dependency distance {nd}.'))

    def _dedupe(self,items:list[UsageImpact]) -> list[UsageImpact]:
        rank={'high':3,'medium':2,'low':1}; unique={}
        for item in items:
            key=(item.change_id,item.file,item.line,item.match_type)
            if key not in unique or rank[item.confidence]>rank[unique[key].confidence]: unique[key]=item
        return sorted(unique.values(),key=lambda x:(x.file,x.line,x.change_id,x.match_type))
