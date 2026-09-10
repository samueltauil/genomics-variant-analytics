# Development Guide

The published executable surface is repository data hygiene. Additional infrastructure validation, write-test tooling and landing inventory have been implemented locally but are still uncommitted as of 2026-09-10. There is no application server, infrastructure deployment command, or end-to-end demo command yet.

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

The published baseline is 12 passing synthetic Git-repository tests and actionlint 1.7.12 validation of both workflows. The expanded local working tree passes **42 tests**: 12 hygiene, 18 infrastructure/write, and 12 landing-inventory tests. Strict OpenSpec validation also passes. No remote CI result is claimed for the uncommitted implementation. Fixtures must never contain biological data, real identifiers, or credentials.

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

Arrival means first observation in UTC, not exact transfer start; it survives growth and restarts. Missing files retain history with `present: false`. All discovered files remain `arriving`: stability/marker detection (2.2), failed-transfer/retry handling (2.3) and staging are not implemented. Do not treat the inventory as permission to stage data.

Both local tools reject UNC/device paths and symlink/reparse redirects; on Windows they require fixed local drives. These guards are not a sandbox against path races or every POSIX mount mechanism. Use synthetic data and trusted directories. Keep generated inventories outside Git; `.sqlite3` files and their sidecars are ignored in the implementation working tree. Detailed local usage is in `infra/README.md` and `docs/landing-inventory.md`, which are not yet published.

Azure login, subscription discovery, provisioning, uploads, benchmarks and teardown remain paused. No local test establishes cloud readiness or authorizes any of those actions.

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

Do not archive the entire change because individual tasks are complete. Task 1.1's live acceptance record is in [PR #10](https://github.com/samueltauil/genomics-variant-analytics/pull/10); task 1.2's secret-protection record is in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12). Both are pending review as of 2026-09-10. Task 2.1 is verified by 12 local synthetic tests, including scheduled discovery, metadata fields, persistence and failure guards. The local record is **3/89 completed**, with 86 pending; default-branch checkboxes remain stale. Cloud deployment and SMB acceptance are not implied by the scanner's local completion.

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