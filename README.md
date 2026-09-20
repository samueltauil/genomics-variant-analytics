# Genomics Variant Analytics Accelerator

**Sequencer → governed variant store on Azure.** Keep the laboratory's SMB write path untouched while moving storage, compute, governance, and analytics into Azure, ending in a Delta-based variant store that is queryable and traceable to its source files.

> **Status: partial implementation; no end-to-end demo.**
> OpenSpec progress is **80/89 tasks complete** as of September 20, 2026. The repository has local synthetic evidence for landing, metadata, variant-store, governance, analytics, visualization, KPI collection, MCP access, reference publication, pipeline provenance and presenter safeguards. The Nextflow secondary-analysis workflow runs locally with synthetic data, while Azure Batch and Slurm/HPC execution are not live. Disposable resource group `rg-genomics-20260919` exists in `eastus2` with expiry **October 3, 2026**. Its private storage foundation, account-native lifecycle policy, and admin-disabled ACR are deployed; release `v0.2.1-pipeline` passed OIDC image publication and registry-backed provenance/SBOM verification; and an unchanged deployment reports no effective ARM changes after fail-closed normalization. The lifecycle tier transition, private governed query endpoint, and full end-to-end demo remain incomplete. See [Coverage](#coverage) for the presentation boundary.

## What this is, and what it is not

This is an **accelerator and reference architecture** assembled from validated genomics patterns and healthcare workload requirements.

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
        │ Nextflow locally; Batch or Slurm HPC as prepared targets
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

Current coverage totals are **0 Demonstrated**, **10 Partially demonstrated**, and **0 Specified only**. No capability is complete enough to present as demonstrated, and no data-plane flow runs end to end. Secondary analysis runs locally through the pure-Python and Nextflow paths, but Batch and Slurm/HPC execution remain unverified. Variant-store, analytics, governance, lineage and MCP behavior are local reference implementations using runtime-generated synthetic data, not deployed Delta, notebook, SQL warehouse, dashboard, Purview, or network MCP services.

| State | Meaning for a customer conversation |
|---|---|
| Demonstrated | You can show it working |
| Partially demonstrated | Show only the evidenced part; describe the rest as intent |
| **Specified only** | Describe as architectural intent. Do not imply working software. |

See the [capability coverage table](docs/coverage.md) for all ten statuses, evidence, limitations, and presenter guidance. Historical cloud acceptance is evidence only for the checks recorded in the repository. A tagged resource group, `rg-genomics-20260919`, exists in `eastus2` as of September 20, 2026, with its verification VM deallocated. The private storage, Data Factory, account-native lifecycle policy, managed identities, and ACR deployments succeeded, and the in-network acceptance script passed its storage checks. An unchanged deployment now produces a fail-closed normalized ARM what-if report with no effective changes. A synthetic lifecycle object still reports tier `Hot`, so its service-driven transition, the private governed query endpoint, and the full end-to-end environment remain incomplete. Local evidence includes the [landing inventory](docs/landing-inventory.md), [metadata model](docs/metadata-store.md), staging log, reference publisher, [secondary-analysis pipeline](docs/secondary-pipeline.md), [analytics harness](docs/analytics-query.md), [MCP facade](docs/mcp-server.md), [instrumented KPI collector](docs/accelerator-kpis.md), data-hygiene tests, and [reference submission gate](docs/reference-submission.md). The task 4.3 gate is a local workflow-submission integration with a synthetic allocator and published-reference abstraction; it is not a deployed cloud pipeline.

## Prerequisites

For local validation, use PowerShell 7.2+, Python 3.10+ and Git; no Azure
account is needed. The machine-checkable preflight also accepts a local JSON
subscription snapshot so its failure reporting can be tested without contacting
Azure. See the [local commands](infra/README.md#run-locally) and
`scripts\Test-DemoPreflight.ps1`.
The [local write smoke test](infra/README.md#local-write-smoke-test) verifies
synthetic write integrity and cleanup without using Azure or SMB.

The preflight checks the following. Snapshot mode is locally verifiable; live
Azure values remain subscription-dependent and must be checked immediately
before a billable deployment. `Deploy-Accelerator.ps1` refuses to perform any
resource lookup or deployment when the required Azure preflight fails.

- An Azure subscription you can create resources in, with the roles needed to assign RBAC and create federated credentials
- Quota for the Batch or HPC pool sizing you intend to run
- A region offering every component in the architecture above
- Azure CLI, Bicep, Git, PowerShell, Python, and a Delta-capable engine (Microsoft Fabric or Azure Databricks)
- A GitHub account for forking

## Cost

The [dated `eastus2` foundation-cost estimate](docs/cost-estimate.md) derives
the current minimum modeled delivery cost (**$0.141**) and idle cost
(**$0.601/day**) from the Bicep defaults and Microsoft retail price meters.
It also states its material exclusions: private endpoints are not yet
meter-resolved, while payload, operations, data transfer, processing,
analytics, and alternate compute are not sized. Refresh and approve an
environment-specific estimate before provisioning; these figures are not a
quote or a full-architecture cost.

## Data

Demo data must be **synthetic or authorized public sample data**. The
[metadata-only demo manifest](docs/demo-dataset.md) references the Illumina
Platinum Genomes `2017-1.0` collection in Azure Open Datasets and binds it only
to generated subject, sample, and cohort identifiers. The manifest contains no
genomic payload or real patient-identifiable metadata; landing-zone seeding
remains pending.

The repository itself must never hold genomic data. The data-hygiene workflow rejects genomic file extensions and Git blobs over 1 MiB. It is a required merge gate on `main`; forks must repeat the [administrator setup and acceptance checks](CONTRIBUTING.md#administrator-setup-and-acceptance). This does not prevent publication to unprotected branches or forks.

## Reuse

Clone it to review the specifications and the partial implementation. The
storage/staging foundation is not a complete or turnkey deployment, and there is
no runnable end-to-end demo. See [docs/limitations.md](docs/limitations.md) for
the current constraints and [docs/demo-runbook.md](docs/demo-runbook.md) for the
planned delivery flow.

## Support

This demo accelerator has no support commitment or SLA and is not a supported
Microsoft offering. See [SUPPORT.md](SUPPORT.md) for support expectations and
the defect-reporting route.

## License

[MIT](LICENSE). Demo variant content comes from Illumina Platinum Genomes via Azure Open Datasets under its own terms; the MIT grant covers this repository's specs, documentation, and code.
