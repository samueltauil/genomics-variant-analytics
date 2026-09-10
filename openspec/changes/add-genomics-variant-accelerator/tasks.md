## 1. Repository guardrails and foundation

Implementation note (2026-09-10): task 1.1 is complete. PR #1 installed the trusted data-hygiene workflow; `main` requires strict GitHub Actions checks and independent PR approval, including for administrators. Six isolated synthetic PRs failed the trusted policy and their merge API attempts were refused; an administrator direct push of a passing but unapproved PR head was also refused. The initial zero-approval fast-forward gap, corrective settings, run URLs, and pending test-PR closure submissions are recorded in [CONTRIBUTING.md](../../../CONTRIBUTING.md#live-acceptance-record-2026-09-10). All 12 local tests, actionlint 1.7.12, and strict OpenSpec validation pass. Task 1.2 is also complete: secret scanning and push protection were confirmed enabled, a harmless control push succeeded, and a never-issued PAT-shaped probe received an explicit GitHub push-protection rejection. The remote stayed unchanged and the disposable branch was removed; see the [secret-protection evidence](../../../CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10). Cloud work remains unverified.

Local-first phase (2026-09-10): Azure access, provisioning, uploads and live benchmarks are paused at the user's request. The [candidate infrastructure inventory and local validator](../../../infra/README.md) prepare asset dependencies and task traceability only; resource-list and plan approval are pending before IaC generation. No cloud task is complete on the strength of this local validation, and all existing acceptance criteria remain unchanged.

Task 1.3 preparation: the [local write smoke harness](../../../infra/README.md#local-write-smoke-test) measures bounded synthetic sequential writes, verifies SHA-256 read-back integrity and removes its scratch file. Network paths are rejected. This implements local test tooling only, not share provisioning, the 100 GiB SMB benchmark or IOPS-ceiling verification; task 1.3 remains pending.

- [x] 1.1 Create the public repository, protect the default branch to require a pull request, and add the data-hygiene status check as required, and verify a pull request containing a `.vcf`, `.bam`, `.cram`, or `.fastq` file or an oversized file cannot be merged, and a direct push to the default branch is refused
- [x] 1.2 Enable secret scanning with push protection, and verify a commit carrying a recognized credential pattern is blocked at push time
- [ ] 1.3 Provision the SSD provisioned-v2 classic file share for the SMB landing zone with SMB Multichannel enabled, and verify a 100 GiB sequential write sustains the provisioned throughput and the share reports the expected IOPS ceiling
- [ ] 1.4 Provision the ADLS Gen2 landing account and container set following the healthcare data solutions folder taxonomy (`Ingest`, `Process`, `Failed`, `External`, `Inventory`, `ReferenceData`, `SampleData`) with genomics modality subfolders, and verify each path exists and is writable by the staging identity only
- [ ] 1.5 Assemble the demo dataset from Illumina Platinum Genomes plus generated synthetic subject, sample, and cohort identifiers, and verify a scan of the manifest finds no real patient identifier and every subject id matches the synthetic id pattern
- [ ] 1.6 Stage the demo run into the landing zone under a realistic instrument folder convention, and verify the file layout matches the convention with no path rewriting

## 2. Landing zone behavior

Task 2.1 verification (2026-09-10): [the local scheduled scanner](../../../docs/landing-inventory.md) inventories seeded synthetic run folders, persists first-observed arrivals across restarts, and reports run/sample IDs, sizes, timestamps and states. All 12 focused tests pass, including scheduled discovery, path guards and failed-scan snapshot preservation. This verifies the scan logic locally, not an Azure scheduler or SMB connectivity. Completeness and failed-transfer transitions remain tasks 2.2 and 2.3; all discovered files currently remain `arriving`.

- [x] 2.1 Implement the scheduled directory scan that inventories run folders, and verify it lists run and sample identifiers, sizes, arrival timestamps, and states for a seeded run
- [ ] 2.2 Implement the completeness stability check (size and last-modified unchanged across two consecutive polls, or vendor completion marker), and verify a file copied slowly reports `arriving` until the copy ends and `complete` afterwards
- [ ] 2.3 Implement failed-transfer detection and the retry path, and verify an interrupted transfer is marked `failed`, is excluded from staging, and that re-sending it replaces the failed entry without affecting sibling files in the run
- [ ] 2.4 Restrict landing-zone data-plane access to the ingestion identity and the instrument service account, and verify a pipeline identity is denied a direct read of the share

## 3. Staging to object storage

- [ ] 3.1 Build the Copy activity pipeline from the SMB share to the ADLS `Ingest` path, filtered to files in the `complete` state, and verify a run copies only complete files and skips `arriving` ones
- [ ] 3.2 Add source and destination checksum comparison to the pipeline, and verify a deliberately corrupted destination causes the staging record to be marked `failed` and withheld from downstream processing
- [ ] 3.3 Emit the staging record (source path, destination URI, state, integrity result, storage tier, classification) to the staging log table, and verify all six fields are populated for every file of a demo run
- [ ] 3.4 Register the pipeline with Purview and confirm Copy activity lineage appears for the Files-to-ADLS hop, and verify the staged artifact resolves back to its landing-zone source in the catalog
- [ ] 3.5 Configure the Storage Actions task for blob-side lifecycle (tiering and index tags) on staged artifacts, and verify an artifact past the age threshold transitions tier while its URI and lineage link still resolve

## 4. Reference data

- [ ] 4.1 Publish GRCh38 and hg19 builds plus gene and transcript annotations into `ReferenceData` under `name/version` paths with a per-artifact checksum manifest, and verify the inventory listing returns type, name, and version for each entry
- [ ] 4.2 Enforce write-once semantics on published reference versions, and verify a write targeting an existing published version is rejected while publishing a new version succeeds and leaves the prior version retrievable
- [ ] 4.3 Add the workflow-to-reference compatibility manifest and the submission-time validation, and verify an incompatible workflow/reference pairing is rejected before any compute pool is allocated
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

- [ ] 6.1 Model the Subject → Sample → Sequencing Run → FASTQ → BAM/CRAM → VCF → variant chain, and verify downward traversal from a subject and upward traversal from a variant both return the full chain for the demo data
- [ ] 6.2 Populate file-level entries with storage URI, analysis stage, producing run, and integrity result, and verify every artifact of the demo run has all four populated
- [ ] 6.3 Enforce referential integrity on writes, and verify an entry referencing a non-existent sample is rejected
- [ ] 6.4 Implement archive semantics, and verify archiving an artifact leaves referencing variant records resolving to a valid entry marked archived
- [ ] 6.5 Split clinical from research metadata behind separate grants, and verify a research-only principal reads research attributes and receives no clinical attributes

## 7. Delta variant store

- [ ] 7.1 Create the Bronze variant Delta table with the eight VCF core columns and the twelve accelerator context fields, and verify the table schema matches the spec field list exactly
- [ ] 7.2 Implement VCF parsing and load using GATK `VariantsToTable` semantics for INFO and FORMAT extraction, and verify a demo VCF loads with core fields populated on every row
- [ ] 7.3 Implement mandatory-field validation, and verify records missing `REF` or `ALT` are rejected rather than written
- [ ] 7.4 Implement null-rather-than-fabricate handling for annotation fields, and verify an unannotated VCF loads with null `gene`, `transcript`, and `variant_consequence` and no row loss
- [ ] 7.5 Populate `source_file_uri`, `pipeline_version`, `reference_build`, and `ingestion_timestamp` from run provenance on every row, and verify provenance resolution for a sampled variant returns the source VCF, producing run, and reference build
- [ ] 7.6 Implement the rejected-record table with reason, source file URI, and source line reference, and verify a file with seeded bad rows produces retrievable rejection entries and correct accepted/rejected counts
- [ ] 7.7 Implement ingestion idempotency keyed on the source artifact, and verify running ingestion twice on the same VCF leaves the attributable variant count unchanged
- [ ] 7.8 Verify reprocessing distinguishability by ingesting the same sample under a new pipeline version and confirming both record sets are separable by `pipeline_version`
- [ ] 7.9 Configure OneLake shortcuts to the ADLS genomic artifacts rather than copying them, and verify `source_file_uri` resolves through the shortcut and continues to resolve after the artifact is tiered
- [ ] 7.10 Apply and document the table layout strategy, and verify the table reports its current partitioning or clustering and last maintenance state

## 8. Governance

- [ ] 8.1 Define the four access tiers as role assignments, and verify a cohort-analytics principal can read aggregates and is denied raw file reads, and a variant-store principal is denied raw FASTQ/BAM reads
- [ ] 8.2 Convert all service-to-service access to managed identities with secrets in Key Vault, and verify a repository scan finds no embedded connection string or storage key
- [ ] 8.3 Implement de-identified query projection, and verify a caller without subject-linkage access receives sample and cohort attributes with subject linkage withheld rather than a whole-query denial
- [ ] 8.4 Separate research and clinical workspaces with independent grants and a recorded authorization on cross-workspace movement, and verify an unapproved transfer is blocked and an approved one is recorded
- [ ] 8.5 Apply classifications at staging and ingestion and surface them to consumers, and verify a staged artifact and the variant table both report a classification
- [ ] 8.6 Wire pipeline executions, data access, reprocessing, and cross-workspace transfers into the audit trail with immutability for recorded principals, and verify a reprocessing event and a patient-linked metadata query each produce a tamper-resistant entry
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
- [ ] 10.7 Author the repository AI context — instructions, prompt files, and agent skills covering the VCF schema, no-PHI constraint, reference-build handling, and positioning limits — and verify a request to add a variant-store column returns a response reflecting those rules unprompted
- [ ] 10.8 Build the MCP server fronting the governed query interface with server-side access-tier enforcement, and verify a de-identified caller's assisted cohort question returns results without subject linkage, that the server exposes no raw table or storage credentials, and that assisted queries appear in the audit trail
- [ ] 10.9 Enable automated pull-request review on workflow, container, manifest, and schema paths, and verify it flags a reference-build change with no version bump and a variant-store column absent from the specs
- [ ] 10.10 Configure the scheduled agent triage for failed pipeline runs, and verify an overnight failure opens an issue carrying failing stage, run identifier, reference build, pipeline version, and log location, and that a recurrence updates that issue rather than duplicating it
- [ ] 10.11 Document the account-tier dependencies and substitute controls, and verify each tier-gated feature named in the platform spec has a stated substitute and residual gap

## 11. Demo enablement

- [ ] 11.1 Write the preflight check covering subscription type, required roles, compute and storage quota, regional availability of every component, and local tooling versions, and verify it reports each unmet prerequisite with found and required values on a deliberately unprepared subscription
- [ ] 11.2 Gate provisioning on preflight, and verify provisioning refuses to start with an unmet quota and creates no resource
- [ ] 11.3 Parameterize every environment-specific value, and verify a scan finds no subscription id, tenant id, or author-specific resource name outside marked examples, and that a clean clone deploys with only the documented required inputs
- [ ] 11.4 Make provisioning idempotent from a single entry point with a stated duration, and verify a re-run after a partial failure completes the remainder without duplication and a re-run against a complete environment reports no changes
- [ ] 11.5 Produce the cost statement covering per-delivery cost, idle cost, dominant resources, and the estimate's date and region, and verify each element is present and derived from actual resource sizing
- [ ] 11.6 Write the bring-up and seeding phases with per-phase duration and confirming observation, and verify an engineer following them against a fresh subscription reaches the documented ready state
- [ ] 11.7 Write the seven-step presentation sequence naming, for each step, the observable output its capability spec requires, and verify each named output is one the implementation actually produces
- [ ] 11.8 Script the rehearsed failure demonstrations — failed transfer, rejected variant record, denied access attempt — and verify each trigger produces the response its capability spec states
- [ ] 11.9 Build the reset procedure with diagnostics, and verify a reset returns the environment to its starting state with no prior-delivery records visible and without redeploying infrastructure, and that an interrupted reset can be diagnosed to determine which stores are clean
- [ ] 11.10 Build teardown, and verify no demo-created resource remains in the target subscription afterwards, and that idle-cost resources are named for engineers who defer it
- [ ] 11.11 Write the claim register covering the released-blueprint, compliance, customer-reference, and clinical-use boundaries with supported and prohibited phrasing for each, and verify every presenter-facing document passes review against it
- [ ] 11.12 Write the talk track marking production considerations separately from demonstrated behavior, and verify it passes review against the claim register
- [ ] 11.13 Publish the demonstrated-versus-specified coverage table, and verify every capability is marked demonstrated, partially demonstrated, or specified only, and that the markings match what the demo environment actually exercises
- [ ] 11.14 Publish known limitations with cause, workaround, and whether each is inherent to the platform or specific to the demo configuration, and verify the platform constraints recorded in the design appear there
- [ ] 11.15 State support expectations and the defect route, and verify the documentation declares no support commitment and distinguishes the accelerator from a supported Microsoft offering
- [ ] 11.16 Dry-run the full flow as a first-time reader using only the published documentation, from preflight through teardown, and verify no step requires knowledge absent from the repository

## 12. End-to-end validation and positioning

- [ ] 12.1 Execute the full seven-step demo scenario from instrument write through governance review, and verify each step produces the observable output named in its capability spec
- [ ] 12.2 Measure and report the accelerator KPIs (pipeline success rate, arrival-to-queryable time, query response time, percentage of records linked to source files, reprocessing time, cost per sample), and verify each is produced from instrumented data rather than estimated
- [ ] 12.3 Trace a single variant end to end from its record through `pipeline_version` to the immutable release, the release attestation, the build provenance, and the SBOM, and verify every hop resolves without a self-asserted link
- [ ] 12.4 Review all customer-facing material against the positioning constraints, and verify it makes no compliance claim, no released-blueprint claim, no unverified customer attribution, and no clinical determination claim for assisted output
- [ ] 12.5 Cross-check every "proposed" item in the proposal's assumptions against what was actually built, and verify the accelerator documentation still labels each as an assumption or records its confirmation
