# API Evolution Assurance

Repository-aware semantic API evolution analysis that detects breaking changes, maps affected consumer code, propagates blast radius through repository dependencies, produces human-reviewable migration operations, and gates release with deterministic engineering evidence.

This project consolidates the useful assets from `api_to_app`, `code_review`, `mcp_scout`, and selected `multi_agent` concepts into a materially deeper developer-infrastructure system.

## Product thesis

Generic code review and generic API-to-frontend generation are increasingly commodity capabilities. The stronger technical problem is **software evolution**:

```text
old API contract
      +
new API contract
      +
consumer repository
      ↓
canonical semantic diff
      ↓
breaking-change model
      ↓
repository usage + dependency graph
      ↓
blast radius
      ↓
migration plan
      ↓
human-approved exact patches
      ↓
lint / types / tests / build gates
      ↓
release evidence / optional approved GitHub PR
```

YC's Fall 2026 Requests for Startups independently describes this category as **Self-Maintaining APIs**: `https://www.ycombinator.com/rfs?year=2026`.

## What is implemented

### Canonical contract ingestion

Supports:

- OpenAPI 3.x JSON/YAML;
- Swagger/OpenAPI 2.0 compatibility mode;
- local `$ref` resolution;
- path + operation parameters;
- required/optional transitions;
- request-body schemas;
- response status/schema models;
- security-required transitions;
- operation IDs and tags.

The canonical representation is intentionally smaller than the full OpenAPI specification so the diff engine can be deterministic and auditable.

### Semantic diff classes

The engine distinguishes:

- endpoint removed / added;
- operation path changed with stable `operationId`;
- parameter added / removed;
- requiredness changes;
- parameter type changes and enum narrowing;
- request-body requiredness;
- request property added / removed / type changed;
- response status added / removed;
- response property added / removed / type changed;
- authentication becoming required / optional.

Changes are classified as `breaking`, `potentially_breaking`, `non_breaking`, or `info` and carry migration hints plus evidence.

### Repository structural index

Uploaded ZIPs are safely extracted with traversal protection and bounded file limits.

Current analyzers:

- **Python:** standard-library AST for imports, symbols, string literals, network calls, attribute accesses, and subscript field access.
- **JavaScript / TypeScript / Svelte:** deterministic lexical structural analyzer for imports, function/class symbols, `fetch`, common `client.get/post/...` calls, string/template targets, and field access.

This is materially stronger than regex-only review, while keeping runtime dependencies minimal. A tree-sitter adapter is an explicit future extension for broader language coverage.

### API-usage matching

Breaking contract paths are matched against static and templated request targets. Property-removal/type changes are mapped to source field access. Field-only matches outside a directly matched API-call file are deliberately downgraded because common property names can create false positives.

### Blast radius

The repository index resolves local import edges where possible. Directly affected files are propagated through reverse dependency edges to a bounded distance, so callers of an impacted module are visible even when they do not call the API themselves.

### Migration planner

The planner emits typed operations:

- `replace_path`
- `replace_field`
- `replace_text`
- `manual`

Likely field renames are inferred only when removed/added schema fields have compatible types and sufficient name similarity.

### Human-approved patch application

Automatic application is intentionally narrow:

- a patch must be explicitly selected;
- the request must send `human_approved=true`;
- only deterministic replacement patch kinds are eligible;
- the old text must occur **exactly once on the evidence line**;
- ambiguous patches are skipped rather than guessed;
- the service creates a copied repository plus `API_EVOLUTION_PATCH.diff` ZIP artifact.

No patch is silently written back to the original uploaded repository snapshot.


### Optional GitHub pull-request publication

After local patch review, the service can publish the approved migration as a new GitHub branch and pull request. This path is deliberately gated:

- `human_approved=true` is mandatory;
- the approved patch IDs are re-applied through the deterministic patch service;
- only files with an `applied` outcome are written to the Git tree;
- the GitHub token is deployment-side only (`AEA_GITHUB_TOKEN`) and is never accepted from browser/request payloads;
- branch creation fails closed if GitHub rejects the target/ref instead of force-updating an existing branch.

The adapter uses GitHub's versioned Git database REST API to create a tree, commit and branch ref, then creates a pull request.

### Tool / validation registry

The system adapts the useful capability-routing idea from `mcp_scout` into an engineering tool plan. It detects applicable gates such as:

- built-in canonical diff;
- built-in structural repository index;
- Ruff;
- pytest;
- mypy;
- Pyright;
- npm `check`;
- npm `test`;
- npm `build`.

The service does not compete with these tools; it uses their outputs as evidence.

## Execution safety

**Uploaded repositories are never executed by default.**

There are two interlocks:

1. request: `allow_trusted_execution=true`;
2. deployment: `AEA_ALLOW_LOCAL_EXECUTION=1`.

Both must be enabled before project commands can run. For a real multi-tenant public service, the second interlock should only exist inside an isolated, disposable runner/container with network and resource controls. The default API container leaves it disabled.

## Release gate

The analysis returns one of:

- `pass`
- `review_required`
- `blocked`

A direct repository usage affected by a breaking contract change blocks release until migration/review. A breaking contract change with no proven usage still requires human review because dynamic/generated calls can evade static analysis. Failing/timeout validation gates also block release.

## API

```text
GET  /api/v1/health
POST /api/v1/contracts/upload
POST /api/v1/repositories/upload
POST /api/v1/assurance
GET  /api/v1/analyses/{analysis_id}
POST /api/v1/analyses/{analysis_id}/patches/apply
POST /api/v1/analyses/{analysis_id}/github/pr
GET  /api/v1/artifacts/{artifact}.zip
```

Interactive API docs: `/docs`.

## Quick demo

Fixtures are provided in `examples/`:

- `openapi_v1.yaml`
- `openapi_v2.yaml`
- `demo_consumer_repo.zip`

They demonstrate:

- `/users/{id}` → `/accounts/{id}` operation-path migration;
- response `email` → `primary_email` field migration;
- a new required `X-Tenant-ID` header on `POST /orders`;
- a new required request property `quantity`.

## Run locally

```bash
# API
cd apps/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Web
cd apps/web
npm ci
npm run dev -- --host 0.0.0.0
```

Or:

```bash
docker compose up --build
```

## Tests

```bash
make check
```

Current backend regression suite covers:

- response-field rename detection;
- operation-ID-preserving path changes;
- new required parameter classification;
- Python/JS repository structural indexing;
- safe ZIP path handling;
- direct usage matching;
- import-graph blast-radius propagation;
- migration planning;
- default no-execution safety policy;
- exact human-approved patch application and unified diff output;
- GitHub Git-database branch/commit/PR publication through a mocked transport (no live credential required in tests).

## Production extensions

The current repository is a strong production-shaped portfolio checkpoint. The next infrastructure layer for a hosted commercial service would be:

1. isolated disposable execution workers (Firecracker/gVisor/container sandbox);
2. GitHub App installation/OAuth as the preferred multi-tenant credential model instead of a deployment token;
3. tree-sitter language adapters beyond Python/JS/TS;
4. provider-specific changelog/webhook ingestion;
5. contract version history and customer-repository subscription graph;
6. patch evaluation benchmarks across recorded API mutations;
7. tenancy, auth, encryption, retention, and audit logging.

