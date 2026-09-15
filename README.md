# Genomics Variant Analytics Accelerator

**Sequencer → governed variant store on Azure.** Keep the laboratory's SMB write path untouched while moving storage, compute, governance, and analytics into Azure, ending in a Delta-based variant store that is queryable and traceable to its source files.

> **Status: implementation started. Nothing here is deployable yet.**
> The repository data-hygiene checker and workflows are installed. PRs and passing checks remain required; the user-authorized solo-maintainer policy requires no independent approval. The earlier administrator-rejection tests describe the previous policy, not a current direct-push guarantee. Secret scanning and push protection are enabled, with a [synthetic credential push rejected](CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10). A [candidate infrastructure inventory and local-only validator](infra/README.md) and [scheduled local landing inventory](docs/landing-inventory.md) are available; IaC templates, processing pipelines and notebooks are not implemented. Azure operations are paused. See [Coverage](#coverage) for what that means in a customer conversation.

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

The engineering-workflow capability is **partially demonstrated**: its data-hygiene checker passes local synthetic tests, and live GitHub tests verify forbidden-file merge refusal and push-time rejection of a recognized synthetic credential pattern. The earlier independent-review policy also rejected unapproved administrator direct pushes; that guarantee no longer applies under the authorized solo-maintainer policy. Secret protection does not detect every sensitive value and has explicit bypass flows; see its [acceptance record and limits](CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10). The rest of the engineering workflow remains unverified. No data-plane capability is demonstrated end to end; the other capabilities remain specified only or partially demonstrated as documented in the [capability coverage table](docs/coverage.md).

| State | Meaning for a customer conversation |
|---|---|
| Demonstrated | You can show it working |
| Partially demonstrated | Show only the evidenced part; describe the rest as intent |
| **Specified only** | Describe as architectural intent. Do not imply working software. |

See the [capability coverage table](docs/coverage.md) for all ten capability statuses, the evidence behind each marking, and presenter guidance. If a row says specified only, do not demo it; if it says partially demonstrated, show only the evidence named in that row.

The landing directory scanner has passed seeded local tests for tasks 2.1 and
2.2, including size/mtime stability and optional completion markers. This is not
an SMB/cloud demonstration; failed-transfer handling and staging remain pending.
See [local inventory scope](docs/landing-inventory.md). An executor-independent
[reference submission gate](docs/reference-submission.md) rejects incompatible
build/annotation versions locally; actual workflow integration is still pending.
The [local metadata model](docs/metadata-store.md) passes synthetic tests for
bidirectional lineage, file details, referential integrity and metadata-only
archival (tasks 6.1 through 6.4). It is not an access-controlled service;
integration with pipeline outputs remains pending. OpenSpec progress is 8/89
tasks complete, including historical guardrail acceptance under the earlier policy.

## Prerequisites

For local infrastructure preparation, use PowerShell 7.2+, Python 3.10+ and Git;
no Azure account or CLI is needed. See the [local commands](infra/README.md#run-locally).
The [local write smoke test](infra/README.md#local-write-smoke-test) verifies
synthetic write integrity and cleanup without using Azure or SMB.

A future cloud preflight check will verify the following. It is not implemented
or authorized in the current local-only phase; treat this list as planning input.

- An Azure subscription you can create resources in, with the roles needed to assign RBAC and create federated credentials
- Quota for the Batch or HPC pool sizing you intend to run
- A region offering every component in the architecture above
- Azure CLI, Git, and a Delta-capable engine (Microsoft Fabric or Azure Databricks)
- A GitHub account for forking

## Cost

Azure access and provisioning remain paused. No cloud resources were created or
charged by the local implementation commands. Before any billable action, a
dated, region-specific estimate based on approved sizing and an explicit spending
limit are required. Local checks are not a deployment authorization.

Not yet estimated. Once provisioning exists, this section will state per-delivery cost, idle cost, the resources that dominate each, and the date and region the estimate was produced for.

Until then: Azure Managed Lustre and provisioned-v2 SSD file shares are the two line items that will dominate, and both bill while idle.

## Data

Demo data is **synthetic or openly licensed**. Variant content comes from Illumina Platinum Genomes via Azure Open Datasets; subject, sample, and cohort identifiers are generated. No real patient-identifiable data is used, and none should be added.

The repository itself must never hold genomic data. The data-hygiene workflow rejects genomic file extensions and Git blobs over 1 MiB. It is a required merge gate on `main`; forks must repeat the [administrator setup and acceptance checks](CONTRIBUTING.md#administrator-setup-and-acceptance). This does not prevent publication to unprotected branches or forks.

## Reuse

Clone it to review or extend the specifications; there is no runnable deployment
yet. See [docs/limitations.md](docs/limitations.md) for the current constraints
and [docs/demo-runbook.md](docs/demo-runbook.md) for the planned delivery flow.

## Support

This demo accelerator has no support commitment or SLA and is not a supported
Microsoft offering. See [SUPPORT.md](SUPPORT.md) for support expectations and
the defect-reporting route.

## License

[MIT](LICENSE). Demo variant content comes from Illumina Platinum Genomes via Azure Open Datasets under its own terms; the MIT grant covers this repository's specs, documentation, and code.
