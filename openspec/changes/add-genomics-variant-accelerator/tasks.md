## 1. Repository guardrails and foundation

Current policy update (2026-09-10): the user authorized a solo-maintainer policy. Required approval counts are now zero in both branch protection and the default-branch ruleset; strict required checks, the PR rule, administrator enforcement, resolved threads, and force-push/deletion restrictions remain. The independent-review/direct-push evidence below describes the earlier configuration, not the current guarantee: a green, already-open PR head can again permit an administrator fast-forward. No further control expansion is planned; implementation is the priority.

Implementation note (2026-09-10): task 1.1 is complete. PR #1 installed the trusted data-hygiene workflow; `main` requires strict GitHub Actions checks and independent PR approval, including for administrators. Six isolated synthetic PRs failed the trusted policy and their merge API attempts were refused; an administrator direct push of a passing but unapproved PR head was also refused. The initial zero-approval fast-forward gap, corrective settings, run URLs, and pending test-PR closure submissions are recorded in [CONTRIBUTING.md](../../../CONTRIBUTING.md#live-acceptance-record-2026-09-10). All 12 local tests, actionlint 1.7.12, and strict OpenSpec validation pass. Task 1.2 is also complete: secret scanning and push protection were confirmed enabled, a harmless control push succeeded, and a never-issued PAT-shaped probe received an explicit GitHub push-protection rejection. The remote stayed unchanged and the disposable branch was removed; see the [secret-protection evidence](../../../CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10). Cloud work remains unverified.

Local-first phase (2026-09-10): Azure access, provisioning, uploads and live benchmarks are paused at the user's request. The [candidate infrastructure inventory and local validator](../../../infra/README.md) prepare asset dependencies and task traceability only; resource-list and plan approval are pending before IaC generation. No cloud task is complete on the strength of this local validation, and all existing acceptance criteria remain unchanged.

Azure testing phase (2026-09-10): the user authorized provisioning in a disposable MCAPS subscription, to be removed afterwards. [Parameterized Bicep](../../../infra/main.bicep) now deploys workload identities, an SSD provisioned v2 SMB share, an HNS-enabled ADLS account, a private VNet with private endpoints and private DNS, and an in-network verification client. Two governance constraints shaped the result and are not workarounds to remove: subscription policy forces `publicNetworkAccess: Disabled` and `allowSharedKeyAccess: False` on storage accounts, and public IP addresses cannot be created. Every data-plane operation therefore runs over private endpoints, and both SMB and REST authenticate with managed identities rather than keys.

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

Task 2.3 verification (2026-09-17): the blocking contract is resolved by requiring the sending run to declare an expected size per file, so failure is never inferred from stability alone. [The landing scanner](../../../docs/landing-inventory.md#failure-detection-and-retry) reads a root-relative `{run_id}` transfer manifest together with a stall deadline, then classifies a file larger than declared as `failed`/`size-exceeds-declared`, a short file unchanged past the deadline as `failed`/`incomplete-transfer`, and a declared file that never arrived as `failed`/`missing-transfer` carrying the run and sample its declared path resolves to. A short file is never advanced to `complete`, which closes the truncation hole the stability rule left open. Retry needs no separate command: a re-send changes size or modification time, which resets `unchanged_since`, clears `failure_reason` and revises the existing record in place to `arriving`, then to `complete` once it reaches the declared size and stabilizes. The original `arrival_timestamp` is retained, no second row is created, and sibling files of the same run are evaluated independently. `available_for_staging` returns only `complete` files, so failed and arriving files are withheld. The contract fails closed: an absent, unparsable, oversized, self-declaring, cross-run or duplicate-declaring manifest is rejected, reported in `manifest_errors`, and holds that run's files at `arriving` with `metadata_error: manifest-unavailable`. A scan configured without a manifest reports `failure_detection: not-evaluated` and claims no failure at all.

Eleven focused failure tests inside the 32-test landing suite cover truncation, oversize, non-arrival, retry, sibling independence, staging exclusion, manifest validation, inventory binding and the CLI; the full 160-test suite, the data-hygiene scan and strict OpenSpec validation pass. The Azure Files source shares the same evaluation path and can fetch a manifest over REST, but this is local synthetic evidence: no instrument, SMB share or interrupted cloud transfer was exercised. The guarantee is bounded by the declaration — a sender that declares the truncated size it actually shipped is believed — and the stall deadline is deployment-specific rather than a property of the accelerator.

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
- [ ] 3.5 Configure the Storage Actions task for blob-side lifecycle (tiering and index tags) on staged artifacts, and verify an artifact past the age threshold transitions tier while its URI and lineage link still resolve

## 4. Reference data

Task 4.3 evidence (2026-09-15): the compatibility manifest and workflow submission path require an explicit build and immutable version, resolve write-once published manifests, pin per-manifest SHA-256 digests, and reject missing or incompatible references before the allocator callback. Twenty-one synthetic tests pass; no genomic payloads or reference downloads are used.

Tasks 4.1 and 4.2 verification (2026-09-11): the [reference publisher](../../../scripts/publish_reference.py) streams artifacts from pinned sources into a separate `reference` container laid out as `type/name/version`, recording a SHA-256 and byte count per artifact in a manifest that commits the version. Five real entries were published from versioned Ensembl paths totalling about 2 GB: GRCh38 and GRCh37 primary assemblies, GRCh38 and GRCh37 gene annotations, and GRCh38 transcript sequences. Versioned source paths are used deliberately, because a `current` alias moves and would make a published version irreproducible. The inventory returns type, name and version for all five. Write-once is enforced by a container-level WORM policy, which hierarchical-namespace accounts must use since version-level policies need blob versioning: a direct overwrite of a published manifest was rejected with `409 BlobImmutableDueToPolicy`, and the publisher independently refused to republish an existing version before writing anything. A successor version published normally while the prior version stayed byte-identical and retrievable. Nine focused tests cover the publication rules against an in-memory transport.

The policy is created unlocked so a disposable environment stays deletable, and [teardown](../../../scripts/Remove-Accelerator.ps1) now removes unlocked policies before deleting the group; a locked policy blocks deletion until retention expires, which a production deployment should accept deliberately. GRCh37 is published under its GRC name rather than as `hg19`: they are the same assembly, but the UCSC distribution differs in sequence naming, so the entry names what was actually published.

- [x] 4.1 Publish GRCh38 and hg19 builds plus gene and transcript annotations into `ReferenceData` under `name/version` paths with a per-artifact checksum manifest, and verify the inventory listing returns type, name, and version for each entry
- [x] 4.2 Enforce write-once semantics on published reference versions, and verify a write targeting an existing published version is rejected while publishing a new version succeeds and leaves the prior version retrievable
- [x] 4.3 Add the workflow-to-reference compatibility manifest and the submission-time validation, and verify an incompatible workflow/reference pairing is rejected before any compute pool is allocated
- [ ] 4.4 Wire reference read and publish operations into the audit trail, and verify both an authorized publish and a denied publish produce audit entries with principal, entry, version, and timestamp

## 5. Secondary analysis pipeline

- [ ] 5.1 Author the Nextflow pipeline covering quality control, alignment, BAM/CRAM output, and variant calling to VCF/GVCF, and verify it completes on the demo sample producing both output types
- [ ] 5.2 Add the Azure Batch executor profile with managed-identity access to ADLS, and verify a run completes with no storage key or connection string present in the workflow definition or config
- [ ] 5.3 Add the Slurm executor profile with Azure Managed Lustre scratch hydrated from blob by HSM import and exported on completion, and verify the file system is created, used, exported, and torn down within a single campaign
- [ ] 5.4 Run the demo sample on both executors and compare with GATK `Concordance` against the truth set, and verify variant-level concordance meets the accelerator threshold
- [ ] 5.5 Persist the run provenance record (workflow id and version, reference build and version, execution target and pool, input URIs, output URIs, start and end time, terminal state, log location), and verify all ten fields are present for both a successful and a deliberately failed run
- [ ] 5.6 Implement stage-level failure handling, and verify a forced failure in variant calling marks the run failed with the stage identified and does not publish partial outputs as complete
- [ ] 5.7 Confirm compute release after terminal state, and verify pool node count returns to zero following a burst of concurrent runs

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
- [ ] 8.2 Convert all service-to-service access to managed identities with secrets in Key Vault, and verify a repository scan finds no embedded connection string or storage key
Task 8.3 local verification (2026-09-15): variant projection preserves synthetic sample/cohort attributes and removes subject linkage without denying the query; the focused governance test passes. A deployed query endpoint remains unverified.

- [x] 8.3 Implement de-identified query projection, and verify a caller without subject-linkage access receives sample and cohort attributes with subject linkage withheld rather than a whole-query denial
Task 8.4 local verification (2026-09-15): research/clinical grants are independent; unapproved transfers raise an explicit authorization error and approved transfers record a synthetic approval ID. The focused governance test passes. Cloud movement controls remain unverified.

- [x] 8.4 Separate research and clinical workspaces with independent grants and a recorded authorization on cross-workspace movement, and verify an unapproved transfer is blocked and an approved one is recorded
Task 8.5 local verification (2026-09-15): staging requires a fixed classification vocabulary, and variant ingestion requires classification in run provenance plus a sidecar exposed by `records_with_classification`; the exact 20-field variant table is unchanged. Focused staging and variant tests pass.

- [x] 8.5 Apply classifications at staging and ingestion and surface them to consumers, and verify a staged artifact and the variant table both report a classification
Task 8.6 local verification (2026-09-15): pipeline registration, metadata access, reprocessing, and workspace transfers append hash-chained audit entries; SQLite triggers reject update/delete and chain verification passes. Focused governance and metadata tests pass. Service-side immutable retention remains unverified.

- [x] 8.6 Wire pipeline executions, data access, reprocessing, and cross-workspace transfers into the audit trail with immutability for recorded principals, and verify a reprocessing event and a patient-linked metadata query each produce a tamper-resistant entry
- [ ] 8.7 Deploy with private endpoints and public data-plane endpoints disabled, and verify ingestion, staging, processing, and query all still function
- [ ] 8.8 Implement the external-sharing approval gate, and verify a share attempt without approval is blocked and an approved share records dataset, recipient, and purpose
- [ ] 8.9 Assemble end-to-end lineage by joining variant provenance columns to the metadata store with Purview supplying item-level context, and verify both a backward trace from a query result and a forward trace from a landing-zone file return the full chain

## 9. Analytics and visualization

- [ ] 9.1 Implement the six supported query scenarios (gene, quality filter, cross-cohort, allele in sample, pipeline version, sequencing run), and verify each returns correct results against the demo dataset with sample, cohort, filter status, reference build, and pipeline version attached
- [ ] 9.2 Expose the store through both a notebook environment and a SQL endpoint, and verify the same logical query returns equivalent result sets through both surfaces for the same principal
- [ ] 9.3 Implement result traceability in the analytics surface, and verify selecting a returned variant shows source file URI, producing run, reference build, and pipeline version without leaving the surface
- [ ] 9.4 Record the store version or snapshot read by each notebook, and verify re-running a notebook against its recorded version reproduces the original result set
- [ ] 9.5 Build the six visualization views (gene-centric, variant frequency, cohort comparison, quality-filter funnel, sample-to-file lineage, processing status), and verify each renders on demo data and that a caller without subject-linkage access sees lineage only to sample level
- [ ] 9.6 Instrument query response time against the representative dataset and publish the target, and verify each supported query reports its measured response time alongside results
- [ ] 9.7 Wire AI-assisted exploration to the governed query interface, and verify an assisted cohort question returns traceable results, that a caller without subject-linkage access cannot obtain subject identity by rephrasing, and that assisted output is labelled exploratory

## 10. Engineering platform and AI context

- [ ] 10.1 Configure the Azure federated identity credential and convert deployment workflows to OIDC, and verify a deployment succeeds while an enumeration of repository and environment secrets returns no Azure credential
- [ ] 10.2 Create `clinical` and `research` environments with required reviewers, self-review prevented, administrator bypass disabled, and deployment refs limited to release tags, and verify a branch deployment is refused, a self-approval is refused, and an approved tag deployment produces a deployment record with environment, approver, commit, and outcome
- [ ] 10.3 Enable immutable releases and publish the first pipeline release from a draft with assets attached, and verify the tag cannot be moved or deleted, the tag name cannot be reused after deletion, and the release attestation is retrievable
- [ ] 10.4 Add build provenance attestation to the pipeline container workflow with `push-to-registry` targeting ACR, and verify `gh attestation verify oci://<acr>/<image>` succeeds and reports the originating repository, commit, and workflow
- [ ] 10.5 Add SBOM generation and SBOM attestation to the container workflow, and verify the aligner and variant-caller versions are retrievable from a variant record's `pipeline_version`
- [ ] 10.6 Enforce attestation verification in the pipeline submission path, and verify an unattested image is rejected and an untracked dependency without a commit SHA is rejected before compute allocation
- [x] 10.7 Author the repository AI context — instructions, prompt files, and agent skills covering the VCF schema, no-PHI constraint, reference-build handling, and positioning limits — and verify a request to add a variant-store column returns a response reflecting those rules unprompted
- [ ] 10.8 Build the MCP server fronting the governed query interface with server-side access-tier enforcement, and verify a de-identified caller's assisted cohort question returns results without subject linkage, that the server exposes no raw table or storage credentials, and that assisted queries appear in the audit trail
- [ ] 10.9 Enable automated pull-request review on workflow, container, manifest, and schema paths, and verify it flags a reference-build change with no version bump and a variant-store column absent from the specs
- [ ] 10.10 Configure the scheduled agent triage for failed pipeline runs, and verify an overnight failure opens an issue carrying failing stage, run identifier, reference build, pipeline version, and log location, and that a recurrence updates that issue rather than duplicating it
- [ ] 10.11 Document the account-tier dependencies and substitute controls, and verify each tier-gated feature named in the platform spec has a stated substitute and residual gap

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
- [ ] 11.3 Parameterize every environment-specific value, and verify a scan finds no subscription id, tenant id, or author-specific resource name outside marked examples, and that a clean clone deploys with only the documented required inputs
- [ ] 11.4 Make provisioning idempotent from a single entry point with a stated duration, and verify a re-run after a partial failure completes the remainder without duplication and a re-run against a complete environment reports no changes
- [ ] 11.5 Produce the cost statement covering per-delivery cost, idle cost, dominant resources, and the estimate's date and region, and verify each element is present and derived from actual resource sizing
- [ ] 11.6 Write the bring-up and seeding phases with per-phase duration and confirming observation, and verify an engineer following them against a fresh subscription reaches the documented ready state
- [ ] 11.7 Write the seven-step presentation sequence naming, for each step, the observable output its capability spec requires, and verify each named output is one the implementation actually produces
- [ ] 11.8 Script the rehearsed failure demonstrations — failed transfer, rejected variant record, denied access attempt — and verify each trigger produces the response its capability spec states
- [ ] 11.9 Build the reset procedure with diagnostics, and verify a reset returns the environment to its starting state with no prior-delivery records visible and without redeploying infrastructure, and that an interrupted reset can be diagnosed to determine which stores are clean
- [ ] 11.10 Build teardown, and verify no demo-created resource remains in the target subscription afterwards, and that idle-cost resources are named for engineers who defer it
- [x] 11.11 Write the claim register covering the released-blueprint, compliance, customer-reference, and clinical-use boundaries with supported and prohibited phrasing for each, and verify every presenter-facing document passes review against it
- [x] 11.12 Write the talk track marking production considerations separately from demonstrated behavior, and verify it passes review against the claim register
- [x] 11.13 Publish the demonstrated-versus-specified coverage table, and verify every capability is marked demonstrated, partially demonstrated, or specified only, and that the markings match what the demo environment actually exercises
- [x] 11.14 Publish known limitations with cause, workaround, and whether each is inherent to the platform or specific to the demo configuration, and verify the platform constraints recorded in the design appear there
- [x] 11.15 State support expectations and the defect route, and verify the documentation declares no support commitment and distinguishes the accelerator from a supported Microsoft offering
- [ ] 11.16 Dry-run the full flow as a first-time reader using only the published documentation, from preflight through teardown, and verify no step requires knowledge absent from the repository

## 12. End-to-end validation and positioning

- [ ] 12.1 Execute the full seven-step demo scenario from instrument write through governance review, and verify each step produces the observable output named in its capability spec
- [ ] 12.2 Measure and report the accelerator KPIs (pipeline success rate, arrival-to-queryable time, query response time, percentage of records linked to source files, reprocessing time, cost per sample), and verify each is produced from instrumented data rather than estimated
- [ ] 12.3 Trace a single variant end to end from its record through `pipeline_version` to the immutable release, the release attestation, the build provenance, and the SBOM, and verify every hop resolves without a self-asserted link
- [ ] 12.4 Review all customer-facing material against the positioning constraints, and verify it makes no compliance claim, no released-blueprint claim, no unverified customer attribution, and no clinical determination claim for assisted output
- [ ] 12.5 Cross-check every "proposed" item in the proposal's assumptions against what was actually built, and verify the accelerator documentation still labels each as an assumption or records its confirmation
