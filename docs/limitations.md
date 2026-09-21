# Known limitations

This page records constraints an engineer can encounter while preparing or
presenting the accelerator. Every entry identifies the cause, a workaround or
mitigation, and whether the constraint is:

- **Inherent to the platform:** the underlying service or product imposes the
  constraint, so a production deployment must account for it too.
- **Demo-specific:** the constraint follows from this accelerator's current
  architecture, account tier, assumptions, or demonstration scope. A customer
  implementation can choose differently.

The accelerator is a reference architecture, not a clinical system or a
compliance solution. See [claim-register.md](claim-register.md) for the language
that may be used when presenting it.

## Azure data-plane and storage constraints

### Storage Actions cannot move files from Azure Files to object storage

**Classification:** Inherent to the platform.

**Limitation:** Azure Storage Actions cannot implement an
`Azure Files -> Blob/ADLS` transfer.

**Cause:** Storage Actions operates on Azure Blob Storage and Azure Data Lake
Storage objects. It has neither an Azure Files source nor a cross-service copy
operation.

**Workaround or mitigation:** Use Azure Data Factory or Fabric Data Factory Copy
activity for the Files-to-ADLS hop and its supported catalog lineage. Retain
Use account-native lifecycle management for supported blob-side tiering and
retention after the copy. HNS accounts do not support blob index tags, so rules
must use supported conditions such as path prefix and age. AzCopy on a hosted
agent is a fallback for a large single file when Copy activity throughput is
insufficient, but it requires separate lineage recording.

### Azure file shares do not emit file-created events

**Classification:** Inherent to the platform.

**Limitation:** Arrival detection on the SMB landing zone cannot be driven by a
native Event Grid file-created event.

**Cause:** Event Grid publishes storage events for Blob and ADLS Gen2, not for
Azure file shares. There is no `Microsoft.Storage.FileCreated` event.

**Workaround or mitigation:** Scan a bounded set of run directories on a
schedule. Treat a file as complete only after size and last-modified values are
stable across two polls, or after an instrument-written completion marker is
present. This introduces polling latency and metadata I/O; tune the interval to
the expected run duration and do not recursively walk the whole share. A
VM-hosted file-system watcher can publish to a custom Event Grid topic when
lower latency justifies another component for the lab to operate.

### SMB requires a classic Azure Files deployment

**Classification:** Inherent to the platform.

**Limitation:** The SMB landing zone cannot use the newer
`Microsoft.FileShares` resource provider.

**Cause:** That provider supports NFS shares only. SMB shares are deployed in a
storage account through `Microsoft.Storage`.

**Workaround or mitigation:** Provision a classic Azure Files share through
`Microsoft.Storage`, and keep this requirement in preflight and infrastructure
validation so an incompatible share type is rejected before data seeding.

### Azure Files has file-size and throughput ceilings

**Classification:** Inherent to the platform.

**Limitation:** A single file is limited to 4 TiB. HDD shares provide
approximately 60 MiB/s per file, while SSD SMB has much higher but still finite
per-file throughput.

**Cause:** These are Azure Files scalability and performance limits; storage
capacity alone does not guarantee the IOPS or throughput required by a
sequencing run.

**Workaround or mitigation:** Use SSD provisioned v2, provision storage, IOPS,
and throughput for the expected workload, and enable SMB Multichannel. Validate
the landing zone with a representative sequential-write test before a
delivery. Files over 4 TiB must be split by the producing workflow or landed on
a different storage technology; the accelerator cannot bypass the service
limit.

### Large genomic files remain in object storage

**Classification:** Demo-specific.

**Limitation:** FASTQ, BAM/CRAM, and VCF artifacts are not materialized again in
the analytics lakehouse. Only parsed variant rows are copied into Delta.

**Cause:** Physical copies of multi-terabyte genomic artifacts add transfer
time and cost. The healthcare data solutions guidance recommends a bring-your-
own-storage shortcut pattern for imaging and genomics volumes.

**Workaround or mitigation:** Keep one canonical copy in ADLS and expose it
through OneLake shortcuts. Preserve the canonical `source_file_uri` in variant
rows and test that the shortcut and lineage link still resolve after lifecycle
tiering. A deployment that requires physical isolation can copy the files, but
must budget for duplicate storage and update lineage accordingly.

### Managed Lustre scratch requires lifecycle orchestration

**Classification:** Demo-specific.

**Limitation:** The HPC execution path is not a permanently available file
system. Scratch must be created, hydrated, exported, and removed for each
campaign, and an interrupted export or teardown can require operator recovery.

**Cause:** The design uses Azure Managed Lustre with Blob HSM integration as
ephemeral high-performance scratch so idle HPC storage does not remain
provisioned.

**Workaround or mitigation:** Automate import, export, and teardown as workflow
stages; retain run state and logs outside the scratch file system; and require
an operator to inspect and retry a failed export before teardown. Customers
that keep persistent scratch can reduce orchestration at the cost of ongoing
capacity charges.

## Catalog, lineage, and reproducibility constraints

### Purview does not provide variant-record lineage for Fabric lakehouses

**Classification:** Inherent to the platform.

**Limitation:** Microsoft Purview cannot be used as the system of record for
lineage from an individual variant row to its source VCF and pipeline run.

**Cause:** Fabric scanning provides item-level metadata and lineage. Sub-item
metadata scanning is preview functionality, and sub-item lineage is not
supported.

**Workaround or mitigation:** Store `source_file_uri`, `pipeline_version`, and
`reference_build` on every variant row and join those values to the metadata
store's subject-to-artifact graph. Use Purview for classification and
coarse-grained pipeline/lakehouse lineage only. Do not promise variant-level
lineage in the Purview user interface.

### A container digest does not prove how an image was built

**Classification:** Inherent to the platform.

**Limitation:** An image in Azure Container Registry has content identity, but
the registry digest alone does not establish the source repository, commit,
workflow, or toolchain that produced it.

**Cause:** Registry digests identify bytes, not build provenance or the contents
of the bioinformatics toolchain.

**Workaround or mitigation:** Publish GitHub build-provenance and signed SBOM
attestations to ACR, verify them before compute allocation, and make
`pipeline_version` resolve through an immutable release to the attested image.
If attestation publication or verification fails, reject the run rather than
falling back to an unattested image.

**Repository implementation status:** The container workflow and local
pre-allocation verifier are implemented. Release `v0.2.1-pipeline` authenticated
to Azure through OIDC, pushed the synthetic pipeline image to ACR, and
published registry-backed SLSA provenance and CycloneDX SBOM attestations.
This verifies the demo supply-chain path only. It does not establish a
production bioinformatics toolchain or an independently approved clinical or
research deployment.

### Immutable releases cannot be corrected in place

**Classification:** Inherent to the platform.

**Limitation:** After an immutable release is published, its tag cannot be moved
or deleted, its assets cannot be changed or deleted, and its tag name cannot be
reused.

**Cause:** GitHub immutable releases deliberately make the release-to-commit
binding permanent and cryptographically verifiable.

**Workaround or mitigation:** Prepare the release as a draft, attach and verify
all assets and manifests, and publish only after manual review. Correct a
mistake with a new version and tag; do not expect to repair the published
release in place.

### Release assets are limited to 2 GiB per file

**Classification:** Inherent to the platform.

**Limitation:** Reference genomes and other large genomic artifacts cannot be
attached directly to a GitHub release.

**Cause:** GitHub caps each release asset at 2 GiB.

**Workaround or mitigation:** Keep reference data in immutable object-storage
paths. Release only the versioned manifest and checksums, and ensure the
manifest resolves to the storage location used by the workflow.

### The healthcare data solutions delivery model is changing

**Classification:** Inherent to the platform.

**Limitation:** A deployment cannot assume the managed healthcare data
solutions package will remain the long-term delivery mechanism.

**Cause:** A downloadable package for customer-managed implementations became
available on August 3, 2026. Beginning October 1, 2026, only existing customers
can deploy the managed solution, and managed-solution support ends on
December 31, 2027.

**Workaround or mitigation:** Depend on the documented genomics folder taxonomy,
medallion conventions, and lineage columns rather than on managed-solution
artifacts. Revalidate integration instructions when adopting a newer source
package.

## GitHub account and repository constraints

### Push rulesets are unavailable for this public repository

**Classification:** Demo-specific.

**Limitation:** The repository cannot block genomic file extensions at push
time across every branch and fork by using a push ruleset.

**Cause:** Push rulesets target private and internal repositories. This demo is
public and hosted in a personal account.

**Workaround or mitigation:** Protect the default branch, require pull requests,
and make a data-hygiene check required for merge when a change contains
`.vcf`, `.bam`, `.cram`, `.fastq`, or an oversized file. Secret scanning with
push protection remains a separate push-time control for recognized secrets.

**Residual gap:** A direct push to an unprotected branch is not covered by the
merge gate. A private or internal organization repository can add the stronger
push ruleset.

### Environment protection depends on repository visibility and plan

**Classification:** Demo-specific.

**Limitation:** A private fork on GitHub Free cannot use the environment
protection configuration assumed by the demo.

**Cause:** GitHub Free supports environments for public repositories; private
repositories require GitHub Pro or Team. Required reviewers are also limited to
six.

**Workaround or mitigation:** Keep the personal-account demo public, or move a
private deployment to a plan that supports protected environments. Validate
environment availability and reviewer configuration in preflight instead of
silently deploying without approval gates.

### Copilot content exclusion and centralized audit are unavailable

**Classification:** Demo-specific.

**Limitation:** This personal-account deployment cannot configure Copilot
content exclusion, centrally managed Copilot policy, or Copilot audit logs.

**Cause:** Those controls require Copilot Business or Enterprise.

**Workaround or mitigation:** Keep genomic and patient data out of the
repository entirely, expose variant data to assistants only through the
governed query interface, and enforce the repository data-hygiene gate. An
organization deployment needing centralized policy or audit must use the
appropriate Copilot plan.

### A public repository is a permanent, indexed surface

**Classification:** Demo-specific.

**Limitation:** Content pushed to the public repository may be indexed, copied,
or retained even after a later deletion.

**Cause:** Public Git history and forks are not a reversible data-distribution
channel.

**Workaround or mitigation:** Never commit genomic data, patient data, secrets,
or customer-specific identifiers. Run data-hygiene and secret checks before the
first push as well as on every pull request. Store sample data in the designated
object-storage location, not in Git or release assets.

## Demo data, analytics, and positioning constraints

### The demo combines an authorized public genome with synthetic context

**Classification:** Demo-specific.

**Limitation:** Demo cohort and clinical findings cannot be treated as evidence
about a real patient or population.

**Cause:** Variant content comes from the consented Illumina Platinum Genomes
dataset, while subject, sample, cohort, and clinical attributes are generated.
No real PHI or patient-identifiable metadata is included.

**Workaround or mitigation:** Present the data as biologically realistic but
clinically meaningless. Do not add real patient data to the repository or
shared demo environment. A customer evaluating real data must use its own
approved workspace, access controls, consent basis, data classification, and
operating procedures.

### The eight-column VCF schema is an accelerator assumption

**Classification:** Demo-specific.

**Limitation:** The source material says eight VCF columns are required but
does not enumerate them.

**Cause:** The accelerator adopts the standard core fields `CHROM`, `POS`, `ID`,
`REF`, `ALT`, `QUAL`, `FILTER`, and `INFO` as the most defensible working
interpretation.

**Workaround or mitigation:** Treat the schema as proposed until the source
requirement is confirmed. Keep extension fields nullable when they cannot be
derived, and update the variant-store spec, parser, tests, and AI context
together if a different field set is confirmed.

### Several analytics choices remain unvalidated

**Classification:** Demo-specific.

**Limitation:** The visualization screen set, table partitioning or clustering,
query-response target, accelerator KPIs, annotation toolchain, and final Delta
engine are not confirmed production choices.

**Cause:** They are proposed components or open design questions that require
representative data volumes, workload measurements, and customer requirements.
Both Fabric and Databricks satisfy the current Delta contract, and annotation
fields may be null.

**Workaround or mitigation:** Label these choices as proposed, publish measured
results with dataset size, date, region, and engine, and tune the layout before
production use. Do not fabricate missing annotations. Record any selected
engine or annotation toolchain as deployment configuration and version its
outputs.

### Batch and HPC equivalence is concordance-based

**Classification:** Demo-specific.

**Limitation:** The accelerator does not guarantee byte-identical BAM/CRAM,
VCF, or GVCF output across Azure Batch and Slurm/HPC.

**Cause:** Different executors, scheduling, libraries, and compression can
change bytes without changing the called variants.

**Workaround or mitigation:** Hold inputs, workflow version, container, and
reference version constant, then validate variant-level concordance against a
truth set with GATK `Concordance`. Define and report the acceptance threshold;
do not describe concordant outputs as bit-for-bit identical.

### The Delta variant store adds storage rather than replacing source files

**Classification:** Demo-specific.

**Limitation:** Parsed Delta rows and retained VCFs both consume storage.

**Cause:** Source files remain necessary for provenance and reprocessing, while
Delta materialization provides query performance.

**Workaround or mitigation:** Apply lifecycle tiers to retained artifacts,
materialize only variant records, and report cost per sample alongside query
performance. Do not claim that the variant store eliminates file-storage cost.

### AI-assisted interpretation is exploratory only

**Classification:** Demo-specific.

**Limitation:** Assistant output is not a clinical determination, diagnostic
recommendation, or clinical decision-support result.

**Cause:** The accelerator demonstrates governed query authoring and cohort
exploration; it does not validate an interpretation model as a medical device
or clinical workflow.

**Workaround or mitigation:** Label assisted output as exploratory, preserve
source traceability, enforce the caller's access tier server-side, and require
qualified human review outside the accelerator for any clinical use.

### Governance controls do not create compliance

**Classification:** Inherent to the platform.

**Limitation:** Deploying the accelerator does not make genomic data compliant
with a law, regulation, or organizational policy.

**Cause:** Compliance depends on jurisdiction, intended use, configuration,
data handling, validation, approvals, and operating procedures that this demo
cannot determine.

**Workaround or mitigation:** Present managed identities, RBAC, private
networking, classification, lineage, and audit as configurable building blocks.
Customers must perform their own legal, privacy, security, clinical, and
regulatory assessment.

## Manual intervention

### Controlled operations require a human decision

**Classification:** Demo-specific.

**Limitation:** The complete flow is not unattended. A person must approve
protected-environment deployments, external sharing, and movement between
clinical and research workspaces; review immutable releases before publication;
and authorize any retry that could overwrite or redistribute data.

**Cause:** These are intentional governance gates, not missing automation.
Automating the decision itself would remove separation of duties and the
recorded authorization required by the design.

**Workaround or mitigation:** Automate evidence collection and validation, but
keep the decision explicit. The runbook must identify the approver, required
evidence, expected response time, and audit record for each gate. Configure
multiple eligible reviewers so one unavailable reviewer does not block a demo.
In this single-maintainer reference repository, no second reviewer identity
is available: live testing demonstrated environment configuration, branch-ref
refusal, and self-approval refusal (GitHub itself reports
`current_user_can_approve: false` for the triggering user and rejects a
self-approval attempt), but a completed approved-tag deployment carrying a
distinct approver was not produced and is not claimed. A team deployment
adds a second reviewer and exercises that final scenario for real.

### Failure recovery, reset, and teardown can require an operator

**Classification:** Demo-specific.

**Limitation:** An engineer may need to retry an interrupted file transfer,
resolve a failed checksum, recover an incomplete Lustre export, trigger the
rehearsed failure scenarios, diagnose a partial reset, and run teardown.

**Cause:** The demo intentionally exposes failure handling, and destructive or
ambiguous recovery actions cannot always be chosen safely without inspecting
the affected run and stores.

**Workaround or mitigation:** Make normal operations idempotent, persist
diagnostics outside ephemeral resources, and provide runbook checkpoints for
each manual action. Before retrying, confirm the source artifact and target
state; before teardown, confirm required outputs and attestations were exported.
If teardown is deferred, the engineer must accept and monitor the documented
idle cost.

## Design constraint coverage

The table below maps every constraint recorded in the
[design](../openspec/changes/add-genomics-variant-accelerator/design.md) to the
limitation or mitigation above.

| Design constraint | Coverage in this page |
| --- | --- |
| 1. Storage Actions supports Blob/ADLS, not Azure Files | Storage Actions cannot move files from Azure Files to object storage |
| 2. Event Grid has no Azure file-share creation event | Azure file shares do not emit file-created events |
| 3. SMB requires classic file shares | SMB requires a classic Azure Files deployment |
| 4. Azure Files size and throughput limits | Azure Files has file-size and throughput ceilings |
| 5. Purview lacks Fabric sub-item lineage | Purview does not provide variant-record lineage for Fabric lakehouses |
| 6. Healthcare data solutions uses a genomics layout and recommends BYOS | Large genomic files remain in object storage |
| 7. Healthcare data solutions is changing delivery model | The healthcare data solutions delivery model is changing |
| 8. Managed Lustre imports and exports through Blob HSM | Managed Lustre scratch requires lifecycle orchestration |
| 9. Illumina Platinum Genomes supplies authorized demo variants | The demo combines an authorized public genome with synthetic context |
| 10. Immutable releases permanently bind tags, commits, and assets | Immutable releases cannot be corrected in place |
| 11. Artifact and SBOM attestations can be published to ACR | A container digest does not prove how an image was built |
| 12. Environment protection is visibility- and plan-dependent | Environment protection depends on repository visibility and plan |
| 13. Push rulesets and release assets have visibility or size limits | Push rulesets are unavailable for this public repository; Release assets are limited to 2 GiB per file |
| 14. Copilot enterprise controls are unavailable to personal accounts | Copilot content exclusion and centralized audit are unavailable |

## Open decisions

The following choices do not block the specifications, but must be resolved and
documented before claiming a production-ready reference deployment:

- Fabric or Databricks as the reference Delta engine.
- A bundled annotation step or annotated VCF input, including the selected
  toolchain and reference versions.
- Validated table layout, query-performance target, cost per sample, and
  accelerator KPI thresholds at representative scale.
