from __future__ import annotations
import io, json, zipfile
from pathlib import Path
from services.repository_service import RepositoryService
from services.contract_parser import ContractParser
from services.contract_diff import ContractDiffService
from services.usage_analyzer import UsageAnalyzer
from services.migration_service import MigrationPlanner


def zip_repo():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('src/api.py','''import requests\n\ndef fetch_user(base, user_id):\n    data = requests.get(f"{base}/users/{user_id}").json()\n    return data.email\n''')
        z.writestr('app.py','from src.api import fetch_user\n\ndef run():\n    return fetch_user("https://example.test", "1")\n')
        z.writestr('web.ts','''export async function createOrder(){\n  return fetch('/orders', { method: 'POST' });\n}\n''')
        z.writestr('../escape.py','bad=True')
    return b.getvalue()


def contracts():
    old={'openapi':'3.1.0','info':{'title':'Demo','version':'1'},'paths':{'/users/{id}':{'get':{'operationId':'getUser','responses':{'200':{'content':{'application/json':{'schema':{'type':'object','properties':{'email':{'type':'string'}}}}}}}}}}}
    new={'openapi':'3.1.0','info':{'title':'Demo','version':'2'},'paths':{'/accounts/{id}':{'get':{'operationId':'getUser','responses':{'200':{'content':{'application/json':{'schema':{'type':'object','properties':{'primary_email':{'type':'string'}}}}}}}}}}}
    p=ContractParser(); return p.parse('old.json',json.dumps(old).encode()),p.parse('new.json',json.dumps(new).encode())


def test_structural_index_and_blast_radius(tmp_path:Path):
    root,index=RepositoryService(tmp_path/'repos').extract_and_index('r1','repo.zip',zip_repo())
    assert index['languages']['python']==2
    assert any(c['target'].endswith('/users/{}') for c in index['network_calls'])
    assert any(e['source']=='app.py' and e['target']=='src/api.py' for e in index['import_edges'])
    assert any('unsafe path' in w for w in index['warnings'])
    old,new=contracts(); changes=ContractDiffService().diff(old,new)
    impacts,files=UsageAnalyzer().analyze(changes,index,True)
    assert any(i.file=='src/api.py' and i.match_type in {'templated_path','field_usage'} for i in impacts)
    assert any(f.file=='app.py' and f.propagated_distance==1 for f in files)
    patches=MigrationPlanner().plan(changes,impacts)
    assert any(p.kind=='replace_path' for p in patches)
    assert any(p.kind=='replace_field' for p in patches)
