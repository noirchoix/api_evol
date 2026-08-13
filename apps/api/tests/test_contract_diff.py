from __future__ import annotations
import json
from services.contract_parser import ContractParser
from services.contract_diff import ContractDiffService


def parse(obj,name='openapi.json'):
    return ContractParser().parse(name,json.dumps(obj).encode())


def base(path='/users/{id}',field='email'):
    return {'openapi':'3.1.0','info':{'title':'Demo','version':'1'},'paths':{path:{'get':{'operationId':'getUser','parameters':[{'name':'id','in':'path','required':True,'schema':{'type':'string'}}],'responses':{'200':{'content':{'application/json':{'schema':{'type':'object','required':['id',field],'properties':{'id':{'type':'string'},field:{'type':'string'}}}}}}}}}}}


def test_response_field_rename_is_breaking_with_candidate():
    old=base(field='email'); new=base(field='primary_email')
    changes=ContractDiffService().diff(parse(old,'old.json'),parse(new,'new.json'))
    removed=[c for c in changes if c.category.endswith('_property_removed')]
    assert removed and removed[0].severity=='breaking'
    assert removed[0].old['property']=='email'
    assert removed[0].new['rename_candidate']=='primary_email'


def test_operation_id_detects_path_change():
    old=base('/users/{id}'); new=base('/accounts/{id}')
    changes=ContractDiffService().diff(parse(old,'old.json'),parse(new,'new.json'))
    path=[c for c in changes if c.category=='path_changed']
    assert len(path)==1 and path[0].severity=='breaking'
    assert path[0].old['path']=='/users/{id}' and path[0].new['path']=='/accounts/{id}'


def test_new_required_parameter_is_breaking():
    old=base(); new=base(); new['paths']['/users/{id}']['get']['parameters'].append({'name':'tenant','in':'header','required':True,'schema':{'type':'string'}})
    changes=ContractDiffService().diff(parse(old,'old.json'),parse(new,'new.json'))
    assert any(c.category=='parameter_added' and c.severity=='breaking' for c in changes)
