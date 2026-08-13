from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from schemas.models import CanonicalContract, CanonicalOperation, CanonicalParameter, CanonicalSchema

HTTP_METHODS={'get','post','put','patch','delete','options','head','trace'}


class ContractParseError(ValueError):
    pass


class ContractParser:
    def parse(self, source_name:str, data:bytes) -> CanonicalContract:
        sha=hashlib.sha256(data).hexdigest()
        try:
            raw=json.loads(data.decode('utf-8')) if source_name.lower().endswith('.json') else yaml.safe_load(data.decode('utf-8'))
        except Exception as exc:
            raise ContractParseError(f'Contract is not valid JSON/YAML: {exc}') from exc
        if not isinstance(raw,dict): raise ContractParseError('Contract root must be an object.')
        if 'paths' not in raw or not isinstance(raw.get('paths'),dict): raise ContractParseError('Contract does not contain a valid paths object.')
        if raw.get('swagger'):
            return self._swagger2(source_name,sha,raw)
        return self._openapi(source_name,sha,raw)

    def _openapi(self,source_name:str,sha:str,raw:dict[str,Any]) -> CanonicalContract:
        warnings=[]; operations={}
        root_security=bool(raw.get('security'))
        for path,path_item in (raw.get('paths') or {}).items():
            if not isinstance(path_item,dict): continue
            path_params=path_item.get('parameters') or []
            for method,op in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(op,dict): continue
                params=self._parameters((path_params or [])+(op.get('parameters') or []),raw)
                request_schema=None; request_required=False
                rb=self._resolve(op.get('requestBody') or {},raw)
                if isinstance(rb,dict) and rb:
                    request_required=bool(rb.get('required'))
                    request_schema=self._content_schema(rb.get('content') or {},raw)
                responses={}
                for status,response in (op.get('responses') or {}).items():
                    response=self._resolve(response or {},raw)
                    schema=self._content_schema(response.get('content') or {},raw) if isinstance(response,dict) else None
                    if schema: responses[str(status)]=schema
                key=f'{method.upper()} {path}'
                operations[key]=CanonicalOperation(
                    key=key,method=method.upper(),path=path,operation_id=str(op.get('operationId') or ''),summary=str(op.get('summary') or op.get('description') or '')[:1000],
                    parameters=params,request_required=request_required,request_schema=request_schema,responses=responses,
                    security_required=bool(op.get('security')) if 'security' in op else root_security,tags=[str(x) for x in op.get('tags') or []],
                )
        info=raw.get('info') or {}
        if not operations: warnings.append('No HTTP operations were discovered in paths.')
        return CanonicalContract(title=str(info.get('title') or source_name),version=str(info.get('version') or ''),openapi_version=str(raw.get('openapi') or '3.x'),source_name=source_name,sha256=sha,operations=operations,warnings=warnings)

    def _swagger2(self,source_name:str,sha:str,raw:dict[str,Any]) -> CanonicalContract:
        warnings=['Swagger/OpenAPI 2.0 compatibility mode normalizes body parameters and response schemas into the canonical model.']
        operations={}; root_security=bool(raw.get('security'))
        for path,path_item in (raw.get('paths') or {}).items():
            if not isinstance(path_item,dict): continue
            path_params=path_item.get('parameters') or []
            for method,op in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(op,dict): continue
                all_params=(path_params or [])+(op.get('parameters') or [])
                non_body=[]; body=None
                for p in all_params:
                    rp=self._resolve(p,raw)
                    if isinstance(rp,dict) and rp.get('in')=='body': body=rp
                    else: non_body.append(p)
                params=self._parameters(non_body,raw)
                request_schema=self._schema_summary((body or {}).get('schema') or {},raw) if body else None
                responses={}
                for status,response in (op.get('responses') or {}).items():
                    response=self._resolve(response or {},raw)
                    if isinstance(response,dict) and response.get('schema'):
                        responses[str(status)]=self._schema_summary(response['schema'],raw)
                key=f'{method.upper()} {path}'
                operations[key]=CanonicalOperation(key=key,method=method.upper(),path=path,operation_id=str(op.get('operationId') or ''),summary=str(op.get('summary') or op.get('description') or '')[:1000],parameters=params,request_required=bool((body or {}).get('required')),request_schema=request_schema,responses=responses,security_required=bool(op.get('security')) if 'security' in op else root_security,tags=[str(x) for x in op.get('tags') or []])
        info=raw.get('info') or {}
        return CanonicalContract(title=str(info.get('title') or source_name),version=str(info.get('version') or ''),openapi_version=str(raw.get('swagger') or '2.0'),source_name=source_name,sha256=sha,operations=operations,warnings=warnings)

    def _parameters(self,params:list[Any],root:dict[str,Any]) -> list[CanonicalParameter]:
        result=[]; seen=set()
        for item in params:
            p=self._resolve(item,root)
            if not isinstance(p,dict): continue
            name=str(p.get('name') or ''); loc=str(p.get('in') or '')
            if not name or not loc: continue
            schema=self._resolve(p.get('schema') or {},root)
            if not schema and p.get('type'): schema=p
            cp=CanonicalParameter(name=name,location=loc,required=bool(p.get('required')),schema_type=self._type_name(schema),schema_format=str(schema.get('format') or '') if isinstance(schema,dict) else '',enum=list(schema.get('enum') or []) if isinstance(schema,dict) else [])
            key=(name,loc)
            if key in seen:
                result=[x for x in result if (x.name,x.location)!=key]
            seen.add(key); result.append(cp)
        return sorted(result,key=lambda x:(x.location,x.name))

    def _content_schema(self,content:dict[str,Any],root:dict[str,Any]) -> CanonicalSchema | None:
        if not isinstance(content,dict) or not content: return None
        media=content.get('application/json') or content.get('application/*+json') or next(iter(content.values()),{})
        if not isinstance(media,dict) or not media.get('schema'): return None
        return self._schema_summary(media['schema'],root)

    def _schema_summary(self,schema:Any,root:dict[str,Any]) -> CanonicalSchema:
        s=self._resolve(schema or {},root)
        if not isinstance(s,dict): return CanonicalSchema()
        required=[str(x) for x in s.get('required') or []]
        props={}
        for name,sub in (s.get('properties') or {}).items():
            resolved=self._resolve(sub,root)
            props[str(name)]=self._type_name(resolved)
        if not props and s.get('items'):
            props['[]']=self._type_name(self._resolve(s.get('items'),root))
        return CanonicalSchema(type=self._type_name(s),required=sorted(required),properties=dict(sorted(props.items())),nullable=bool(s.get('nullable')))

    def _type_name(self,schema:Any) -> str:
        if not isinstance(schema,dict): return 'unknown'
        if schema.get('type'): return str(schema['type']) + (f":{schema.get('format')}" if schema.get('format') else '')
        if schema.get('properties'): return 'object'
        if schema.get('allOf'): return 'allOf'
        if schema.get('oneOf'): return 'oneOf'
        if schema.get('anyOf'): return 'anyOf'
        return 'unknown'

    def _resolve(self,node:Any,root:dict[str,Any],seen:set[str]|None=None) -> Any:
        if not isinstance(node,dict) or '$ref' not in node: return node
        ref=str(node['$ref'])
        if not ref.startswith('#/'): return node
        seen=set() if seen is None else set(seen)
        if ref in seen: return node
        seen.add(ref); cur:Any=root
        try:
            for part in ref[2:].split('/'):
                part=part.replace('~1','/').replace('~0','~'); cur=cur[part]
        except (KeyError,TypeError): return node
        if isinstance(cur,dict) and '$ref' in cur: return self._resolve(cur,root,seen)
        return deepcopy(cur)
