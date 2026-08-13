from __future__ import annotations

import json
from pathlib import Path

import httpx

from schemas.models import PatchApplyOutcome, PatchApplyResponse, PatchOperation
from services.github_service import GitHubPRService


def test_github_pr_uses_only_applied_patch_files(tmp_path: Path):
    artifact_root = tmp_path / 'artifacts'
    work = artifact_root / 'art_demo'
    work.mkdir(parents=True)
    (work / 'client.py').write_text('value = data.primary_email\n', encoding='utf-8')
    patch = PatchOperation(
        id='p1', file='client.py', line=1, kind='replace_field', old_text='email', new_text='primary_email',
        confidence='high', reason='rename', change_ids=['c1']
    )
    result = PatchApplyResponse(
        artifact_id='art_demo', applied=1, skipped=0,
        outcomes=[PatchApplyOutcome(patch_id='p1', status='applied', detail='ok')],
        unified_diff='diff', download_path='/artifact.zip'
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == 'GET' and '/git/ref/heads/main' in request.url.path:
            return httpx.Response(200, json={'object': {'sha': 'base123'}})
        if request.method == 'GET' and request.url.path.endswith('/git/commits/base123'):
            return httpx.Response(200, json={'tree': {'sha': 'tree123'}})
        if request.method == 'POST' and request.url.path.endswith('/git/trees'):
            assert body['base_tree'] == 'tree123'
            assert body['tree'][0]['path'] == 'client.py'
            assert 'primary_email' in body['tree'][0]['content']
            return httpx.Response(201, json={'sha': 'tree456'})
        if request.method == 'POST' and request.url.path.endswith('/git/commits'):
            return httpx.Response(201, json={'sha': 'commit789'})
        if request.method == 'POST' and request.url.path.endswith('/git/refs'):
            assert body == {'ref': 'refs/heads/api-evolution/demo', 'sha': 'commit789'}
            return httpx.Response(201, json={'ref': body['ref']})
        if request.method == 'POST' and request.url.path.endswith('/pulls'):
            assert body['head'] == 'api-evolution/demo' and body['base'] == 'main'
            return httpx.Response(201, json={'number': 42, 'html_url': 'https://github.test/acme/demo/pull/42'})
        return httpx.Response(500, json={'message': 'unexpected request'})

    service = GitHubPRService('secret', api_url='https://api.github.test', transport=httpx.MockTransport(handler))
    published = service.create_pull_request(
        owner='acme', repo='demo', base_branch='main', branch_name='api-evolution/demo', title='Migrate API', body='',
        artifact_root=artifact_root, patch_result=result, patches=[patch]
    )
    assert published.pull_number == 42
    assert published.commit_sha == 'commit789'
    assert published.applied_patch_ids == ['p1']
    assert len(calls) == 6
