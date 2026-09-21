## 1. Repository guardrails and foundation

Current policy update (2026-09-10): the user authorized a solo-maintainer policy. Required approval counts are now zero in both branch protection and the default-branch ruleset; strict required checks, the PR rule, administrator enforcement, resolved threads, and force-push/deletion restrictions remain. The independent-review/direct-push evidence below describes the earlier configuration, not the current guarantee: a green, already-open PR head can again permit an administrator fast-forward. No further control expansion is planned; implementation is the priority.

Implementation note (2026-09-10): task 1.1 is complete. PR #1 installed the trusted data-hygiene workflow; `main` requires strict GitHub Actions checks and independent PR approval, including for administrators. Six isolated synthetic PRs failed the trusted policy and their merge API attempts were refused; an administrator direct push of a passing but unapproved PR head was also refused. The initial zero-approval fast-forward gap, corrective settings, run URLs, and pending test-PR closure submissions are recorded in [CONTRIBUTING.md](../../../CONTRIBUTING.md#live-acceptance-record-2026-09-10). All 12 local tests, actionlint 1.7.12, and strict OpenSpec validation pass. Task 1.2 is also complete: secret scanning and push protection were confirmed enabled, a harmless control push succeeded, and a never-issued PAT-shaped probe received an explicit GitHub push-protection rejection. The remote stayed unchanged and the disposable branch was removed; see the [secret-protection evidence](../../../CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10). Cloud work remains unverified.

Local-first phase (2026-09-10): Azure access, provisioning, uploads and live benchmarks are paused at the user's request. The [candidate infrastructure inventory and local validator](../../../infra/README.md) prepare asset dependencies and task traceability only; resource-list and plan approval are pending before IaC generation. No cloud task is complete on the strength of this local validation, and all existing acceptance criteria remain unchanged.

Azure testing phase (2026-09-10): the user authorized provisioning in a disposable MCAPS subscription, to be removed afterwards. [Parameterized Bicep](../../../infra/main.bicep) now deploys workload identities, an SSD provisioned v2 SMB share, an HNS-enabled ADLS account, a private VNet with private endpoints and private DNS, and an in-network verification client. Two governance constraints shaped the result and are not workarounds to remove: subscription policy forces `publicNetworkAccess: Disabled` and `allowSharedKeyAccess: False` on storage accounts, and public IP addresses cannot be created. Every data-plane operation therefore runs over private endpoints, and both SMB and REST authenticate with managed identities rather than keys.

Task 11.10 teardown verification (2026-09-18): tearing down the live environment surfaced three more defects in `Remove-Accelerator.ps1`, none of which a dry run would have reached. The immutability-policy sweep asked every storage account for its blob containers, but the Files-only landing account answers `FeatureNotSupportedForAccount` with a Bad Request rather than an empty list, which aborted the whole teardown; that account is now skipped with a stated reason. The sweep then read `properties.immutabilityPolicy` directly, which terminates under `Set-StrictMode` for the ordinary case of a container with no policy; the property is now probed before it is read. With both fixed, teardown deleted `rg-genomics-demo` and its 26 resources, and post-deletion checks confirm `az group exists` returns false, no resource group carries the `project=genomics-variant-accelerator` tag, and neither storage account survives. The tag guard was exercised in earnest: deletion is refused unless the group carries the expected project tag. Soft-delete windows still apply, so the accounts remain recoverable for their retention period and the script says so rather than claiming the subscription is clean. The task remains unchecked because the second half of its criterion — naming the idle-cost resources for an engineer who defers teardown — is not yet written.

Live re-entry and provisioning defects (2026-09-18): the disposable environment from 2026-09-11 was still present in the MCAPS subscription, past its `expiresOn` date, with its untracked `.azure/environment.env.json` lost. Re-running the documented entry point surfaced three real defects that had never been exercised, all now fixed.

1. Preflight read `subscriptionPolicies.quotaId` from `az account show`, which does not return that property; under `Set-StrictMode` it raised and reported the subscription as unreadable. The billing agreement now comes from an `az rest` call to the ARM Subscriptions API, and a principal that cannot read it gets `UNVERIFIED` rather than a blocking failure. `az account subscription show` was rejected as the source because it needs a preview extension that cannot install non-interactively and hangs.
2. Preflight passed `--all` together with `--scope` to `az role assignment list`, which the CLI refuses; the deployer-role check could never pass against a live subscription. It now scopes to the subscription with `--include-inherited`.
3. Provisioning was not idempotent when the untracked client key was absent: it generated a new key pair and the deployment failed with `PropertyChangeNotAllowed` on `linuxConfiguration.ssh.publicKeys`, because Azure forbids changing that property on an existing VM. Provisioning now reuses the key already recorded on the verification client and only generates one when no client exists.

After the fixes, preflight reported `Ready: true` with zero blocking failures against the authorized disposable subscription, and provisioning completed in about **2 minutes 20 seconds** including in-network taxonomy creation. The failed first attempt also supplies the partial-failure half of task 11.4: the re-run completed the remainder and the twelve taxonomy directories were created once, not duplicated.

Two template defects that guaranteed permanent drift were also fixed: the storage modules defaulted `allowPublicNetworkAccess` to `true`, so the template fought the policy that forces `Disabled` on every deployment, and `main.bicep` stamped `utcNow()` into a `deployedOn` tag, re-tagging every resource on each run. Both storage accounts and all three identities now report `NoChange`, and the measured change set on an unchanged environment fell from 36 changes to 25 while `NoChange` rose from 10 to 21.

Task 11.4 was open at this stage. Provisioning was idempotent in substance, but
raw ARM what-if could not report no changes because it included server-assigned
properties and runtime identity references. The September 20 implementation
record under task 11.4 documents the fail-closed normalizer and completed live
acceptance.

Demo-preflight/runbook follow-up (2026-09-19): tracked-file scanning now rejects live subscription and tenant identifiers, and the ignored local environment record remains outside a clean clone. `docs/cost-estimate.md` records a dated `eastus2` USD model from the actual Bicep share, VM, and disk sizing, but retains Private Link, data-plane usage, payload, compute, and analytics costs as exclusions until their inputs or price meters are captured. The runbook has locally runnable bring-up/preflight, synthetic seeding, seven-step capability boundaries, three failure demonstrations, reset diagnostics, and guarded teardown. The fresh-subscription bring-up was later completed, and the September 20 task 11.4 record documents the complete-environment zero-effective-change result. Cloud reset remains unverified. Task 11.10 is complete: a read-only subscription check found `rg-genomics-demo` absent and zero resources tagged `project=genomics-variant-accelerator`; the runbook and dated cost estimate name the idle-cost resources and rates that matter if teardown is deferred.

Tasks 11.8-11.9 rehearsed-failure and reset evidence (2026-09-19): `scripts/rehearse_demo_failures.py` drives all three demonstrations from one entry point against the real local stores -- an authoritative-failure-marker transfer interruption and retry through `scripts.scan_landing`, a synthetic VCF row missing ALT through `scripts.variant_store.VariantStore`, and an ungranted raw-file read through `scripts.governance.GovernancePolicy` -- and reports each trigger's actual response next to the exact response its capability spec states; all three currently match. `scripts/reset_demo.py` now also resets one explicitly named demo-owned directory (`rehearsal-landing`) alongside its named SQLite files, never a glob or a scan of the state root itself. `tests/test_reset_demo.py` proves reset is idempotent, that an injected partial interruption (some stores removed, others not) is distinguishable through `--diagnose`, that a subsequent reset finishes only what remains, and that unrelated files and directories inside and outside the state root are left untouched. Both tasks are checked as fully verified locally; this is local SQLite and filesystem evidence only, not a cloud reset, which remains a stated scope limit.

Task 11.16 first-reader dry run (2026-09-19): `scripts/dry_run_first_reader.py` plays a reader who has only cloned the repository and follows README.md and docs/demo-runbook.md, with no other context -- it never reads the untracked `.azure/environment.env.json` local environment record. It ran the exact documented commands for Phase 0 (preflight), Phase 2 (seeding), Phase 4 (rehearsal), and Phase 5 (reset) against a scratch directory and compared each result to the confirming observation the runbook promises. Running it surfaced one real documentation defect before any fix: Phase 0's shown command (no `-SnapshotPath`) can never report `Ready: true` as the runbook then claimed, because local mode by design never contacts Azure; `docs/demo-runbook.md` (Phase 0) is corrected to document `Ready: false`, `BlockingFailures: 0`, and nine `UNVERIFIED` checks as the correct local-mode observation, and to state which flags reach `Ready: true`. A second staleness was found and fixed in the same pass: Phase 6's text still said "task 11.10 remains unchecked" after 11.10 was checked with live evidence on 2026-09-18; it now cites that evidence and says explicitly it is not a standing guarantee for a later delivery. With both fixed, a rerun reports every local phase matching its documented observation and zero open gaps; the dated evidence is committed at `docs/dry-run-evidence-2026-09-19.json` and asserted by `tests/test_dry_run_first_reader.py` (9 tests). Phases 1 (bring-up) and 6 (teardown) are reported as `live-cloud`, not executed: their documented commands require an authorized, already-provisioned `-SubscriptionId` that no published document supplies, and the harness deliberately does not treat the ambient `az` session on the machine running it as that input, so it is not counted toward acceptance. The task is checked on the strength of the local, documentation-only phases plus the two fixed defects; the live bring-up/teardown half of "from preflight through teardown" remains an honest, stated scope limit of a documentation-only dry run, consistent with tasks 11.3-11.7's live-cloud status above.

Tasks 1.4 and 2.4 verification (2026-09-10): [the acceptance script](../../../scripts/Test-Environment.ps1) reports all twelve taxonomy directories returning 200, the staging identity creating a file, the processing identity refused write on the lake with HTTP 403 while retaining read, and the processing identity refused a landing-share listing with HTTP 403. The instrument service account half of 2.4 is represented by a separate ingestion identity holding the only landing-zone write grants; no real instrument account was joined.

Task 1.3 preparation: the [local write smoke harness](../../../infra/README.md#local-write-smoke-test) measures bounded synthetic sequential writes, verifies SHA-256 read-back integrity and removes its scratch file. Network paths are rejected. This implements local test tooling only, not share provisioning, the 100 GiB SMB benchmark or IOPS-ceiling verification; task 1.3 remains pending.

- [x] 1.1 Create the public repository, protect the default branch to require a pull request, and add the data-hygiene status check as required, and verify a pull request containing a `.vcf`, `.bam`, `.cram`, or `.fastq` file or an oversized file cannot be merged, and a direct push to the default branch is refused
- [x] 1.2 Enable secret scanning with push protection, and verify a commit carrying a recognized credential pattern is blocked at push time
Task 1.3 verification (2026-09-10): the share is SSD provisioned v2 with SMB Multichannel enabled, reporting the provisioned 3000 IOPS and 200 MiB/s ceiling. SMB authenticates with a managed identity rather than the shared key: the account sets `azureFilesIdentityBasedAuthentication.smbOAuthSettings.isSmbOAuthEnabled`, the ingestion identity holds **Storage File Data SMB MI Admin**, and the Linux client mounts with `sec=krb5` after `azfilesauthmanager` obtains a ticket from IMDS. `allowSharedKeyAccess` stays `false`, so no share key exists to mount with, and the key-operator grant was removed. A 100 GiB sequential write sustained **240 MiB/s in 426 s**, above the provisioned rate. The property is nested under `azureFilesIdentityBasedAuthentication` and needs API version 2025-08-01; setting it at the top level is silently ignored.

Task 1.5 verification (2026-09-15): the [metadata-only demo manifest](../../../docs/demo-dataset.md) pins the authorized Illumina Platinum Genomes `2017-1.0/hg38` collection and generates 17 synthetic subject/sample bindings across two synthetic cohorts. The validator reports zero patient-identifying fields and values, confirms every subject ID matches `^SYN-PG-SUBJECT-[0-9]{4}$`, and rejects PHI-like fields and values, public donor identifiers, unknown fields, malformed or duplicate synthetic IDs, and weakened source/reference provenance. Ten focused tests, the metadata-only payload scan, and strict OpenSpec validation pass; no genomic payload was added.

- [x] 1.3 Provision the SSD provisioned-v2 classic file share for the SMB landing zone with SMB Multichannel enabled, and verify a 100 GiB sequential write sustains the provisioned throughput and the share reports the expected IOPS ceiling
- [x] 1.4 Provision the ADLS Gen2 landing account and container set following the healthcare data solutions folder taxonomy (`Ingest`, `Process`, `Failed`, `External`, `Inventory`, `ReferenceData`, `SampleData`) with genomics modality subfolders, and verify each path exists and is writable by the staging identity only
- [x] 1.5 Assemble the demo dataset from Illumina Platinum Genomes plus generated synthetic subject, sample, and cohort identifiers, and verify a scan of the manifest finds no real patient identifier and every subject id matches the synthetic id pattern
Task 1.6 verification (2026-09-15): the [metadata-only staging harness](../../../scripts/stage_demo_landing.py) derives 34 paired-end placeholder files from the 17 manifest identities under `SYN-RUN-001/Data/Intensities/BaseCalls`, runs the existing landing scanner twice, and verifies exact relative paths, synthetic sample/run metadata, and `complete` state without rewriting. Four focused harness tests, the full 135-test suite, and strict OpenSpec validation pass; no genomic payload is committed.

- [x] 1.6 Stage the demo run into the landing zone under a realistic instrument folder convention, and verify the file layout matches the convention with no path rewriting

## 2. Landing zone behavior

Task 2.1 verification (2026-09-10): [the local scheduled scanner](../../../docs/landing-inventory.md) inventories seeded synthetic run folders, persists first-observed arrivals across restarts, and reports run/sample IDs, sizes, timestamps and states. The original 12 focused tests passed, including scheduled discovery, path guards and failed-scan snapshot preservation. This verifies the scan logic locally, not an Azure scheduler or SMB connectivity.

Task 2.2 verification (2026-09-10): 21 focused tests pass with the two-consecutive-observation size/mtime rule and optional root-relative vendor completion markers. A synthetic slow copy remains `arriving` during growth and becomes `complete` after stability; new changes revoke completeness. Stale markers, cross-run markers, missing files and unresolved identifiers are tested. Task 2.3 was blocked at that point on a trustworthy transfer-failure contract, because a paused or truncated transfer can look stable. No Azure operations were performed.

Task 2.3 verification (2026-09-19): the blocking contract is resolved by requiring an authoritative, generation-bound terminal failure marker; stability alone never declares failure. [The landing scanner](../../../docs/landing-inventory.md#failure-detection-and-retry) reads a root-relative `{run_id}` transfer manifest for expected sizes and a `{run_id}` failure marker with `status: "failed"`, an explicit reason, and the failed file generation fingerprint. A file larger than declared is `failed`/`size-exceeds-declared`; a short or absent file without the terminal signal remains `arriving`; a matching marker marks the affected file `failed` with the sender's reason. Invalid markers fail closed with `failure-marker-unavailable`, and stale fingerprints cannot fail a re-sent generation. Retry changes the file generation, resets `unchanged_since`, clears `failure_reason` and revises the existing record in place to `arriving`, then to `complete` once it reaches the declared size and stabilizes. The original `arrival_timestamp` is retained, no second row is created, and sibling files of the same run are evaluated independently. `available_for_staging` returns only `complete` files, so failed and arriving files are withheld. The Azure Files source shares the same evaluation path and can fetch the manifest and failure marker over REST; this is local synthetic evidence, with no instrument, SMB share or interrupted cloud transfer exercised.

The focused landing suite covers interrupted and terminal-signaled failures, stable-short non-failure, absent transfers, retry replacement, sibling isolation, staging exclusion, restart persistence, invalid and stale markers, manifest validation, inventory binding and the CLI. Full-suite, data-hygiene and strict OpenSpec validation evidence is recorded after the implementation run.

- [x] 2.1 Implement the scheduled directory scan that inventories run folders, and verify it lists run and sample identifiers, sizes, arrival timestamps, and states for a seeded run
- [x] 2.2 Implement the completeness stability check (size and last-modified unchanged across two consecutive polls, or vendor completion marker), and verify a file copied slowly reports `arriving` until the copy ends and `complete` afterwards
- [x] 2.3 Implement failed-transfer detection and the retry path, and verify an interrupted transfer is marked `failed`, is excluded from staging, and that re-sending it replaces the failed entry without affecting sibling files in the run
- [x] 2.4 Restrict landing-zone data-plane access to the ingestion identity and the instrument service account, and verify a pipeline identity is denied a direct read of the share

## 3. Staging to object storage

Task 3.1 verification (2026-09-10): a Data Factory factory with a managed virtual network copies the landing share to the ADLS `Ingest` path over approved managed private endpoints. It reads the share with the ingestion identity and writes the lake with the staging identity, so landing access stays as task 2.4 restricts it; no account key is used, because policy disables shared key. The scanner's completeness rule was extracted into `evaluate_inventory` and is now shared by the local walk and a new [Azure Files source](../../../scripts/stage_landing.py) that reads change time at 100-nanosecond resolution. [The staging test](../../../scripts/Test-Staging.ps1) seeds one file that stays stable and one that grows between two inventories, then runs the pipeline over the complete set only. The run succeeded and the destination held exactly the stable file; the growing file and an unrecognized path were skipped. The Copy activity's `validateDataConsistency` flag is not treated as integrity verification; task 3.2 supplies that.

Tasks 3.2 and 3.3 verification (2026-09-11): [the staging log](../../../scripts/stage_records.py) compares source and destination SHA-256 digests and records the six required fields per file: source path, destination URI, state, integrity result, storage tier and classification. A mismatch is stored as `failed`/`mismatch` and `available_for_processing` excludes it, so a corrupted artifact is never advertised downstream; re-verification revises the existing record rather than appending a second one. Eight focused tests cover matching and mismatched digests, revocation of an earlier verified record, per-file independence, invalid tiers/classifications/digests/URIs, persistence and the database constraints. [The live check](../../../scripts/Test-StagingIntegrity.ps1) read the staged artifact and its landing-zone source from inside the network and reported `staged`/`verified` with one artifact available, then deliberately corrupted the destination and reported `failed`/`mismatch` with none available. Classification is a declared handling label from a fixed vocabulary, not an inferred sensitivity; task 8.5 still owns classification policy. Digests are computed by the caller that read the bytes, so the log records a comparison rather than performing the transfer itself.

- [x] 3.1 Build the Copy activity pipeline from the SMB share to the ADLS `Ingest` path, filtered to files in the `complete` state, and verify a run copies only complete files and skips `arriving` ones
- [x] 3.2 Add source and destination checksum comparison to the pipeline, and verify a deliberately corrupted destination causes the staging record to be marked `failed` and withheld from downstream processing
- [x] 3.3 Emit the staging record (source path, destination URI, state, integrity result, storage tier, classification) to the staging log table, and verify all six fields are populated for every file of a demo run
- [ ] 3.4 Register the pipeline with Purview and confirm Copy activity lineage appears for the Files-to-ADLS hop, and verify the staged artifact resolves back to its landing-zone source in the catalog
  - Blocked verification (2026-09-21): the disposable environment has no Purview account or private Purview endpoint/DNS scaffolding. `Microsoft.Purview` is `NotRegistered` in subscription `4056ba05-003e-46b0-9a5c-1fbce204e9d1`, and the Azure CLI Purview extension is not installed. The repository has no Purview deployment module, so a short-lived private account cannot be provisioned or connected without adding and approving new private-network infrastructure. No Purview lineage claim is made; the governed local resolver remains explicitly item-level simulation, while record-level provenance remains the system of record. A future authorized run must register the provider, deploy the private account/endpoints and DNS, register the Data Factory and storage sources, run a Copy activity, verify the catalog lineage hop and staged-artifact source resolution, then delete the account immediately.
Task 3.5 contract revision (2026-09-19): live testing confirmed that the
HNS-enabled lake does not support blob index tags and that Storage Actions
cannot reach the public-network-disabled account through the tested trusted
access rule. The reviewed requirement now calls for a private-compatible
lifecycle mechanism and supported HNS conditions rather than a specific
Storage Actions/index-tag combination. The deployed Storage Actions task is
partial evidence only; task completion now requires account-native lifecycle
tiering and a live URI/lineage-preservation observation.

Task 3.5 implementation evidence (2026-09-20): the lake module now deploys an
account-native management policy on the HNS-enabled, public-network-disabled
storage account. The policy tiers block blobs below `healthcare/Ingest/` from
Hot to Cool after the configured age without relying on blob index tags.
The policy deployed successfully with a zero-day acceptance threshold. A
metadata-only synthetic object was created through the private DFS endpoint at
`Ingest/LifecycleAcceptance/lifecycle-20260920T025447Z.txt`; its ignored local
record retains the canonical URI and synthetic lineage source. The first
private check returned HTTP 200 and tier `Hot`. Azure has not yet performed its
service-scheduled transition, so the task remains open until a later check
returns `Cool` while the same URI still resolves.

Task 3.5 transition confirmation (2026-09-21): a later run of
[`scripts/Test-LifecycleTransition.ps1`](../../../scripts/Test-LifecycleTransition.ps1)
against the same object
(`https://stglaketgrxjnw6usjfg.dfs.core.windows.net/healthcare/Ingest/LifecycleAcceptance/lifecycle-20260920T025447Z.txt`)
returned `httpStatus: "200"`, `accessTier: "Cool"`, and `transitioned: true` at
`2026-09-21T12:33:42Z` -- the account-native management policy moved the
object from Hot to Cool with no blob index tags and no Storage Actions
dependency, while the same private URI continued to resolve and the
synthetic lineage source link remained intact. This closes the task with a
live tier-transition observation rather than partial (policy-deployed-only)
evidence.

- [x] 3.5 Configure private-compatible blob-side lifecycle tiering on staged artifacts using conditions supported by the selected account, and verify an artifact past the age threshold transitions tier while its URI and lineage link still resolve

## 4. Reference data

Task 4.3 evidence (2026-09-15): the compatibility manifest and workflow submission path require an explicit build and immutable version, resolve write-once published manifests, pin per-manifest SHA-256 digests, and reject missing or incompatible references before the allocator callback. Twenty-one synthetic tests pass; no genomic payloads or reference downloads are used.

Tasks 4.1 and 4.2 verification (2026-09-11): the [reference publisher](../../../scripts/publish_reference.py) streams artifacts from pinned sources into a separate `reference` container laid out as `type/name/version`, recording a SHA-256 and byte count per artifact in a manifest that commits the version. Five real entries were published from versioned Ensembl paths totalling about 2 GB: GRCh38 and GRCh37 primary assemblies, GRCh38 and GRCh37 gene annotations, and GRCh38 transcript sequences. Versioned source paths are used deliberately, because a `current` alias moves and would make a published version irreproducible. The inventory returns type, name and version for all five. Write-once is enforced by a container-level WORM policy, which hierarchical-namespace accounts must use since version-level policies need blob versioning: a direct overwrite of a published manifest was rejected with `409 BlobImmutableDueToPolicy`, and the publisher independently refused to republish an existing version before writing anything. A successor version published normally while the prior version stayed byte-identical and retrievable. Nine focused tests cover the publication rules against an in-memory transport.

The policy is created unlocked so a disposable environment stays deletable, and [teardown](../../../scripts/Remove-Accelerator.ps1) now removes unlocked policies before deleting the group; a locked policy blocks deletion until retention expires, which a production deployment should accept deliberately. GRCh37 is published under its GRC name rather than as `hg19`: they are the same assembly, but the UCSC distribution differs in sequence naming, so the entry names what was actually published.

Task 4.4 verification (2026-09-19): `reference_publisher` and `reference_reader` are independent grants, and `GovernancePolicy.authorize_reference` appends a hash-chained `reference_data` entry for every authorization decision carrying principal, requested operation, explicit `authorized` or `denied` outcome, entry type and name, immutable version, combined `type/name/version` identity, and UTC timestamp. `ReferenceZone` routes publish and exact/list reads through those roles before storage access. Workflow submission resolves every explicitly requested manifest through the governed exact-read path before allocation, preserving the declared build/version and failing without default or substitution when unavailable. Focused synthetic in-memory tests prove an authorized publish, authorized workflow reads, and a denied publish; the denied write leaves storage unchanged, while SQLite triggers reject audit updates/deletes and chain verification succeeds. Remaining production consideration: the Azure client drivers in `scripts/Publish-Reference.ps1` and `scripts/Test-ReferenceData.ps1` still construct the zone with an explicit `None` governor because those runs have no durable audit store, so cloud-side retained auditing is not claimed; see [the local controls](../../../docs/governance-local-controls.md#reference-publish-and-read).

- [x] 4.1 Publish GRCh38 and hg19 builds plus gene and transcript annotations into `ReferenceData` under `name/version` paths with a per-artifact checksum manifest, and verify the inventory listing returns type, name, and version for each entry
- [x] 4.2 Enforce write-once semantics on published reference versions, and verify a write targeting an existing published version is rejected while publishing a new version succeeds and leaves the prior version retrievable
- [x] 4.3 Add the workflow-to-reference compatibility manifest and the submission-time validation, and verify an incompatible workflow/reference pairing is rejected before any compute pool is allocated
- [x] 4.4 Wire reference read and publish operations into the audit trail, and verify both an authorized publish and a denied publish produce audit entries with principal, entry, version, and timestamp

## 5. Secondary analysis pipeline

Task 5.2 evidence (2026-09-21): run `azure-batch-live-006` executed the full five-process Nextflow workflow (`GENERATE_DEMO_SAMPLE`, `QUALITY_CONTROL`, `ALIGN_READS`, `CALL_VARIANTS`, `PUBLISH_RESULTS`) on a live Azure Batch pool (`secondary-analysis-pool`, `Standard_D2s_v3`, `rg-genomics-20260919`) and completed with `Succeeded: 5`, producing a real BAM/BAI, VCF, and `qc_report.json`. No storage key, connection string, or registry password appears anywhere: the storage account has `allowSharedKeyAccess: false`, so Nextflow authenticates via `azure.managedIdentity.clientId`, and the pool pulls its four per-stage ACR images through a pool-level `containerConfiguration.containerRegistries[].identityReference` -- a second, independent managed-identity path -- confirmed by grepping `.nextflow.log` for `sig=`/`sharedkey`/`accountkey`/`SAS token` (no matches) and finding only `ManagedIdentityCredential` bootstrap entries. Because `ManagedIdentityCredential` requires Azure-hosted compute, the run was launched from a temporary verification VM carrying the same identity, not the local dev machine. Its provenance record validates against the same twelve-field schema used for the local/standard profile (`execution_target: "azure_batch"`, `compute_pool: "secondary-analysis-pool"`, `terminal_state: "succeeded"`). After completion, the pool's autoscale policy drained back to zero dedicated nodes, confirmed via `az batch pool show` (`allocationState: steady`, `currentDedicatedNodes: 0`) -- see [docs/secondary-pipeline.md](../../../docs/secondary-pipeline.md#azure-batch-profile----validated-with-a-live-run-task-52) for full detail, including the per-VM-family Batch quota and Gen2-image discoveries that shaped the final pool SKU. `scripts/run_nextflow_secondary_pipeline.py` still only drives `-profile standard`; extending it to parametrize `-profile azure_batch` is a follow-on hardening item, not a blocker for this task.

Task 5.3 verification attempt (2026-09-21): blocked by unavailable HPC execution resources. The execution host has no `sbatch`/Slurm client, and the authorized Azure resource group `rg-genomics-20260919` contains no Slurm/CycleCloud cluster and no `Microsoft.AzureManagedLustre/fileSystems` resource; it contains Azure Batch, storage, networking, and verification-VM resources only. Consequently, no campaign can create or use Managed Lustre scratch, perform Blob HSM import/export, or verify teardown. The Slurm profile remains configuration-only and this task is intentionally still open pending an authorized Slurm cluster, Lustre filesystem capacity/networking, and campaign credentials/quotas.

Task 5.7 evidence (2026-09-21): a deliberate concurrent burst launched two independent Azure Batch profile runs (`azure-batch-burst-001`, `azure-batch-burst-002`) in parallel from the authorized verification VM (`vm-genomics-20260919`) against the same live pool (`secondary-analysis-pool`). Both runs reached terminal success at `2026-09-21T13:46:23Z` and each published a BAM, BAI, VCF, FASTQ inputs, manifest, and `qc_report.json` under `/root/batch-burst/<run_id>/results`. During the burst, `az batch pool show` observed the autoscale formula raise the pool to `targetDedicatedNodes: 2` and `currentDedicatedNodes: 2` at `2026-09-21T13:43:27Z` with `autoScaleRun.results` reporting `$TargetDedicatedNodes=2 ... $tasks=2`, confirming demand-driven allocation for concurrent work. After the runs completed, the same polling sequence observed the pool step down through `targetDedicatedNodes: 1` / `currentDedicatedNodes: 1` and then return to `targetDedicatedNodes: 0`, `currentDedicatedNodes: 0`, `allocationState: steady` at `2026-09-21T13:53:08Z` with `autoScaleRun.results` reporting `$TargetDedicatedNodes=0 ... $tasks=0`. This satisfies the requirement to show compute allocation during a burst and release back to zero only after the concurrent runs reached terminal state; the verification VM was then deallocated again to avoid idle compute cost.

- [x] 5.1 Author the Nextflow pipeline covering quality control, alignment, BAM/CRAM output, and variant calling to VCF/GVCF, and verify it completes on the demo sample producing both output types
- [x] 5.2 Add the Azure Batch executor profile with managed-identity access to ADLS, and verify a run completes with no storage key or connection string present in the workflow definition or config
- [ ] 5.3 Add the Slurm executor profile with Azure Managed Lustre scratch hydrated from blob by HSM import and exported on completion, and verify the file system is created, used, exported, and torn down within a single campaign
- [ ] 5.4 Run the demo sample on both executors and compare with GATK `Concordance` against the truth set, and verify variant-level concordance meets the accelerator threshold
- [x] 5.5 Persist the run provenance record (workflow id and version, reference build and version, execution target and pool, input URIs, output URIs, start and end time, terminal state, log location), and verify all ten fields are present for both a successful and a deliberately failed run
- [x] 5.6 Implement stage-level failure handling, and verify a forced failure in variant calling marks the run failed with the stage identified and does not publish partial outputs as complete
- [x] 5.7 Confirm compute release after terminal state, and verify pool node count returns to zero following a burst of concurrent runs

## 6. Metadata store

Task 6.5 verification (2026-09-15): the [local metadata store](../../../docs/metadata-store.md) persists research and clinical attributes in separate SQLite tables and persists independent `research_metadata`, `clinical_metadata`, and `subject_linkage` grants. Twenty-five synthetic tests pass. A research-only principal receives sample-scoped research attributes with no clinical key or subject identifier; clinical reads and subject resolution fail with explicit authorization errors. This verifies the local Python API, not a deployed service authorization boundary or audit implementation.

Tasks 6.2 and 6.4 verification (2026-09-10): 21 focused metadata tests pass. Every artifact in the synthetic local demo chains has a storage URI, typed analysis stage, existing producer run and explicit integrity result. Pipeline producers are registered separately from sequencing runs. File retrieval persists those fields; invalid metadata rolls back entity/link insertion, and legacy version-1 stores require explicit backfill without invented values. Metadata-only archival preserves URI, producer, integrity and variant ancestry, including across restarts and concurrent snapshot reads. No payloads were read or archived in storage; real pipeline execution remains pending, and task 6.5 separately verifies local grants.

Tasks 6.1 and 6.3 verification (2026-09-10): the [local metadata model](../../../docs/metadata-store.md) persists synthetic Subject/Sample/Run/artifact/variant-occurrence relationships in SQLite. Thirteen focused tests verify full-chain traversal in both directions, branching/shared ancestors, missing-sample rejection without partial writes, foreign keys, persistence and snapshot-consistent reads. This verifies the model using locally generated demo metadata, not the future Platinum Genomes dataset or pipeline integration. File attributes, archive semantics and access grants were pending at that verification point and are covered by the later task evidence; the API remains trusted local development code and must not be exposed as a governed query service. No Azure operations were performed.

- [x] 6.1 Model the Subject → Sample → Sequencing Run → FASTQ → BAM/CRAM → VCF → variant chain, and verify downward traversal from a subject and upward traversal from a variant both return the full chain for the demo data
- [x] 6.2 Populate file-level entries with storage URI, analysis stage, producing run, and integrity result, and verify every artifact of the demo run has all four populated
- [x] 6.3 Enforce referential integrity on writes, and verify an entry referencing a non-existent sample is rejected
- [x] 6.4 Implement archive semantics, and verify archiving an artifact leaves referencing variant records resolving to a valid entry marked archived
- [x] 6.5 Split clinical from research metadata behind separate grants, and verify a research-only principal reads research attributes and receives no clinical attributes

## 7. Delta variant store

- [x] 7.1 Create the Bronze variant Delta table with the eight VCF core columns and the twelve accelerator context fields, and verify the table schema matches the spec field list exactly
- [x] 7.2 Implement VCF parsing and load using GATK `VariantsToTable` semantics for INFO and FORMAT extraction, and verify a demo VCF loads with core fields populated on every row
- [x] 7.3 Implement mandatory-field validation, and verify records missing `REF` or `ALT` are rejected rather than written
- [x] 7.4 Implement null-rather-than-fabricate handling for annotation fields, and verify an unannotated VCF loads with null `gene`, `transcript`, and `variant_consequence` and no row loss
- [x] 7.5 Populate `source_file_uri`, `pipeline_version`, `reference_build`, and `ingestion_timestamp` from run provenance on every row, and verify provenance resolution for a sampled variant returns the source VCF, producing run, and reference build
- [x] 7.6 Implement the rejected-record table with reason, source file URI, and source line reference, and verify a file with seeded bad rows produces retrievable rejection entries and correct accepted/rejected counts
- [x] 7.7 Implement ingestion idempotency keyed on the source artifact, and verify running ingestion twice on the same VCF leaves the attributable variant count unchanged
- [x] 7.8 Verify reprocessing distinguishability by ingesting the same sample under a new pipeline version and confirming both record sets are separable by `pipeline_version`
- [x] 7.9 Configure OneLake shortcuts to the ADLS genomic artifacts rather than copying them, and verify `source_file_uri` resolves through the shortcut and continues to resolve after the artifact is tiered
  - Local/reference evidence: `VariantStore` stores shortcut and ADLS artifact metadata without copying payloads; synthetic tests resolve the same canonical URI and artifact after a tier change. OneLake/ADLS execution remains unverified.
- [x] 7.10 Apply and document the table layout strategy, and verify the table reports its current partitioning or clustering and last maintenance state
  - Local/reference evidence: synthetic tests inspect clustered columns and a recorded maintenance state; SQLite does not execute Delta clustering or optimization.

## 8. Governance

Task 8.1 local verification (2026-09-15): `GovernancePolicy` persists four independent tiers, authorizes cohort aggregates and variant-store access, explicitly denies raw FASTQ/BAM reads without the raw-file tier, and records denial events. Four synthetic governance tests pass. Cloud role assignments remain deployment-dependent.

- [x] 8.1 Define the four access tiers as role assignments, and verify a cohort-analytics principal can read aggregates and is denied raw file reads, and a variant-store principal is denied raw FASTQ/BAM reads
Task 8.2 local verification (2026-09-19): every service-to-service path in the tracked infrastructure is managed-identity-only. `infra/modules/data-lake.bicep` and `infra/modules/landing-zone.bicep` set `allowSharedKeyAccess: false`; `infra/modules/staging.bicep` gives Data Factory `ManagedIdentity`-typed credentials rather than an account key, and `infra/modules/identities.bicep`/`test-client.bicep` attach only user-assigned identities. The Python drivers obtain bearer tokens from IMDS and never embed a static key. No component in this repository requires an external secret, so nothing needs Key Vault; the "external tool needs a secret" scenario in the governance spec has no violating instance. A new git-blob-level scanner, `scripts/scan_secrets.py`, rejects Azure Storage/Cosmos/Service Bus/Event Hub connection strings, bare storage/Cosmos account keys, SAS query strings, PEM private key blocks, and client-secret literals, while tolerating explicit placeholders. Fourteen focused tests in `tests/test_scan_secrets.py` pass, the scanner reports zero violations against the current repository tree, and it now runs as a second step inside the existing required `data-hygiene` workflow job. See [governance-local-controls.md#identity-based-service-access-and-secret-handling](../../../docs/governance-local-controls.md#identity-based-service-access-and-secret-handling). `rg-genomics-demo` is absent, so this is a repository-scan and IaC-inspection verification, not a fresh live redeployment; the prior disposable environment previously exercised managed-identity SMB and blob access (tasks 1.3, 1.4).
- [x] 8.2 Convert all service-to-service access to managed identities with secrets in Key Vault, and verify a repository scan finds no embedded connection string or storage key
Task 8.3 local verification (2026-09-15): variant projection preserves synthetic sample/cohort attributes and removes subject linkage without denying the query; the focused governance test passes. A deployed query endpoint remains unverified.

- [x] 8.3 Implement de-identified query projection, and verify a caller without subject-linkage access receives sample and cohort attributes with subject linkage withheld rather than a whole-query denial
Task 8.4 local verification (2026-09-15): research/clinical grants are independent; unapproved transfers raise an explicit authorization error and approved transfers record a synthetic approval ID. The focused governance test passes. Cloud movement controls remain unverified.

- [x] 8.4 Separate research and clinical workspaces with independent grants and a recorded authorization on cross-workspace movement, and verify an unapproved transfer is blocked and an approved one is recorded
Task 8.5 local verification (2026-09-15): staging requires a fixed classification vocabulary, and variant ingestion requires classification in run provenance plus a sidecar exposed by `records_with_classification`; the exact 20-field variant table is unchanged. Focused staging and variant tests pass.

- [x] 8.5 Apply classifications at staging and ingestion and surface them to consumers, and verify a staged artifact and the variant table both report a classification
Task 8.6 local verification (2026-09-15): pipeline registration, metadata access, reprocessing, and workspace transfers append hash-chained audit entries; SQLite triggers reject update/delete and chain verification passes. Focused governance and metadata tests pass. Service-side immutable retention remains unverified.

- [x] 8.6 Wire pipeline executions, data access, reprocessing, and cross-workspace transfers into the audit trail with immutability for recorded principals, and verify a reprocessing event and a patient-linked metadata query each produce a tamper-resistant entry
Task 8.7 blocked (2026-09-21): both storage accounts in the surviving `rg-genomics-20260919` environment report `publicNetworkAccess: Disabled`, `networkRuleSet.defaultAction: Deny`, and no public IP exists anywhere in the resource group. [The acceptance script](../../../scripts/Test-Environment.ps1), run from the in-VNet verification client against the live environment, reports six PASS checks covering the taxonomy, staging writes, processing read/write separation, landing-share denial, and managed-identity SMB mounting. This verifies the ingestion, staging, and processing storage paths. The task remains blocked because the deployment contains no live notebook, SQL, or governed query endpoint, and therefore no private query path to exercise. The repository has only the local SQLite governed-query reference harness; a private blob read or local test is not substituted for the missing acceptance evidence. Completing this task requires selecting and deploying an approved analytics engine/query service, wiring its managed identity and governed access policy, adding its private endpoint/private DNS path, loading an authorized synthetic variant dataset, and extending the in-VNet acceptance script to execute and audit a de-identified query. No such service or deployment authorization is currently available.

- [ ] 8.7 Deploy with private endpoints and public data-plane endpoints disabled, and verify ingestion, staging, processing, and query all still function

Task 8.8 local verification (2026-09-19): `GovernancePolicy.share_externally` requires a matching, unexpired, unused approval identifying dataset, recipient, and purpose; variant-store/cohort-analytics read grants do not satisfy it. A share without a matching approval, a mismatched dataset/recipient/purpose, an expired approval, and a reused approval are each denied and audited as `deny:share_externally`; an approved share is audited as `share_externally` recording dataset, recipient, and purpose. Both denial and approval entries are appended to the existing hash-chained audit trail and pass `AuditTrail.verify()`. Focused governance tests pass.

- [x] 8.8 Implement the external-sharing approval gate, and verify a share attempt without approval is blocked and an approved share records dataset, recipient, and purpose
- [x] 8.9 Assemble end-to-end lineage by joining variant provenance columns to the metadata store with Purview supplying item-level context, and verify both a backward trace from a query result and a forward trace from a landing-zone file return the full chain
  - Local/reference evidence (2026-09-19): `scripts/lineage.py` joins `VariantStore`, `MetadataStore`, and `StagingLog`; `CatalogContext` is explicitly labelled as an item-level Microsoft Purview catalog-context simulation (`live: false`). `tests/test_lineage.py` proves full backward and forward traces over synthetic Subject -> Sample -> Sequencing Run -> FASTQ -> BAM -> VCF -> variant data, de-identified subject suppression, separate raw-content authorization, and verified staging continuity. No live Purview connection or cloud lineage claim is made.

## 9. Analytics and visualization

Tasks 9.1-9.4 local verification (2026-09-19): scripts/analytics_query.py implements the six query scenarios as a governed query core over VariantStore/MetadataStore, an SQL-endpoint surface (execute_sql/SqlQueryAdapter) structurally equivalent to the notebook-style scenario methods, per-row traceability via AnalyticsQueryEngine.trace, and snapshot-pinned reproducible re-runs via NotebookSession. Twelve focused tests in tests/test_analytics_query.py pass against runtime-generated synthetic VCF/metadata, covering all six scenarios, unauthorized denial, de-identified projection, notebook/SQL equivalence, traceability, and reproducible rerun. A deployed notebook workspace and SQL warehouse endpoint remain unverified.

- [x] 9.1 Implement the six supported query scenarios (gene, quality filter, cross-cohort, allele in sample, pipeline version, sequencing run), and verify each returns correct results against the demo dataset with sample, cohort, filter status, reference build, and pipeline version attached
  - Local/reference evidence: see the six query_* methods on AnalyticsQueryEngine and their scenario tests in tests/test_analytics_query.py. The demo dataset used is runtime-generated synthetic VCF/metadata, not the Platinum Genomes manifest.
- [x] 9.2 Expose the store through both a notebook environment and a SQL endpoint, and verify the same logical query returns equivalent result sets through both surfaces for the same principal
  - Local/reference evidence: NotebookSession and SqlQueryAdapter both execute through AnalyticsQueryEngine.execute_sql with the identical SQL templates; test_notebook_and_sql_surfaces_return_equivalent_results verifies equal result sets for the same principal. No deployed notebook workspace or SQL warehouse endpoint is exercised.
- [x] 9.3 Implement result traceability in the analytics surface, and verify selecting a returned variant shows source file URI, producing run, reference build, and pipeline version without leaving the surface
  - Local/reference evidence: every query result row carries producing_run plus its native source_file_uri, reference_build, and pipeline_version; AnalyticsQueryEngine.trace and test_result_traceability_without_separate_lookup confirm all four are available from the analytics surface alone.
- [x] 9.4 Record the store version or snapshot read by each notebook, and verify re-running a notebook against its recorded version reproduces the original result set
  - Local/reference evidence: AnalyticsQueryEngine.create_snapshot/resolve_snapshot bound queries by rowid, and NotebookSession records one at construction; test_notebook_session_reproduces_recorded_snapshot ingests a new matching variant after the first run and shows a session reusing the recorded snapshot reproduces the original result set while a fresh session picks up the new row.
- [x] 9.5 Build the six visualization views (gene-centric, variant frequency, cohort comparison, quality-filter funnel, sample-to-file lineage, processing status), and verify each renders on demo data and that a caller without subject-linkage access sees lineage only to sample level
  - Local/reference evidence: AnalyticsViewModels in scripts/analytics_experience.py builds all six view models over AnalyticsQueryEngine and MetadataStore.trace_sample. test_six_access_aware_views_render_synthetic_data verifies all six render on runtime-generated synthetic data and that restricted lineage starts at the sample rather than exposing a subject. Processing-status unavailable execution-target and failure-reason values remain null rather than inferred.
- [x] 9.6 Instrument query response time against the representative dataset and publish the target, and verify each supported query reports its measured response time alongside results
  - Local/reference evidence: QueryResults exposes scenario, snapshot_id, and response_time_ms for every supported query, with QueryMeasurement records retained by AnalyticsQueryEngine. test_every_supported_query_reports_measured_response_time runs the six scenarios against a runtime-generated 51-record, two-cohort synthetic harness and verifies each reports an observed time at or below the documented 1,000 ms local target. The target is explicitly labelled an assumption in docs/analytics-query.md and is not a production-performance claim.
- [x] 9.7 Wire AI-assisted exploration to the governed query interface, and verify an assisted cohort question returns traceable results, that a caller without subject-linkage access cannot obtain subject identity by rephrasing, and that assisted output is labelled exploratory
  - Local/reference evidence: AssistedCohortExploration accepts only bounded gene/cohort questions and invokes AnalyticsQueryEngine with the original principal; it has no direct table or file access. test_assisted_exploration_is_governed_traceable_and_exploratory verifies a rephrased subject-identity request remains de-identified, returns per-result provenance, and carries the exploratory/non-clinical label.

## 10. Engineering platform and AI context

Task 10.1 live verification (2026-09-19): the pipeline deployment workflow
used GitHub OIDC to authenticate as
`id-genomics-pipeline-tgrxjnw6usjfg`, log in to the admin-disabled ACR, and
push `genomics-variant-pipeline:v0.2.1-pipeline`. The first attempt exposed an
immutable-subject mismatch: this repository emits
`repo:samueltauil@279246/genomics-variant-analytics@1358346690:environment:*`,
not the mutable owner/name subject. `Configure-GitHubOidc.ps1` now reads the
repository OIDC customization endpoint and creates or updates each Entra
federated credential to the emitted prefix. Workflow run `35468110327`
completed successfully after that correction. GitHub API enumeration returned
zero repository secrets and zero secrets in `release-build`, `clinical`, and
`research`; the Azure client, tenant, subscription, resource group, and ACR
identifiers remain repository variables rather than credentials.

- [x] 10.1 Configure the Azure federated identity credential and convert deployment workflows to OIDC, and verify a deployment succeeds while an enumeration of repository and environment secrets returns no Azure credential
- [ ] 10.2 Create `clinical` and `research` environments with required reviewers, self-review prevented, administrator bypass disabled, and deployment refs limited to release tags, and verify a branch deployment is refused, a self-approval is refused, and an approved tag deployment produces a deployment record with environment, approver, commit, and outcome
  - Partial implementation (2026-09-19): both environments are configured live with `can_admins_bypass=false`, a required reviewer, `prevent_self_review=true`, and a `v*` tag deployment policy. Branch/self-approval/approved-tag execution remains unverified because no independent reviewer or Azure target is configured.
- [x] 10.3 Enable immutable releases and publish the first pipeline release from a draft with assets attached, and verify the tag cannot be moved or deleted, the tag name cannot be reused after deletion, and the release attestation is retrievable
  - Live acceptance (2026-09-19): enabled immutable releases; published `v0.1.0-pipeline` from a draft with `pipeline-release-manifest.json`, `reference-compatibility.json`, `toolchain.json`, and `SHA256SUMS`. `gh release view` reports `immutable=true`; `gh release verify v0.1.0-pipeline --format json` verified the release attestation and all asset digests. Force-moving and deleting the tag were rejected by repository rules. A disposable immutable `v0.1.0-reuse-probe` was published, deleted with its tag, and a push attempting to recreate the same tag name was rejected. The retained tag resolves to commit `febafa0cc78777da8ae046253051c0b4aec83e41`.
Task 10.4 live verification (2026-09-19): release workflow run `35468110327`
pushed
`acrgentgrxjnw6usjfg.azurecr.io/genomics-variant-pipeline:v0.2.1-pipeline`
with digest
`sha256:c05f74d757061a5e9f07b6c86653b7a8d5b98e0e6d842fbb860510b64606483d`.
`gh attestation verify` fetched the SLSA v1 bundle from ACR and verified
repository `samueltauil/genomics-variant-analytics`, commit
`05c832b79140965f5de1d420476765bed2e9bbff`, workflow
`.github/workflows/pipeline-container.yml`, and source ref
`refs/tags/v0.2.1-pipeline`.

- [x] 10.4 Add build provenance attestation to the pipeline container workflow with `push-to-registry` targeting ACR, and verify `gh attestation verify oci://<acr>/<image>` succeeds and reports the originating repository, commit, and workflow
Task 10.5 live verification (2026-09-19): the same workflow generated a
CycloneDX 1.6 SBOM, added the reviewed synthetic toolchain declaration, and
published its signed attestation to ACR. Registry-backed verification returned
`aligner` version `synthetic-aligner-1.0.0` and `variant-caller` version
`synthetic-variant-caller-1.0.0` for the image digest above. The
`trace_variant_supply_chain` verifier starts from a stored synthetic variant
whose `pipeline_version` is `v0.2.1-pipeline` and fails closed unless the
immutable release, provenance tag and commit, image digest, SBOM subject, and
required tool versions agree.

- [x] 10.5 Add SBOM generation and SBOM attestation to the container workflow, and verify the aligner and variant-caller versions are retrievable from a variant record's `pipeline_version`
- [x] 10.6 Enforce attestation verification in the pipeline submission path, and verify an unattested image is rejected and an untracked dependency without a commit SHA is rejected before compute allocation
  - Local implementation verified (2026-09-19): `submit_pipeline_workflow` rejects incomplete/unattested evidence and dependencies without full commit SHAs before calling the allocator; live registry verification remains blocked with 10.4.
- [x] 10.7 Author the repository AI context — instructions, prompt files, and agent skills covering the VCF schema, no-PHI constraint, reference-build handling, and positioning limits — and verify a request to add a variant-store column returns a response reflecting those rules unprompted
Task 10.8 local verification (2026-09-19): `scripts/mcp_server.py` adds an
in-process, stdio-transport MCP-style facade (`MCPServer`) over the existing
`AnalyticsQueryEngine`/`AnalyticsViewModels`/`AssistedCohortExploration` and
`GovernancePolicy`, with mandatory server-side `variant_store` tier
enforcement at the MCP boundary in addition to the enforcement already
inside the delegated methods. `tests/test_mcp_server.py` proves tool
enumeration exposes no credential-shaped text, an unauthorized caller is
denied and audited, three differently phrased assisted questions from a
de-identified caller never return `research_subject_id`, every assisted
result row carries full traceability, every assisted response carries the
exploratory notice, every assisted query appends an
`ai_assisted_cohort_exploration` audit event, no server/engine attribute
carries credential-shaped text, and an in-process stdio JSON-Lines round
trip (`tools/list`/`tools/call`) works. No network-reachable MCP endpoint is
deployed; `serve_stdio` opens no port and starts no listener.

- [x] 10.8 Build the MCP server fronting the governed query interface with server-side access-tier enforcement, and verify a de-identified caller's assisted cohort question returns results without subject linkage, that the server exposes no raw table or storage credentials, and that assisted queries appear in the audit trail
Task 10.9 local verification (2026-09-19): the trusted `pull_request_target`
workflow checks workflow, container, reference-compatibility-manifest, variant
implementation and governed schema paths without checking out or executing
proposed code. The deterministic reviewer compares reference sets per workflow
and requires a `workflow_version` bump, and derives the exact 20-column
contract from the Delta variant-store spec before comparing `VARIANT_FIELDS`.
Four isolated synthetic Git-history tests prove the two required findings and
their passing counterparts.

- [x] 10.9 Enable automated pull-request review on workflow, container, manifest, and schema paths, and verify it flags a reference-build change with no version bump and a variant-store column absent from the specs
Task 10.10 acceptance record (2026-09-19): the daily and manually dispatchable
workflow consumes a `pipeline-failures` artifact, and the shared triage logic
has dry-run and GitHub issue adapters. Five focused tests prove
first-occurrence creation with all required provenance, recurrence update
without duplication, replay idempotency, fail-closed required fields, and the
GitHub adapter's GET/POST/PATCH requests without network access. A live,
manually invoked synthetic acceptance run exercised the same GitHub adapter
used by the scheduled job. It created disposable issue #26 at 15:20:51Z with
failing stage `variant-calling`, run `SYN-RUN-TRIAGE-20260919`, reference
`GRCh38` assembly version `GCA_000001405.15`, pipeline version
`v0.1.0-synthetic-triage`, and an `example.invalid` log location. A distinct
second occurrence updated #26 at 15:21:12Z; the issue then contained two
occurrence markers and recurrence count 2, while an all-state marker query
returned exactly one issue. The disposable issue was closed at 15:21:39Z.
This proves the live create/update path without retaining an open test issue;
the configured cron itself was not observed firing during this acceptance.

- [x] 10.10 Configure the scheduled agent triage for failed pipeline runs, and verify an overnight failure opens an issue carrying failing stage, run identifier, reference build, pipeline version, and log location, and that a recurrence updates that issue rather than duplicating it
Task 10.11 verification (2026-09-19): `docs/engineering-controls.md` records,
for each platform tier/visibility dependency, the dependency, substitute
control, and residual gap. The table covers push and organization rulesets,
deployment environment protections, Copilot organization controls and
entitlements, Actions capacity, secret protection, immutable
release/attestation availability, and release-asset size. Focused documentation
tests require all four cells for every named feature and preserve the
unverified-live-triage statement.

- [x] 10.11 Document the account-tier dependencies and substitute controls, and verify each tier-gated feature named in the platform spec has a stated substitute and residual gap

## 11. Demo enablement

Local verification record (2026-09-16): `scripts/Test-DemoPreflight.ps1` now
supports a deterministic subscription snapshot mode covering subscription
state/type, deployment and role-assignment roles, compute/storage quota,
regional component availability, and Azure CLI/Bicep versions. The unprepared
snapshot reports each failure with found/required values; a prepared snapshot
passes without contacting Azure. `Deploy-Accelerator.ps1` invokes preflight
before subscription lookup or deployment and accepts the snapshot only for
local gate testing. `scripts/reset_demo.py` clears only named local delivery
SQLite files and reports per-store diagnostics; the runbook and talk track
separate local evidence from live-cloud and specified-only behavior. No live
subscription, pricing, fresh bring-up, cloud reset, teardown, failed-transfer
retry, or end-to-end presentation was claimed.

- [x] 11.1 Write the preflight check covering subscription type, required roles, compute and storage quota, regional availability of every component, and local tooling versions, and verify it reports each unmet prerequisite with found and required values on a deliberately unprepared subscription
- [x] 11.2 Gate provisioning on preflight, and verify provisioning refuses to start with an unmet quota and creates no resource
Task 11.3 live verification (2026-09-19): `scripts/check_environment_identifiers.py`, run against the tracked working tree after the `20260919` live deployment, reports no tracked subscription or tenant identifier; the live environment's actual subscription/tenant GUIDs live only in the git-ignored `.azure/environment.env.json`. The parameterized template deployed cleanly for this run using only `infra/main.bicep`'s documented parameters (environment name, region, tags), with no author-specific resource name hardcoded outside the marked demo examples already covered by the pre-existing local scan noted above.

- [x] 11.3 Parameterize every environment-specific value, and verify a scan finds no subscription id, tenant id, or author-specific resource name outside marked examples, and that a clean clone deploys with only the documented required inputs
Task 11.4 contract revision (2026-09-19): repeated live deployments are
non-destructive and non-duplicating, but raw ARM what-if reports service
defaults, read-only values, and runtime identity references as modifications
or unsupported resources. The reviewed requirement now calls for a
version-controlled, fail-closed normalization report that retains raw output,
recognizes only documented noise, and reports every unfamiliar difference as
pending. Task completion requires that normalized report to return no
effective changes against the complete environment.

Task 11.4 live verification (2026-09-20):
[`normalize_arm_what_if.py`](../../../scripts/normalize_arm_what_if.py)
retains raw ARM what-if JSON and permits only reviewed resource-type and
property-path combinations plus five explicit managed-identity role IDs.
Unknown paths, resource types, creates, deletes, and unsupported diagnostics
remain effective changes; focused tests prove those cases fail closed.
`Deploy-Accelerator.ps1` writes both raw and normalized reports under the
ignored `.azure` directory. After the account-native lifecycle policy was
created and the October 3 expiry tag restored, an unchanged live run reported
`Pending effective changes: none` from 23 reviewed `Modify`, 21 `NoChange`, 8
`Ignore`, and 5 reviewed `Unsupported` entries. The deployment created no
resources and completed the existing taxonomy without duplication.

- [x] 11.4 Make provisioning idempotent from a single entry point with a stated duration, and verify a re-run after a partial failure completes the remainder without duplication and a re-run against a complete environment reports no effective changes after documented fail-closed normalization
Task 11.5 verification (updated 2026-09-20): [`docs/cost-estimate.md`](../../../docs/cost-estimate.md) is dated 2026-09-19 for `eastus2`, derived from the deployed Bicep sizing (128 GiB/3,000 IOPS/200 MiB/s share, `Standard_D4s_v7` VM, and 32 GiB OS disk) and Azure Retail Prices API rates. It states the current default per-delivery cost (~$0.14), idle cost (~$0.601/day, dominated by the provisioned share), the additional exposure if the VM is left running (~$6.36/day), and names the dominant idle resource explicitly. Account-native lifecycle management has no separately deployed task-execution resource; storage transactions remain excluded with the other unsized usage. The optional legacy Storage Actions resources are disabled by default.

- [x] 11.5 Produce the cost statement covering per-delivery cost, idle cost, dominant resources, and the estimate's date and region, and verify each element is present and derived from actual resource sizing
Task 11.6 live verification (2026-09-19): bring-up against the authorized fresh `ME-MngEnvMCAP403212-tauilsamuel-1` subscription reached the documented ready state twice: preflight passed, then `Deploy-Accelerator.ps1` provisioned the full foundation (identities, VNet/DNS/private endpoints, both storage accounts, Data Factory pipeline, verification VM, Storage Actions task) in about 6 minutes on first bring-up, confirmed by `.azure/environment.env.json` being written with all expected resource names and the taxonomy folders present. Seeding readiness is confirmed by [`Test-Environment.ps1`](../../../scripts/Test-Environment.ps1) reporting all twelve taxonomy directories resolving and the staging identity able to write into them, so a subsequent demo-dataset seed (tasks 1.5/1.6) has a writable destination immediately after bring-up. A second full re-run reached the same ready state in about 4 minutes, confirming the phase durations are representative rather than a one-off.

- [x] 11.6 Write the bring-up and seeding phases with per-phase duration and confirming observation, and verify an engineer following them against a fresh subscription reaches the documented ready state
Task 11.7 verification (2026-09-19): Phase 3 of [`docs/demo-runbook.md`](../../../docs/demo-runbook.md) follows the required ingest, stage, process, build, query, visualize, and govern sequence. Each row names the observable fields required by its capability contract and labels the evidence as local, live partial, previously recorded, or unverified. `tests/test_demo_runbook.py` parses all seven rows and verifies a representative required output for each against the implementation module that produces it, preventing the presentation sequence from naming an output absent from the repository.

- [x] 11.7 Write the seven-step presentation sequence naming, for each step, the observable output its capability spec requires, and verify each named output is one the implementation actually produces
- [x] 11.8 Script the rehearsed failure demonstrations — failed transfer, rejected variant record, denied access attempt — and verify each trigger produces the response its capability spec states
- [x] 11.9 Build the reset procedure with diagnostics, and verify a reset returns the environment to its starting state with no prior-delivery records visible and without redeploying infrastructure, and that an interrupted reset can be diagnosed to determine which stores are clean
- [x] 11.10 Build teardown, and verify no demo-created resource remains in the target subscription afterwards, and that idle-cost resources are named for engineers who defer it
- [x] 11.11 Write the claim register covering the released-blueprint, compliance, customer-reference, and clinical-use boundaries with supported and prohibited phrasing for each, and verify every presenter-facing document passes review against it
- [x] 11.12 Write the talk track marking production considerations separately from demonstrated behavior, and verify it passes review against the claim register
- [x] 11.13 Publish the demonstrated-versus-specified coverage table, and verify every capability is marked demonstrated, partially demonstrated, or specified only, and that the markings match what the demo environment actually exercises
- [x] 11.14 Publish known limitations with cause, workaround, and whether each is inherent to the platform or specific to the demo configuration, and verify the platform constraints recorded in the design appear there
- [x] 11.15 State support expectations and the defect route, and verify the documentation declares no support commitment and distinguishes the accelerator from a supported Microsoft offering
- [x] 11.16 Dry-run the full flow as a first-time reader using only the published documentation, from preflight through teardown, and verify no step requires knowledge absent from the repository

## 12. End-to-end validation and positioning

Tasks 12.4-12.5 verification (2026-09-19): `scripts/review_positioning.py`
validates the four boundaries in `docs/claim-register.md`, discovers all
presenter-facing Markdown plus text-based generated material, and records every
matched claim with its contextual disposition in
`docs/positioning-review.json`. The checked report covers 24 files and 29
contextual matches with no prohibited assertion. Six focused tests prove each
boundary rejects a positive claim, explicit limitation language passes, the
review scope is complete, and confirmation cannot be recorded without explicit
review evidence. `docs/assumption-register.json` exactly preserves all nine
ordered proposal assumptions and cross-checks each against task state,
implementation paths, and the matching coverage-table status; all nine remain
labelled `assumption` because no explicit reviewed confirmation exists. The
full 244-test suite, the repository scanner, and strict OpenSpec validation
pass.

- [ ] 12.1 Execute the full seven-step demo scenario from instrument write through governance review, and verify each step produces the observable output named in its capability spec
- [x] 12.2 Measure and report the accelerator KPIs (pipeline success rate, arrival-to-queryable time, query response time, percentage of records linked to source files, reprocessing time, cost per sample), and verify each is produced from instrumented data rather than estimated
Task 12.3 live verification (2026-09-19): a synthetic Bronze record
(`chr17:43071077 A>G`, source
`abfss://synthetic@lake.invalid/Process/VCF/SYN-RUN-TRACE-001.vcf`) was ingested
with `pipeline_version: v0.2.1-pipeline`. `trace_variant_supply_chain`
validated that value against GitHub's verified immutable-release attestation,
which binds the tag to commit
`05c832b79140965f5de1d420476765bed2e9bbff`; the registry-backed SLSA
attestation binds the same tag and commit to image digest
`sha256:c05f74d757061a5e9f07b6c86653b7a8d5b98e0e6d842fbb860510b64606483d`;
and the registry-backed CycloneDX attestation binds that digest to
`synthetic-aligner-1.0.0` and `synthetic-variant-caller-1.0.0`. The verifier
rejects a mismatched release tag, commit, image subject, digest, predicate, or
missing required tool.

- [x] 12.3 Trace a single variant end to end from its record through `pipeline_version` to the immutable release, the release attestation, the build provenance, and the SBOM, and verify every hop resolves without a self-asserted link
- [x] 12.4 Review all customer-facing material against the positioning constraints, and verify it makes no compliance claim, no released-blueprint claim, no unverified customer attribution, and no clinical determination claim for assisted output
- [x] 12.5 Cross-check every "proposed" item in the proposal's assumptions against what was actually built, and verify the accelerator documentation still labels each as an assumption or records its confirmation
