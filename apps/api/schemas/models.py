from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

Severity = Literal['breaking','potentially_breaking','non_breaking','info']
Confidence = Literal['low','medium','high']


class HealthResponse(BaseModel):
    ok: bool
    app_name: str
    environment: str
    analyses: int
    repositories: int
    deterministic_core: bool = True


class CanonicalParameter(BaseModel):
    name: str
    location: str
    required: bool = False
    schema_type: str = 'unknown'
    schema_format: str = ''
    enum: list[Any] = Field(default_factory=list)


class CanonicalSchema(BaseModel):
    type: str = 'unknown'
    required: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    nullable: bool = False


class CanonicalOperation(BaseModel):
    key: str
    method: str
    path: str
    operation_id: str = ''
    summary: str = ''
    parameters: list[CanonicalParameter] = Field(default_factory=list)
    request_required: bool = False
    request_schema: CanonicalSchema | None = None
    responses: dict[str, CanonicalSchema] = Field(default_factory=dict)
    security_required: bool = False
    tags: list[str] = Field(default_factory=list)


class CanonicalContract(BaseModel):
    title: str
    version: str
    openapi_version: str
    source_name: str
    sha256: str
    operations: dict[str, CanonicalOperation]
    warnings: list[str] = Field(default_factory=list)


class ContractUploadResponse(BaseModel):
    contract_id: str
    source_name: str
    sha256: str
    title: str
    version: str
    openapi_version: str
    operation_count: int
    warnings: list[str]


class RepositoryUploadResponse(BaseModel):
    repository_id: str
    filename: str
    sha256: str
    file_count: int
    languages: dict[str,int]
    network_call_count: int
    import_edge_count: int
    warnings: list[str]


class ChangeEvidence(BaseModel):
    id: str
    source: str
    detail: str


class ContractChange(BaseModel):
    id: str
    severity: Severity
    category: str
    operation_key: str
    summary: str
    old: Any = None
    new: Any = None
    confidence: Confidence = 'high'
    migration_hint: str = ''
    evidence: list[ChangeEvidence] = Field(default_factory=list)


class NetworkCall(BaseModel):
    id: str
    file: str
    line: int
    client: str
    method: str = ''
    target: str
    literal: bool = True
    enclosing_symbol: str = ''


class UsageImpact(BaseModel):
    change_id: str
    file: str
    line: int
    symbol: str = ''
    match_type: Literal['exact_path','templated_path','field_usage','operation_id','dependency_propagation']
    confidence: Confidence
    evidence: str


class ImpactedFile(BaseModel):
    file: str
    direct_impacts: int
    propagated_distance: int = 0
    reasons: list[str] = Field(default_factory=list)


class PatchOperation(BaseModel):
    id: str
    file: str
    line: int | None = None
    kind: Literal['replace_text','replace_path','replace_field','manual']
    old_text: str = ''
    new_text: str = ''
    confidence: Confidence
    reason: str
    change_ids: list[str]
    requires_human_approval: bool = True


class ToolCapability(BaseModel):
    id: str
    name: str
    capability: str
    command: list[str] = Field(default_factory=list)
    safety: Literal['static','executes_project_code'] = 'static'
    detected: bool = False
    reason: str = ''


class ValidationResult(BaseModel):
    tool_id: str
    status: Literal['passed','failed','skipped','unavailable','timeout']
    command: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: str = ''
    stderr: str = ''
    evidence: str = ''


class AssuranceRequest(BaseModel):
    old_contract_id: str
    new_contract_id: str
    repository_id: str
    allow_trusted_execution: bool = False
    propagate_import_impacts: bool = True


class AssuranceResponse(BaseModel):
    analysis_id: str
    created_at: str
    old_contract: ContractUploadResponse
    new_contract: ContractUploadResponse
    repository: RepositoryUploadResponse
    changes: list[ContractChange]
    breaking_change_count: int
    usage_impacts: list[UsageImpact]
    impacted_files: list[ImpactedFile]
    patch_plan: list[PatchOperation]
    tool_plan: list[ToolCapability]
    validation: list[ValidationResult]
    release_gate: Literal['pass','review_required','blocked']
    release_gate_reasons: list[str]
    evidence_summary: list[str]
    limitations: list[str]
    metadata: dict[str,Any] = Field(default_factory=dict)

class PatchApplyRequest(BaseModel):
    approved_patch_ids: list[str] = Field(min_length=1)
    human_approved: bool = False


class PatchApplyOutcome(BaseModel):
    patch_id: str
    status: Literal['applied','skipped','failed']
    detail: str


class PatchApplyResponse(BaseModel):
    artifact_id: str
    applied: int
    skipped: int
    outcomes: list[PatchApplyOutcome]
    unified_diff: str
    download_path: str

class GitHubPRRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)
    base_branch: str = Field(default='main', min_length=1, max_length=200)
    branch_name: str = Field(default='', max_length=200)
    title: str = Field(default='API evolution migration', min_length=1, max_length=256)
    body: str = Field(default='', max_length=20000)
    approved_patch_ids: list[str] = Field(min_length=1)
    human_approved: bool = False


class GitHubPRResponse(BaseModel):
    pull_number: int
    pull_url: str
    branch_name: str
    base_branch: str
    commit_sha: str
    artifact_id: str
    applied_patch_ids: list[str]

