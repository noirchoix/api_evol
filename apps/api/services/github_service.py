from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import httpx

from schemas.models import GitHubPRResponse, PatchApplyResponse, PatchOperation


class GitHubIntegrationError(RuntimeError):
    pass


_SAFE_REPO = re.compile(r'^[A-Za-z0-9_.-]+$')
_SAFE_BRANCH = re.compile(r'^[A-Za-z0-9._/-]+$')


class GitHubPRService:
    """Create a review branch and PR using GitHub's Git database REST API.

    No token is accepted from request bodies. Credentials are deployment secrets.
    The service writes only files proven to have an ``applied`` deterministic patch
    outcome from the local, human-approved patch service.
    """

    def __init__(
        self,
        token: str,
        api_url: str = 'https://api.github.com',
        api_version: str = '2026-03-10',
        transport: httpx.BaseTransport | None = None,
    ):
        self.token = token.strip()
        self.api_url = api_url.rstrip('/')
        self.api_version = api_version
        self.transport = transport

    def _validate_target(self, owner: str, repo: str, base_branch: str, branch_name: str) -> None:
        if not self.token:
            raise GitHubIntegrationError('GitHub integration is disabled: AEA_GITHUB_TOKEN is not configured.')
        if not _SAFE_REPO.fullmatch(owner) or not _SAFE_REPO.fullmatch(repo):
            raise GitHubIntegrationError('GitHub owner/repository contains unsupported characters.')
        for value, label in ((base_branch, 'base_branch'), (branch_name, 'branch_name')):
            if not value or not _SAFE_BRANCH.fullmatch(value) or '..' in value or value.startswith('/') or value.endswith('/'):
                raise GitHubIntegrationError(f'Invalid GitHub {label}.')

    def _request(self, client: httpx.Client, method: str, path: str, **kwargs) -> dict:
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get('message') or response.text
            except Exception:
                detail = response.text
            raise GitHubIntegrationError(f'GitHub API {method} {path} failed ({response.status_code}): {detail[:500]}')
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubIntegrationError('GitHub API returned an unexpected response shape.')
        return payload

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        base_branch: str,
        branch_name: str,
        title: str,
        body: str,
        artifact_root: Path,
        patch_result: PatchApplyResponse,
        patches: list[PatchOperation],
    ) -> GitHubPRResponse:
        self._validate_target(owner, repo, base_branch, branch_name)
        applied_ids = {o.patch_id for o in patch_result.outcomes if o.status == 'applied'}
        if not applied_ids:
            raise GitHubIntegrationError('No deterministic approved patches were applied; refusing to create an empty PR.')

        patch_by_id = {p.id: p for p in patches}
        files = sorted({patch_by_id[i].file for i in applied_ids if i in patch_by_id})
        work = artifact_root / patch_result.artifact_id
        tree_entries: list[dict] = []
        for rel in files:
            target = (work / rel).resolve()
            try:
                target.relative_to(work.resolve())
            except ValueError as exc:
                raise GitHubIntegrationError(f'Patched path escaped artifact root: {rel}') from exc
            if not target.is_file():
                raise GitHubIntegrationError(f'Patched file no longer exists: {rel}')
            try:
                content = target.read_text(encoding='utf-8')
            except UnicodeDecodeError as exc:
                raise GitHubIntegrationError(f'GitHub PR publishing currently supports UTF-8 text patches only: {rel}') from exc
            mode = '100755' if target.stat().st_mode & 0o111 else '100644'
            tree_entries.append({'path': rel, 'mode': mode, 'type': 'blob', 'content': content})

        headers = {
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {self.token}',
            'X-GitHub-Api-Version': self.api_version,
            'User-Agent': 'api-evolution-assurance',
        }
        repo_path = f'/repos/{owner}/{repo}'
        with httpx.Client(base_url=self.api_url, headers=headers, timeout=30.0, transport=self.transport) as client:
            base_ref = self._request(client, 'GET', f'{repo_path}/git/ref/heads/{quote(base_branch, safe="/")}')
            base_sha = str(((base_ref.get('object') or {}).get('sha')) or '')
            if not base_sha:
                raise GitHubIntegrationError('GitHub base branch response did not contain a commit SHA.')
            base_commit = self._request(client, 'GET', f'{repo_path}/git/commits/{base_sha}')
            base_tree = str(((base_commit.get('tree') or {}).get('sha')) or '')
            if not base_tree:
                raise GitHubIntegrationError('GitHub base commit response did not contain a tree SHA.')
            new_tree = self._request(client, 'POST', f'{repo_path}/git/trees', json={'base_tree': base_tree, 'tree': tree_entries})
            tree_sha = str(new_tree.get('sha') or '')
            if not tree_sha:
                raise GitHubIntegrationError('GitHub tree creation did not return a SHA.')
            commit = self._request(
                client,
                'POST',
                f'{repo_path}/git/commits',
                json={'message': title, 'tree': tree_sha, 'parents': [base_sha]},
            )
            commit_sha = str(commit.get('sha') or '')
            if not commit_sha:
                raise GitHubIntegrationError('GitHub commit creation did not return a SHA.')
            self._request(client, 'POST', f'{repo_path}/git/refs', json={'ref': f'refs/heads/{branch_name}', 'sha': commit_sha})
            pr_body = body.strip() or (
                'Generated by API Evolution Assurance after semantic contract analysis, repository blast-radius analysis, '
                'deterministic patch planning, and explicit human approval.\n\n'
                f'Patch artifact: `{patch_result.artifact_id}`\nApplied patches: {", ".join(sorted(applied_ids))}'
            )
            pr = self._request(
                client,
                'POST',
                f'{repo_path}/pulls',
                json={'title': title, 'body': pr_body, 'head': branch_name, 'base': base_branch},
            )
            number = int(pr.get('number') or 0)
            url = str(pr.get('html_url') or '')
            if not number or not url:
                raise GitHubIntegrationError('GitHub pull request response was missing number or URL.')

        return GitHubPRResponse(
            pull_number=number,
            pull_url=url,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            artifact_id=patch_result.artifact_id,
            applied_patch_ids=sorted(applied_ids),
        )
