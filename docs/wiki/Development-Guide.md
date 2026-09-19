# Development Guide

The default-branch baseline includes repository data hygiene, local infrastructure validation, write-test tooling, landing completeness, reference-submission, metadata-model, variant-store, governance, analytics, MCP, and engineering-workflow changes, all merged into `main` as of 2026-09-19. There is no application server or end-to-end cloud demo command; local harnesses and a disposable, now torn-down Azure deployment are the current evidence.

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

The full local test suite passes **299 tests** (verified 2026-09-19 on Windows), covering hygiene, infrastructure/write, landing-inventory/completeness, reference-submission, metadata, variant-store, governance, analytics, MCP, secret-scanning, and engineering-workflow checks. Strict OpenSpec validation also passes. Fixtures must never contain biological data, real identifiers, or credentials.

## Local-Only Implementation

The following commands are available from a fresh checkout of `main`. Implementation publication does not authorize Azure operations. Local Azurite configuration, databases and storage directories are ignored; existing runtime files are not deleted.

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

Stability is not proof of success: a writer can pause or leave a truncated file. Task 2.3 therefore declares failure only against a transfer manifest in which the sending run states each file's expected size, paired with a stall deadline; without that manifest the scanner classifies no failure and holds nothing as complete for that run. Do not treat this inventory as permission to stage data; staging (tasks 3.1-3.3) reads only files this scanner reports complete.

Both landing tools reject UNC/device paths and symlink/reparse redirects; on Windows they require fixed local drives. These guards are not a sandbox against path races or every POSIX mount mechanism. Use synthetic data and trusted directories. Keep generated inventories outside Git; `.sqlite3` files and their sidecars are ignored. Detailed current usage is in the development working tree's `infra/README.md` and `docs/landing-inventory.md`.

The new `scripts/validate_submission.py` CLI accepts three trusted local JSON paths through `--request`, `--compatibility` and `--inventory`. It requires an exact workflow version, one explicit genome version and the complete compatible annotation set. Missing or incompatible versions fail without a default build. URI/checksum metadata and canonical-JSON manifest digests are pinned in its output; URIs are not resolved or downloaded. It always reports `compute_allocated: false` and `azure_readiness: not-evaluated`.

The Python `submit_workflow` API validates the explicit build and immutable published manifests before calling an injected allocator. The companion `submit_run` API validates a trusted inventory document. Twenty-one synthetic tests verify ordering and rejection cases. Payload scientific validation, attestation and cloud access are not established by synthetic fixtures. See the [reference-submission guide](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/reference-submission.md) for full schemas and examples.

The local `scripts.metadata_store.MetadataStore` Python API implements tasks 6.1 through 6.4 with synthetic entity identifiers, typed parent links, required file details and metadata-only archival. It persists full-chain ancestry, rejects invalid writes atomically, and returns snapshot-consistent traces. Twenty-one tests cover these rules, producer references, legacy backfill, archival, persistence and path guards:

```powershell
python -m unittest discover -s tests -p test_metadata_store.py -v
```

Use a trusted absolute local database path, separate from the landing inventory, and close the store through its context manager. New artifacts require `file_metadata`; register processing producers with `add_pipeline_run`, retrieve details with `get_artifact`, and mark archival with `archive_artifact`. Version-1 stores upgrade without invented metadata and require explicit `backfill_file_metadata` for legacy files. This is not a CLI. Clinical/research access grants (6.5) are now implemented as a separate local governance layer (see [Data Model and Provenance](Data-Model-and-Provenance#local-metadata-implementation)); actual storage lifecycle and real pipeline integration remain pending. The [metadata model page](Data-Model-and-Provenance#local-metadata-implementation) links the current API and usage guide.

Azure login, subscription discovery, provisioning, uploads and benchmarks were authorized on 2026-09-10 in a disposable sandbox subscription; that environment was fully torn down on 2026-09-18. A separate fresh deployment now exists in `rg-genomics-20260919` under the authorized USD 150 total ceiling and an October 3, 2026 expiry tag. Its verification VM is deallocated, while storage and networking resources remain. Fresh object-storage and Storage Actions deployments failed. No local test or resource-group success state alone establishes cloud readiness; use only recorded component acceptance evidence.

## Deploying and Verifying an Environment

Deployment creates billable resources. Run the plan first, and tear down when finished.

```powershell
./scripts/Deploy-Accelerator.ps1 -EnvironmentName demo -Location eastus2 -WhatIf
./scripts/Deploy-Accelerator.ps1 -EnvironmentName demo -Location eastus2 -ExpiresInDays 1
./scripts/Test-Environment.ps1 -SkipThroughput
./scripts/Test-Staging.ps1
./scripts/Test-StagingIntegrity.ps1
./scripts/Publish-Reference.ps1
./scripts/Test-ReferenceData.ps1
./scripts/Remove-Accelerator.ps1 -EnvironmentName demo
```

Deployment is idempotent and re-runnable. Every resource is tagged `project=genomics-variant-accelerator` and `lifecycle=disposable-test` with an `expiresOn` date, and the teardown script refuses a resource group that lacks the project tag. Concrete subscription, tenant and resource names are written to an untracked `.azure/environment.env.json`; this repository and its wiki are public, so those values never belong in a committed file.

`Test-Environment.ps1` checks the folder taxonomy, the staging and processing grants, and the SMB mount, and takes a 100 GiB throughput measurement unless `-SkipThroughput` is passed. `Test-Staging.ps1` seeds one stable file and one that grows between two inventories, then proves the pipeline copies only the complete one. `Test-StagingIntegrity.ps1` checksum-verifies a staged artifact, then corrupts the destination on purpose and confirms the record turns failed and drops out of the downstream set; re-run `Test-Staging.ps1` afterwards to restore an intact copy. All three drive the in-network client through `az vm run-command`, because the storage data planes are private.

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

Do not archive the entire change because individual tasks are complete. Ingestion, taxonomy, staging and reference tasks carry measured cloud evidence in addition to local tests; the Delta variant store, metadata, governance, analytics, and MCP tasks carry local synthetic evidence only. The development record is **71/89 completed**, with 18 pending: Purview lineage and lifecycle tiering (3.4, 3.5); Batch/Slurm/Lustre execution and concordance (5.2-5.4, 5.7); private-endpoint-only deployment (8.7); Azure OIDC, independently approved environment deployment, and ACR-hosted build/SBOM attestation (10.1, 10.2, 10.4, 10.5); demo parameterization, idempotency, cost, and bring-up documentation (11.3-11.7); and the full seven-step demo run plus end-to-end release trace (12.1, 12.3). The maintainer authorized zero required approvals on 2026-09-10; PRs and required checks remain in place, but the earlier independent-review/direct-push guarantee no longer applies.

## Practical Lessons

- A forbidden file still fails when deleted or renamed in a later introduced commit. Remove prohibited content from the proposed history rather than disguising it.
- Stemless filenames such as `.vcf` need explicit coverage; Python path suffix parsing alone does not identify them reliably.
- For generated Git-tree tests on Windows, write byte-exact stdin with explicit line endings. PowerShell text pipelines can append a carriage return to a filename passed to `git mktree`.
- Test an administrator push of a passing but unapproved PR head. A zero-approval policy allowed a green, already-open PR to fast-forward during initial acceptance.
- A Python SQLite connection context manager handles transactions but does not close the connection. Close it explicitly, including in tests, to release Windows file locks before temporary-directory cleanup.
- Set `NO_COLOR=1` and `TERM=dumb` for captured PowerShell test output when asserting formatted field values.
- A governed subscription may silently override template values. Read the resource back after deploying rather than trusting that the template was applied; `publicNetworkAccess` and `allowSharedKeyAccess` were both reset by policy here.
- Azure Resource Manager can accept a misplaced property and ignore it. `smbOAuthSettings` belongs under `azureFilesIdentityBasedAuthentication`; writing it at the top level returned success and changed nothing, which looked exactly like an unsupported feature.
- Check the API version before concluding a property is unavailable. The same write succeeded once the storage resource moved to `2025-08-01`.
- Incremental deployment does not delete role assignments removed from a template. Prune stale grants explicitly, or least privilege quietly decays.
- `az vm run-command invoke --scripts` splits on whitespace. Pass a script file with `@path` and Unix line endings; the remote shell is `dash`, so avoid `set -o pipefail`.
- Piping Azure CLI output in PowerShell resets `$LASTEXITCODE`. Capture the exit code before piping, or a failed command reads as success.
- Never let a deployment script fall back to whatever subscription the CLI happens to have selected. The default changed mid-session here and a deploy targeted the wrong subscription; only a `Forbidden` response prevented it. Prefer the recorded environment and pass the subscription explicitly.
- Test the teardown path before you need it. A `$variable:` inside a double-quoted string is parsed as a scope reference, which left the removal script unrunnable until a dry run exposed it.
- An immutability policy blocks container and account deletion. Create it unlocked in disposable environments and remove it before teardown; a locked policy cannot be removed until retention expires.

## Maintaining the Wiki

The Markdown sources are under `docs/wiki` on `main`, reviewed through the repository's normal pull-request checks. The live wiki is a separate Git repository that mirrors them. `Home.md` is the landing page; `_Sidebar.md` supplies navigation. Links without file extensions name wiki pages. Keep the sources reviewable through code-repository PRs; the wiki's own Git history does not pass through this repository's required checks.

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
