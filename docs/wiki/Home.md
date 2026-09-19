# Genomics Variant Analytics Accelerator

A project knowledge base for the path from an unchanged laboratory SMB workflow to a governed, queryable Delta variant store on Azure.

**Status as of 2026-09-19:** repository guardrails, ingestion, staging, reference publication, the secondary-analysis pipeline, the Delta variant store, metadata lineage, governance, analytics/visualization, AI-assisted exploration (MCP), and the engineering-platform controls all have local synthetic or measured-cloud evidence. The earlier disposable environment was torn down on 2026-09-18. A fresh tagged resource group, `rg-genomics-20260919`, now exists in `eastus2`; core resources exist and its verification VM is deallocated, but fresh object-storage and Storage Actions deployments failed and component acceptance is incomplete. Batch/Slurm execution, Managed Lustre scratch, OIDC deployment, ACR-hosted attestation, and the live seven-step end-to-end demo are still unverified or unimplemented, so there is still no runnable end-to-end demo.

This is a reference architecture and demo accelerator, not a released Microsoft blueprint, a supported product, or a clinical decision system. No compliance certification or confirmed customer deployment is claimed.

## Start Here

| Page | What it covers |
|---|---|
| [Architecture](Architecture) | Data flow, component responsibilities, and key design decisions |
| [Data Model and Provenance](Data-Model-and-Provenance) | Variant fields, identifiers, reference builds, and traceability |
| [Development Guide](Development-Guide) | Local checks, OpenSpec workflow, and maintaining this wiki |
| [Repository Guardrails](Repository-Guardrails) | Installed controls, live acceptance evidence, and known enforcement gaps |
| [Demo Readiness and Limitations](Demo-Readiness-and-Limitations) | What can be demonstrated, open decisions, and claims to avoid |

## What Works Today

- A Python/Git checker rejects genomic filename extensions, Git blobs over 1 MiB, and uninspectable submodules.
- A trusted GitHub workflow inspects proposed Git objects without executing proposed code and posts the required `data-hygiene` status on the PR head. A deterministic automated reviewer also flags workflow, container, manifest and schema drift, and a scheduled triage adapter opens or updates a pipeline-failure issue.
- Required checks remain enforced. The maintainer authorized zero required approvals for solo development; historical independent-review/direct-push rejection evidence describes the earlier policy.
- Secret scanning and push protection are enabled; a never-issued credential-pattern push was rejected before advancing the remote branch. A repository-wide secret scanner also runs in the required hygiene check and reports zero embedded credentials.
- The SMB landing share is SSD provisioned v2 with Multichannel enabled. A 100 GiB sequential write sustained **240 MiB/s** against a provisioned 200 MiB/s ceiling, mounted with a managed identity and no storage account key (task 1.3).
- The object-storage taxonomy exists as twelve directories, writable by the staging identity and refused to the processing identity, which is also refused a landing-share listing (tasks 1.4, 2.4).
- A Data Factory Copy pipeline stages only files the inventory reports complete; a file still growing between two observations was skipped (task 3.1). Every staged artifact is then checksum-verified, and a deliberately corrupted destination is marked failed and withheld from downstream processing (tasks 3.2, 3.3). Purview lineage and Storage Actions lifecycle tiering remain absent (tasks 3.4, 3.5).
- Tasks 2.1, 2.2 and 2.3's scheduled scanner persists run/sample identifiers, sizes, first-observed arrivals and states, with two-poll size/mtime stability or optional fresh vendor markers determining completeness. Interrupted transfers are classified against a run-declared expected-size manifest and a stall deadline, and a re-send revises the failed record in place without disturbing siblings. The same rules run over both a local directory and the Azure Files share; no instrument or SMB transfer has been exercised.
- A local reference-submission gate checks explicit workflow/build/annotation versions, resolves immutable published manifests, and rejects incompatible pairings before an allocator callback. A local synthetic Nextflow pipeline (task 5.1) runs quality control through variant calling and produces both BAM/CRAM and VCF/GVCF outputs; Azure Batch and Slurm/HPC executor profiles and executor concordance remain unimplemented (tasks 5.2-5.4, 5.7).
- A local SQLite metadata model traverses the full lineage chain, rejects missing parents, requires file URI/stage/producer/integrity fields, and archives metadata without breaking variant references (6.1 through 6.4). Clinical and research attributes are now split behind separate local grants, and a research-only principal receives no clinical attribute (task 6.5). Twenty-five metadata-and-grant tests pass. This is a trusted local API, not a deployed or access-controlled service; see [Data Model and Provenance](Data-Model-and-Provenance#local-metadata-implementation).
- A local SQLite Bronze harness implements the exact 20-field variant-store contract (`scripts/variant_store.py`): VCF parsing, mandatory-field rejection, null-not-fabricated annotations, run/reference provenance, rejected-record capture, ingestion idempotency, and reprocessing separation. It is not a deployed Delta table or a production layout/performance result.
- Local governance implements four access tiers, de-identified query projection, classification labelling, an external-sharing approval gate, and a hash-chained tamper-evident audit trail covering pipeline runs, metadata access, reprocessing, and cross-workspace transfers (tasks 8.1-8.6, 8.8-8.9). Private-endpoint-only deployment (8.7) is not verified.
- A local governed analytics harness answers all six supported query scenarios with access-aware, traceable, snapshot-reproducible results across equivalent notebook-style and SQL-adapter surfaces, and an in-process MCP facade fronts the same governed engine with server-side access-tier enforcement, exploratory labelling, and audit logging (tasks 9.1-9.7, 10.7-10.8). No deployed notebook workspace, SQL warehouse, dashboard, or network-reachable MCP endpoint exists.
- Five real reference versions are published into a write-once zone laid out as `type/name/version`, each with a per-artifact checksum manifest. A direct overwrite is rejected by storage, and a successor version leaves the prior one retrievable (tasks 4.1, 4.2).

The development record has **71/89 completed tasks**, with the full local test suite passing **299 tests** (verified 2026-09-19). Task 1.1's historical evidence predates the authorized solo-maintainer policy.

The 2026-09-10/11 disposable environment was billable while it ran and was fully removed on 2026-09-18. A separate fresh deployment now exists in `rg-genomics-20260919` with an October 3, 2026 expiry tag. Its verification VM is deallocated, but storage and networking resources remain billable. Component-level and end-to-end acceptance are not established; see [Architecture](Architecture#deployed-environment-and-platform-constraints).

## Sources of Truth

This wiki explains the project; it does not replace its reviewed specifications or acceptance records. Behavior contracts live in the [OpenSpec change](https://github.com/samueltauil/genomics-variant-analytics/tree/main/openspec/changes/add-genomics-variant-accelerator), implementation lives in Git, and claims are bounded by the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md).

Start with the [README](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md), [design](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/design.md), and [task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md). When a wiki statement and a source disagree, inspect the linked change and its verification evidence before repeating the claim.

Never upload biological datasets, patient-identifiable content, credentials, or environment-specific identifiers to the repository or wiki. Even openly licensed genomic data stays outside Git.
