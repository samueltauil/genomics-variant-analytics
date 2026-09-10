# Development Guide

The published baseline includes repository data hygiene. Earlier local infrastructure validation, write-test tooling and landing inventory are recorded in development commit `d89796e`. New completeness and reference-submission changes remain uncommitted as of 2026-09-10. There is no application server, infrastructure deployment command, or end-to-end demo command yet.

## Local Checks

Use Git and Python 3.10 or newer; the expanded local suite also requires PowerShell 7.2+ (`pwsh`). The scanners and tests use the standard library; no Python packages are required. From the repository root:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python -I scripts/check_data_hygiene.py --head HEAD
python -I scripts/check_data_hygiene.py --base origin/main --head HEAD
```

Fetch the current target branch before the comparison and substitute it for `origin/main` when needed. The scanner reads committed Git objects, not staged or untracked files. A clean working copy does not prove introduced history is clean.

| Exit code | Meaning |
|---|---|
| `0` | Inspection completed without policy violations |
| `1` | A policy violation was found |
| `2` | Inspection could not complete; do not treat this as a pass |

The original published baseline is 12 passing synthetic Git-repository tests and actionlint 1.7.12 validation of both workflows. The expanded local working tree passes **63 tests**: 12 hygiene, 18 infrastructure/write, 21 landing-inventory/completeness and 12 submission tests. Strict OpenSpec validation also passes. No remote CI result is claimed for the new uncommitted implementation. Fixtures must never contain biological data, real identifiers, or credentials.

## Local-Only Implementation

The following commands require the current development working tree; they are not yet available from a fresh checkout of `main`. This documentation publication does not publish the implementation files.

```powershell
./scripts/Invoke-Infrastructure.ps1 -Action Validate | ConvertTo-Json -Depth 4
./scripts/Test-LandingWrite.ps1 -Directory ([IO.Path]::GetTempPath()) -ByteCount 1048593
python -m unittest discover -s tests -p 'test_landing_scan.py' -v
```

The infrastructure validator checks schema, task references and dependency order for 12 candidate work packages. Only `Validate` is supported; it reports `TemplatesBuilt: false`, `AzureReadiness: not-evaluated` and `DeploymentSupported: false`. This is not an approved resource plan or a Bicep compilation. Resource-list and concrete-plan approval remain required before IaC generation.

The write harness accepts 1 byte to 1 GiB (default 16 MiB), writes a unique scratch file, flushes, verifies SHA-256 and removes the scratch file on normal close. It rejects network paths and redirected ancestors. Timing is a local smoke measurement affected by caching and repeated-buffer behavior, not the task 1.3 100 GiB SMB benchmark or evidence of a provisioned IOPS ceiling.

The task 2.1 scanner polls an existing trusted local directory, reads file metadata without opening payloads, and persists results in SQLite outside the landing root. For an existing synthetic run directory:

```powershell
python scripts/scan_landing.py --root "$env:TEMP\synthetic-landing" --inventory "$env:TEMP\landing-inventory.sqlite3" --polls 3 --interval-seconds 60
```

The first poll runs immediately, subsequent polls start after a post-scan delay, and each emits one JSON line. No background service is installed. A failed scan stops with a nonzero status and preserves the previous committed snapshot. Use one process per inventory and protect both stdout and the database as potentially sensitive metadata.

The default path convention is `SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R1_001.fastq.gz`. A full-path regex supplied through `--path-pattern` can extract named `run_id` and `sample_id` groups for other instrument layouts without renaming files. Unmatched names remain visible with null IDs and `metadata_error: unrecognized-path`.

Arrival means first observation in UTC, not exact transfer start; it survives growth and restarts. Missing files retain history with `present: false`. A recognized file becomes `complete` after two consecutive successful polls with identical size/mtime, or when an explicitly configured fresh vendor marker is observed. Later changes revoke completeness. Unknown IDs, missing files and marker files themselves are not complete payloads. Reports use schema version 2 and `completeness_evaluated: true`.

Optionally supply `--completion-marker '{run_id}/RTAComplete.txt'` with a new inventory database. Templates accept `{run_id}`, `{sample_id}` and `{path}`; the marker must stay within the root and be at least as new as the payload. This is an opt-in example, not an assumed instrument convention. The root, parsing pattern and marker policy are bound to the database. Existing task 2.1 databases upgrade in place with markers disabled.

Stability is not proof of success: a writer can pause or leave a truncated file. Task 2.3 requires trusted expected sizes/checksums or vendor failure signals and a timeout; that contract is unresolved. Failure/retry handling and staging remain pending. Do not treat this inventory as permission to stage data.

Both landing tools reject UNC/device paths and symlink/reparse redirects; on Windows they require fixed local drives. These guards are not a sandbox against path races or every POSIX mount mechanism. Use synthetic data and trusted directories. Keep generated inventories outside Git; `.sqlite3` files and their sidecars are ignored. Detailed current usage is in the development working tree's `infra/README.md` and `docs/landing-inventory.md`.

The new `scripts/validate_submission.py` CLI accepts three trusted local JSON paths through `--request`, `--compatibility` and `--inventory`. It requires an exact workflow version, one explicit genome version and the complete compatible annotation set. Missing or incompatible versions fail without a default build. URI/checksum metadata and canonical-JSON manifest digests are pinned in its output; URIs are not resolved or downloaded. It always reports `compute_allocated: false` and `azure_readiness: not-evaluated`.

The Python `submit_run` API validates before calling an injected allocator. Twelve synthetic tests verify this ordering and rejection cases. Task 4.3 remains pending until the real workflow uses the gate with a trusted published inventory. Payload checksums, availability, scientific compatibility, attestation and cloud access are not established by placeholder test manifests. See the uncommitted `docs/reference-submission.md` for full schemas and examples.

Azure login, subscription discovery, provisioning, uploads, benchmarks and teardown remain paused. No local test establishes cloud readiness or authorizes any of those actions. No resources were created by these local changes; existing subscription charges are unknown. Proceeding to billable deployment requires a numeric spending limit plus a dated, region-specific estimate from approved sizing and a separately authorized deployment.

## OpenSpec Workflow

The active change is `add-genomics-variant-accelerator`, using the `spec-driven` schema and repository-local planning artifacts. With OpenSpec available:

```sh
openspec status --change add-genomics-variant-accelerator --json
openspec instructions apply --change add-genomics-variant-accelerator --json
openspec validate add-genomics-variant-accelerator --strict
```

1. Read the relevant requirement, scenario, design decision, and task acceptance condition.
2. Implement the smallest testable change and add focused verification.
3. Record observations, not just commands. A successful local test does not establish a live service or repository control.
4. Mark a task complete only when every specified implementation and acceptance condition is verified. Leave blocked tasks unchecked and state the missing evidence.
5. Submit reviewed changes through a PR and keep the implementation, specs, and documentation coherent.

Do not archive the entire change because individual tasks are complete. Task 1.1's live acceptance record is in [PR #10](https://github.com/samueltauil/genomics-variant-analytics/pull/10); task 1.2's secret-protection record is in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12). Consult those PRs for current review state. Tasks 2.1 and 2.2 have 21 local synthetic tests covering discovery, metadata, persistence, slow writes and marker/stability behavior. The local record is **4/89 completed**, with 85 pending; default-branch checkboxes remain stale. Cloud deployment and SMB acceptance are not implied by local completion.

## Practical Lessons

- A forbidden file still fails when deleted or renamed in a later introduced commit. Remove prohibited content from the proposed history rather than disguising it.
- Stemless filenames such as `.vcf` need explicit coverage; Python path suffix parsing alone does not identify them reliably.
- For generated Git-tree tests on Windows, write byte-exact stdin with explicit line endings. PowerShell text pipelines can append a carriage return to a filename passed to `git mktree`.
- Test an administrator push of a passing but unapproved PR head. A zero-approval policy allowed a green, already-open PR to fast-forward during initial acceptance.
- A Python SQLite connection context manager handles transactions but does not close the connection. Close it explicitly, including in tests, to release Windows file locks before temporary-directory cleanup.
- Set `NO_COLOR=1` and `TERM=dumb` for captured PowerShell test output when asserting formatted field values.

## Maintaining the Wiki

The Markdown sources are under `docs/wiki` on the existing `docs/project-wiki` branch, reviewed through [draft PR #11](https://github.com/samueltauil/genomics-variant-analytics/pull/11); they are not yet on `main`. `Home.md` is the landing page; `_Sidebar.md` supplies navigation. Links without file extensions name wiki pages. Keep the sources reviewable through code-repository PRs; the wiki's Git history is separate and its direct edits do not pass through this repository's required checks.

GitHub must have an initial wiki page before its separate Git remote is available. Once `Home` has been created in the signed-in web UI:

```sh
git clone https://github.com/samueltauil/genomics-variant-analytics.wiki.git
```

Review existing wiki pages before copying approved Markdown sources into that clone, then commit and push using the wiki's existing default branch. Do not replace unrelated pages or force-push its history. Verify the rendered Home page, sidebar, internal links, and diagrams after publication. No automatic synchronization workflow is installed.

When adding knowledge, state whether it is observed, specified, or unresolved. Include a date for live state and a link to its source or acceptance evidence. Do not put secrets, genomic data, environment identifiers, unsupported customer claims, or clinical conclusions in either Git repository.

## Sources

- [Contributing guide](https://github.com/samueltauil/genomics-variant-analytics/blob/main/CONTRIBUTING.md)
- [Task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md)
- [Repository Guardrails](Repository-Guardrails)