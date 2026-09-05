## Why

Genomics laboratories run sequencers and lab applications that write large files over SMB into fixed folder structures, so any modernization that asks the lab to reconfigure its instruments is rejected before it starts. At the same time, the downstream output of those instruments — VCF/GVCF files sitting in object storage — is hard to query, hard to trace back to a sample, and hard to govern.

This change specifies a solution-accelerator reference architecture that keeps the sequencer write path untouched while moving storage, compute, governance, and analytics into Azure, ending in a Delta-based governed variant store.

## What Changes

- Specify an SMB landing zone on Azure Files that accepts sequencer output without changing instrument configuration, folder conventions, or naming.
- Specify staging from the SMB landing zone into Blob/ADLS object storage, with integrity verification and recorded lineage.
- Specify secondary-analysis execution (FASTQ → BAM/CRAM → VCF/GVCF) on Azure Batch or HPC, driven by a portable workflow engine, with run provenance captured for every execution.
- Specify a Delta-based genomic variant store built from parsed VCF records, carrying the core VCF columns plus accelerator fields for cohort, gene, provenance, reference build, and pipeline version.
- Specify a metadata store that links Subject → Sample → Sequencing Run → FASTQ → BAM/CRAM → VCF → variant records.
- Specify a versioned reference-data zone (reference builds, annotations, knowledge bases) that pipelines bind to explicitly.
- Specify the governance model: access tiers, managed identities, RBAC, classification, lineage, and audit trails.
- Specify the tertiary analytics surface: variant queries, the demo query set, AI-assisted exploration, and the visualization views.
- Specify the engineering platform: the repository as verifiable source of record, `pipeline_version` bound to immutable releases, signed build and SBOM attestations, merge-time exclusion of genomic data from version control, secretless deployment, and repository-resident AI context.
- Specify demo enablement: the flow a Microsoft solution engineer runs end to end — validate prerequisites, provision, deliver, reset, tear down — plus the claim register that governs what is said while presenting.

No breaking changes — this is the first specification of the accelerator.

### Assumptions

The background material separates confirmed items from proposed ones. Items below are **proposed** and are specified as assumptions to be validated, not as confirmed design:

- The exact eight-column variant schema. The study states eight VCF columns are required but does not enumerate them; specs use the standard VCF core (`CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`) as the working set.
- The hereditary-cancer screening demo scenario and its query set.
- The specific visualization screens.
- Partitioning and optimization strategy for the Delta tables.
- Query-performance targets and the additional accelerator KPIs.
- A full Microsoft Purview implementation, and the specific use of Databricks, Fabric, Azure ML, or AI Foundry.
- The demo repository living in a personal GitHub account, which determines whether environment protection rules require the repository to be public.
- The audience being Microsoft solution engineers running this as a demo. Whether it later becomes a blueprint reference is out of scope and not an intent of this change.
- Customer attributions carried in earlier drafts of the source material, which remain unverified and are excluded from this repository.

### Corrections to the background study

Two steps described in the study are not supported by the platform as documented, and the specs are written without them:

- **Azure Storage Actions cannot move data from Azure Files to Blob.** It operates on Azure Blob Storage and Azure Data Lake Storage only. The staging capability is specified by behavior (move, verify, record lineage, tier) rather than by that service; see [design.md](design.md) for the mechanism.
- **Event Grid raises no file-created event for Azure file shares.** Storage events cover Blob and ADLS Gen2 only, so file arrival in the landing zone is detected by scan rather than by event.

Two constraints apply across every capability: all demo data is synthetic with no real PHI, and nothing in this accelerator asserts that genomic data becomes compliant by using it — compliance depends on the customer's configuration, jurisdiction, and operating procedures.

## Capabilities

### New Capabilities

- `ingestion/smb-landing-zone`: Azure Files SMB share as the primary-analysis landing zone for sequencer output; instrument compatibility, folder conventions, arrival visibility, and transfer failure handling.
- `ingestion/object-storage-staging`: movement of landed files from Azure Files into Blob/ADLS, including integrity verification, tiering, classification, and lineage records.
- `processing/secondary-analysis`: execution of the FASTQ → alignment → BAM/CRAM → variant calling → VCF/GVCF pipeline on Azure Batch or HPC through a portable workflow engine, with per-run provenance.
- `variant-store/delta-variant-store`: the Bronze Delta genomic variant store — record schema, ingestion from VCF, rejected-record handling, and table maintenance.
- `variant-store/genomic-metadata`: the metadata model linking subjects, samples, runs, and file artifacts to variant records, using synthetic identifiers.
- `reference-data/reference-management`: versioned reference builds, annotations, and knowledge bases, with explicit pipeline binding and reproducibility guarantees.
- `governance/access-and-lineage`: access tiers, identity, RBAC, classification, audit trails, and the research/clinical separation.
- `analytics/variant-query-and-visualization`: the tertiary analytics surface — supported query scenarios, notebook/SQL access, AI-assisted exploration, and accelerator visualization views.
- `platform/engineering-workflow`: the repository as source of record for pipelines, infrastructure, notebooks, and reference manifests; release-anchored versioning, supply-chain attestations, data-exclusion controls, deployment approval, and version-controlled AI context.
- `platform/demo-enablement`: the end-to-end engineer flow — checkable prerequisites gating provisioning, parameterized and idempotent deployment, stated cost, the delivery runbook with rehearsed failure paths and reset, teardown, and the claim boundaries, coverage table, and limitations that govern the pitch.

### Modified Capabilities

None — no existing specs.

## Impact

- Creates the initial spec set under `openspec/specs/` for ten capabilities; no code exists yet, so this change is specification-only.
- Downstream implementation will target Azure Files, Storage Actions, Blob/ADLS or OneLake, Azure Batch or CycleCloud/Slurm HPC, a Delta-capable engine (Fabric or Databricks), Key Vault, an identity/RBAC configuration, and a GitHub repository providing CI/CD, release-anchored versioning, and supply-chain attestation.
- Source material: [context/study.md](../../../context/study.md).
- Positioning is an accelerator and reference architecture built from validated genomics patterns, not a released Microsoft blueprint or a confirmed end-to-end customer deployment.
