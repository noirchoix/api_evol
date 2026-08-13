# Execution and Repository Security

Static repository analysis does not grant permission to execute code.

## Default mode

`AEA_ALLOW_LOCAL_EXECUTION=0`

The API may parse repository source, imports, network-call targets, and field access, but project commands are skipped.

## Trusted execution mode

Only enable project execution in an isolated runner. The request must also set `allow_trusted_execution=true`.

Recommended runner controls:

- ephemeral filesystem;
- no host mounts;
- outbound network disabled by default;
- CPU / memory / process / time limits;
- no cloud metadata access;
- no inherited application secrets;
- unprivileged UID;
- immutable base image;
- audit capture of command, exit code, stdout/stderr, and duration.

The included local subprocess runner sanitizes the environment and avoids `shell=True`, but it is **not** a replacement for OS/container isolation in a public multi-tenant deployment.

## GitHub publication security

GitHub PR publication is optional and disabled when `AEA_GITHUB_TOKEN` is empty. The token is read only from the server environment; clients cannot submit credentials in the API request.

The publisher:

- requires `human_approved=true`;
- publishes only patch IDs that produced a deterministic `applied` outcome;
- creates a new branch and does not force-update an existing ref;
- writes only UTF-8 text files changed by approved patch operations;
- does not publish the entire uploaded ZIP as an unreviewed repository replacement.

For multi-tenant deployment, replace a shared token with a GitHub App installation token scoped to the selected repository and minimum required Contents/Pull Requests permissions.

