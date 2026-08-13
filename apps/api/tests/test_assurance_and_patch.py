from __future__ import annotations
import io, json, zipfile
from pathlib import Path
from repositories.store import AssuranceStore
from services.repository_service import RepositoryService
from services.contract_parser import ContractParser
from services.assurance_service import AssuranceService
from services.patch_service import PatchService
from schemas.models import PatchOperation


def repo_bytes():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('client.py','''import requests\n\ndef get_user(base):\n    data = requests.get(base + "/users/1").json()\n    return data.email\n''')
    return b.getvalue()


def specs():
    old={'openapi':'3.1.0','info':{'title':'Demo','version':'1'},'paths':{'/users/{id}':{'get':{'operationId':'getUser','responses':{'200':{'content':{'application/json':{'schema':{'type':'object','properties':{'email':{'type':'string'}}}}}}}}}}}
    new={'openapi':'3.1.0','info':{'title':'Demo','version':'2'},'paths':{'/accounts/{id}':{'get':{'operationId':'getUser','responses':{'200':{'content':{'application/json':{'schema':{'type':'object','properties':{'primary_email':{'type':'string'}}}}}}}}}}}
    return old,new


def test_end_to_end_release_gate_and_execution_safety(tmp_path:Path):
    store=AssuranceStore(tmp_path/'db.sqlite'); parser=ContractParser(); old_obj,new_obj=specs(); old=parser.parse('old.json',json.dumps(old_obj).encode()); new=parser.parse('new.json',json.dumps(new_obj).encode())
    store.put_contract('old','old.json',old.model_dump(mode='json')); store.put_contract('new','new.json',new.model_dump(mode='json'))
    root,index=RepositoryService(tmp_path/'repos').extract_and_index('repo','repo.zip',repo_bytes()); store.put_repository('repo','repo.zip','sha',str(root),index)
    result=AssuranceService(store).analyze('old','new','repo',allow_trusted_execution=False)
    assert result.release_gate=='blocked'
    assert result.breaking_change_count>=1
    assert result.patch_plan
    exec_results=[v for v in result.validation if v.tool_id not in {'canonical_contract_diff','repository_structural_index'} and v.status!='unavailable']
    assert all(v.status=='skipped' for v in exec_results)


def test_patch_service_requires_exact_evidence_line(tmp_path:Path):
    repo=tmp_path/'repo'; repo.mkdir(); (repo/'client.py').write_text('value = data.email\n',encoding='utf-8')
    patch=PatchOperation(id='p1',file='client.py',line=1,kind='replace_field',old_text='email',new_text='primary_email',confidence='high',reason='rename',change_ids=['c1'])
    result=PatchService(tmp_path/'artifacts').apply('a1',repo,[patch],['p1'])
    assert result.applied==1
    assert '-value = data.email' in result.unified_diff
    assert '+value = data.primary_email' in result.unified_diff
    assert (tmp_path/'artifacts'/f'{result.artifact_id}.zip').exists()
