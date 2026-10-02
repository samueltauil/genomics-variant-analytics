# Genomics Variant Analytics Accelerator

**What would it take to move from a lab's existing file drop to traceable, cohort-level variant queries?** This repository gives solution engineers a place to explore that architecture, run its synthetic components, and see exactly which parts have been tested.

It connects familiar Azure patterns for genomic landing, object storage, secondary analysis, governance, and analytics. Start locally in minutes, with no Azure subscription or genomic files. Move to cloud work only when the environment, budget, and acceptance plan are approved.

> This is a demo solution accelerator and reference architecture built from validated patterns. It is not a released Microsoft blueprint or supported product. The full path has not been accepted end to end.

## Try the local demo

Requirements: Git, Python 3.10+, and PowerShell 7.2+. For a fresh checkout:

```powershell
git clone https://github.com/samueltauil/genomics-variant-analytics.git
Set-Location genomics-variant-analytics
```

From the repository root, run a synthetic secondary-analysis job:

```powershell
$demo = Join-Path $env:TEMP ("genomics-demo-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $demo | Out-Null

python -m scripts.run_secondary_pipeline `
  --run-id SYN-README-DEMO-001 `
  --work-dir (Join-Path $demo 'work') `
  --publish-dir (Join-Path $demo 'published') `
  --provenance-db (Join-Path $demo 'run-history.sqlite3') `
  --reference-build SYN-demo-genome `
  --reference-version synthetic-1385e2e921c4 `
  --reference-manifest-sha256 7e3be36672095e4018dfded5466ddb002848387e19d314595cb1a128a231be83
```

The successful JSON report includes the generated run's outputs and provenance. The reference build, immutable version, and digest are explicit by design. This tiny pipeline uses demonstration alignment and variant-calling logic, so its output is not biologically validated. The run does not deploy or contact Azure.

For a guided 20-minute walkthrough of landing metadata, run provenance, failure handling, and reset, follow the [solution engineer execution guide](docs/solution-engineer-guide.md).

## What you can explore

| Area | What is in the repository |
|---|---|
| Genomic landing and staging | Inventory and completeness checks, transfer integrity, and Azure Files to object-storage patterns |
| Secondary analysis | A synthetic local pipeline, Nextflow workflow, and Batch and Slurm execution paths |
| Variant data | A local SQLite harness for the exact 20-field Bronze contract, with rejection and provenance handling |
| Governance and analytics | Synthetic access controls, lineage, query and view models, and exploratory AI-assisted analysis |
| Engineering controls | Reference compatibility checks, data-hygiene gates, supply-chain evidence, and demo safeguards |

The local landing and secondary-analysis commands are separate component demonstrations. They do not form a connected ingest-to-query flow. The local variant store and analytics use SQLite; they are not a deployed Delta table, notebook workspace, SQL endpoint, dashboard, or governed AI service.

## Target architecture

```text
Lab file landing → object storage → secondary analysis → VCF/variant store
                                                ↓
                              governed cohort queries and exploration
```

The target keeps the lab's existing file-transfer workflow in view while making each later step traceable to its source, pipeline, and reference. Every run must name a compatible reference build and immutable version or manifest digest. Demo identities are synthetic, and genomic payloads do not belong in Git.

## Evidence, not promises

The [coverage table](docs/coverage.md) tracks what has runnable evidence and what remains incomplete. It currently rates all ten capability areas as **partially demonstrated**. The repository records component-specific local tests and selected Azure acceptance evidence, including storage and staging behavior, Azure Batch execution, and a private governed-query path. That evidence does not establish a single end-to-end deployment.

The revised private Slurm/AMLFS image and campaign path has local tests and compiled infrastructure, but it has not passed live campaign acceptance. No validated gallery image is claimed. The local Delta, governance, and analytics harnesses also remain distinct from deployed production services.

## Use this before a customer demo

1. Follow the [solution engineer guide](docs/solution-engineer-guide.md) for the no-Azure walkthrough.
2. Check [coverage](docs/coverage.md) and the [claim register](docs/claim-register.md) before describing capabilities.
3. For approved cloud work, review the [full demo runbook](docs/demo-runbook.md), [limitations](docs/limitations.md), [cost estimate](docs/cost-estimate.md), and [infrastructure guide](infra/README.md).

Describe governance as configurable controls, not a compliance outcome. Describe AI-assisted analysis as exploratory, not clinical decision support. Do not imply an unverified customer deployment.

## Project references

- [Architecture and design](openspec/changes/add-genomics-variant-accelerator/design.md)
- [OpenSpec contracts and tasks](openspec/changes/add-genomics-variant-accelerator/)
- [Secondary-analysis pipeline](docs/secondary-pipeline.md)
- [Variant-store guide](docs/variant-store.md)
- [Support and defect reporting](SUPPORT.md)
- [License](LICENSE)

The repository code and documentation use the MIT License. Any external sample-data source has its own terms; see the [metadata-only dataset manifest guide](docs/demo-dataset.md).
