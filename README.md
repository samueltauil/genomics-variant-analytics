# Genomics Variant Analytics Accelerator

**Sequencer → governed variant store on Azure.** Keep the laboratory's SMB write path untouched while moving storage, compute, governance, and analytics into Azure, ending in a Delta-based variant store that is queryable and traceable to its source files.

> **Status: implementation started. Nothing here is deployable yet.**
> The repository data-hygiene checker and its tests are implemented, with GitHub workflows ready for installation. Live branch protection is not yet verified. No infrastructure, pipeline, or notebook code exists. See [Coverage](#coverage) for what that means in a customer conversation.

## What this is, and what it is not

This is an **accelerator and reference architecture** assembled from validated genomics patterns and healthcare customer requirements.

It is **not** a released Microsoft blueprint, not a supported product, and not a confirmed end-to-end customer deployment. Deploying it does not make genomic data compliant — compliance depends on your configuration, jurisdiction, policies, and operating procedures.

Read [docs/claim-register.md](docs/claim-register.md) before presenting any of this to a customer. It states, per boundary, the phrasing that is supported and the phrasing that is not.

## Who this is for

A Microsoft solution engineer who wants to run this as a customer demo: check that your subscription can host it, provision it, deliver it, reset, tear down.

Read in this order:

1. This README — status, coverage, prerequisites, cost
2. [docs/limitations.md](docs/limitations.md) — what you will run into
3. [docs/claim-register.md](docs/claim-register.md) — what you may and may not say
4. [docs/demo-runbook.md](docs/demo-runbook.md) — the delivery itself

Whether this becomes a blueprint reference later is undefined and not the current intent.

## The architecture

```text
Sequencer / lab instrument
        │  SMB
        ▼
Azure Files — primary-analysis landing zone
        │  Data Factory Copy
        ▼
Blob / ADLS / OneLake
        │  Nextflow on Azure Batch or Slurm HPC
        ▼
BAM / CRAM / GVCF / VCF
        │  parse and enrich
        ▼
Delta genomic variant store
        ├── metadata store
        ├── reference-data zone
        ├── notebooks and SQL
        ├── visualization
        └── AI-assisted exploration
```

The design goal is narrow and load-bearing: **the laboratory changes nothing.** No instrument reconfiguration, no new folder conventions, no vendor involvement.

## Capabilities

Ten capability specs live in [openspec/](openspec/). Each is a behavior contract with testable scenarios, not an implementation plan.

| Capability | Covers |
|---|---|
| `ingestion/smb-landing-zone` | SMB share accepting sequencer output unchanged |
| `ingestion/object-storage-staging` | Files → object storage with integrity and lineage |
| `processing/secondary-analysis` | FASTQ → BAM/CRAM → VCF on Batch or HPC |
| `variant-store/delta-variant-store` | Bronze Delta store, VCF core plus context fields |
| `variant-store/genomic-metadata` | Subject → sample → run → file → variant chain |
| `reference-data/reference-management` | Versioned, immutable reference builds |
| `governance/access-and-lineage` | Access tiers, identity, classification, audit |
| `analytics/variant-query-and-visualization` | Queries, notebooks, views, AI-assisted exploration |
| `platform/engineering-workflow` | Source of record, attestations, guardrails, AI context |
| `platform/demo-enablement` | Preflight, provisioning, delivery, reset, teardown, pitch boundaries |

## Coverage

The engineering-workflow capability is **partially demonstrated** locally: its data-hygiene checker runs against synthetic test repositories. GitHub enforcement remains unverified. All other capabilities remain **specified only** in the demo environment.

| State | Meaning for a customer conversation |
|---|---|
| Demonstrated | You can show it working |
| Partially demonstrated | Show the part that runs; describe the rest as intent |
| **Specified only** | Describe as architectural intent. Do not imply working software. |

This table gets updated as capabilities are implemented. If it says specified only, do not demo it.

## Prerequisites

A preflight check will verify these. Until it exists, treat this list as the manual version.

- An Azure subscription you can create resources in, with the roles needed to assign RBAC and create federated credentials
- Quota for the Batch or HPC pool sizing you intend to run
- A region offering every component in the architecture above
- Azure CLI, Git, and a Delta-capable engine (Microsoft Fabric or Azure Databricks)
- A GitHub account for forking

## Cost

Not yet estimated. Once provisioning exists, this section will state per-delivery cost, idle cost, the resources that dominate each, and the date and region the estimate was produced for.

Until then: Azure Managed Lustre and provisioned-v2 SSD file shares are the two line items that will dominate, and both bill while idle.

## Data

Demo data is **synthetic or openly licensed**. Variant content comes from Illumina Platinum Genomes via Azure Open Datasets; subject, sample, and cohort identifiers are generated. No real patient-identifiable data is used, and none should be added.

The repository itself must never hold genomic data. The data-hygiene workflow rejects genomic file extensions and Git blobs over 1 MiB. Server-side enforcement requires the [administrator setup and acceptance checks](CONTRIBUTING.md#administrator-setup-and-acceptance); those live settings are not yet verified.

## Reuse

Clone it and run it. See [docs/limitations.md](docs/limitations.md) for what you will run into, and [docs/demo-runbook.md](docs/demo-runbook.md) for the delivery flow.

## Support

None. This is a demo accelerator with no support commitment and no service level. It is not a supported Microsoft offering.

Found a defect that blocked a delivery? See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Demo variant content comes from Illumina Platinum Genomes via Azure Open Datasets under its own terms; the MIT grant covers this repository's specs, documentation, and code.
