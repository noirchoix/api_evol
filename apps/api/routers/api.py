from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.config import settings
from repositories.store import AssuranceStore
from schemas.models import (
    AssuranceRequest, AssuranceResponse, ContractUploadResponse, GitHubPRRequest, GitHubPRResponse, HealthResponse, PatchApplyRequest,
    PatchApplyResponse, PatchOperation, RepositoryUploadResponse,
)
from services.assurance_service import AssuranceService
from services.contract_parser import ContractParseError, ContractParser
from services.patch_service import PatchService
from services.github_service import GitHubIntegrationError, GitHubPRService
from services.repository_service import RepositoryError, RepositoryService

router=APIRouter()
store=AssuranceStore(); parser=ContractParser(); repositories=RepositoryService(); assurance=AssuranceService(store); patches=PatchService(settings.data_dir/'artifacts')


@router.get('/health',response_model=HealthResponse)
def health() -> HealthResponse:
    analyses,repos=store.counts(); return HealthResponse(ok=True,app_name=settings.app_name,environment=settings.environment,analyses=analyses,repositories=repos)


@router.post('/contracts/upload',response_model=ContractUploadResponse)
async def upload_contract(file:UploadFile=File(...)) -> ContractUploadResponse:
    data=await file.read(settings.max_upload_bytes+1)
    if len(data)>settings.max_upload_bytes: raise HTTPException(status_code=413,detail='Contract upload exceeds configured size limit.')
    name=file.filename or 'openapi.yaml'
    try: contract=parser.parse(name,data)
    except ContractParseError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    cid='ctr_'+contract.sha256[:16]; store.put_contract(cid,name,contract.model_dump(mode='json'))
    return ContractUploadResponse(contract_id=cid,source_name=name,sha256=contract.sha256,title=contract.title,version=contract.version,openapi_version=contract.openapi_version,operation_count=len(contract.operations),warnings=contract.warnings)


@router.post('/repositories/upload',response_model=RepositoryUploadResponse)
async def upload_repository(file:UploadFile=File(...)) -> RepositoryUploadResponse:
    data=await file.read(settings.max_upload_bytes+1)
    if len(data)>settings.max_upload_bytes: raise HTTPException(status_code=413,detail='Repository upload exceeds configured size limit.')
    sha=hashlib.sha256(data).hexdigest(); rid='repo_'+sha[:16]
    try: root,index=repositories.extract_and_index(rid,file.filename or 'repository.zip',data)
    except RepositoryError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    store.put_repository(rid,file.filename or 'repository.zip',sha,str(root),index)
    return RepositoryUploadResponse(repository_id=rid,filename=file.filename or 'repository.zip',sha256=sha,file_count=len(index.get('files') or {}),languages=index.get('languages') or {},network_call_count=len(index.get('network_calls') or []),import_edge_count=len(index.get('import_edges') or []),warnings=index.get('warnings') or [])


@router.post('/assurance',response_model=AssuranceResponse)
def run_assurance(req:AssuranceRequest) -> AssuranceResponse:
    try: return assurance.analyze(req.old_contract_id,req.new_contract_id,req.repository_id,req.allow_trusted_execution,req.propagate_import_impacts)
    except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc


@router.get('/analyses/{analysis_id}',response_model=AssuranceResponse)
def get_analysis(analysis_id:str) -> AssuranceResponse:
    item=store.get_analysis(analysis_id)
    if not item: raise HTTPException(status_code=404,detail='Analysis not found.')
    return AssuranceResponse.model_validate(item)


@router.post('/analyses/{analysis_id}/patches/apply',response_model=PatchApplyResponse)
def apply_patches(analysis_id:str,req:PatchApplyRequest) -> PatchApplyResponse:
    if not req.human_approved: raise HTTPException(status_code=409,detail='Explicit human_approved=true is required before patch application.')
    item=store.get_analysis(analysis_id)
    if not item: raise HTTPException(status_code=404,detail='Analysis not found.')
    analysis=AssuranceResponse.model_validate(item); repo_id=str(analysis.metadata.get('repository_id') or '')
    repo=store.get_repository(repo_id)
    if not repo: raise HTTPException(status_code=404,detail='Repository snapshot no longer exists.')
    patch_models=[PatchOperation.model_validate(p.model_dump(mode='json')) for p in analysis.patch_plan]
    unknown=set(req.approved_patch_ids)-{p.id for p in patch_models}
    if unknown: raise HTTPException(status_code=422,detail=f'Unknown patch ids: {sorted(unknown)}')
    return patches.apply(analysis_id,Path(repo['root_path']),patch_models,req.approved_patch_ids)


@router.post('/analyses/{analysis_id}/github/pr', response_model=GitHubPRResponse)
def create_github_pr(analysis_id: str, req: GitHubPRRequest) -> GitHubPRResponse:
    if not req.human_approved:
        raise HTTPException(status_code=409, detail='Explicit human_approved=true is required before publishing a GitHub PR.')
    item = store.get_analysis(analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail='Analysis not found.')
    analysis = AssuranceResponse.model_validate(item)
    repo_id = str(analysis.metadata.get('repository_id') or '')
    repo_snapshot = store.get_repository(repo_id)
    if not repo_snapshot:
        raise HTTPException(status_code=404, detail='Repository snapshot no longer exists.')
    patch_models = [PatchOperation.model_validate(p.model_dump(mode='json')) for p in analysis.patch_plan]
    unknown = set(req.approved_patch_ids) - {p.id for p in patch_models}
    if unknown:
        raise HTTPException(status_code=422, detail=f'Unknown patch ids: {sorted(unknown)}')
    patch_result = patches.apply(analysis_id, Path(repo_snapshot['root_path']), patch_models, req.approved_patch_ids)
    branch = req.branch_name.strip() or f'api-evolution/{analysis_id}'
    github = GitHubPRService(settings.github_token, settings.github_api_url, settings.github_api_version)
    try:
        return github.create_pull_request(
            owner=req.owner, repo=req.repo, base_branch=req.base_branch, branch_name=branch,
            title=req.title, body=req.body, artifact_root=settings.data_dir/'artifacts',
            patch_result=patch_result, patches=patch_models,
        )
    except GitHubIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get('/artifacts/{artifact_name}')
def download_artifact(artifact_name:str):
    if '/' in artifact_name or '\\' in artifact_name or not artifact_name.endswith('.zip'):
        raise HTTPException(status_code=400,detail='Invalid artifact name.')
    path=settings.data_dir/'artifacts'/artifact_name
    if not path.exists(): raise HTTPException(status_code=404,detail='Artifact not found.')
    return FileResponse(path,media_type='application/zip',filename=artifact_name)
