# Genomics Variant Analytics Accelerator

A project knowledge base for the proposed path from an unchanged laboratory SMB workflow to a governed, queryable Delta variant store on Azure.

**Status as of 2026-09-11:** repository guardrails are implemented and live-tested. A disposable Azure environment is now deployed and verified in a sandbox subscription: workload identities, an SSD provisioned v2 SMB landing share, an HNS-enabled ADLS account, a private network with private endpoints, and a Data Factory staging pipeline. Ingestion, staging and the first Files-to-object-storage hop have measured acceptance evidence. Processing, the Delta store, governed analytics and demo enablement remain specified only, so there is still no runnable end-to-end demo.

This is a reference architecture and demo accelerator, not a released Microsoft blueprint, a supported product, or a clinical decision system. No compliance certification or confirmed customer deployment is claimed.

## Start Here

| Page | What it covers |
|---|---|
| [Architecture](Architecture) | Planned data flow, component responsibilities, and key design decisions |
| [Data Model and Provenance](Data-Model-and-Provenance) | Variant fields, identifiers, reference builds, and traceability |
| [Development Guide](Development-Guide) | Local checks, OpenSpec workflow, and maintaining this wiki |
| [Repository Guardrails](Repository-Guardrails) | Installed controls, live acceptance evidence, and known enforcement gaps |
| [Demo Readiness and Limitations](Demo-Readiness-and-Limitations) | What can be demonstrated, open decisions, and claims to avoid |

## What Works Today

- A Python/Git checker rejects genomic filename extensions, Git blobs over 1 MiB, and uninspectable submodules.
- A trusted GitHub workflow inspects proposed Git objects without executing proposed code and posts the required `data-hygiene` status on the PR head.
- Required checks remain enforced. The maintainer authorized zero required approvals for solo development; historical independent-review/direct-push rejection evidence describes the earlier policy.
- Secret scanning and push protection are enabled; a never-issued credential-pattern push was rejected before advancing the remote branch.
- Local-only preparation validates a 12-group candidate asset inventory, and parameterized Bicep now deploys the storage, identity and network foundation from a single idempotent entry point.
- The SMB landing share is SSD provisioned v2 with Multichannel enabled. A 100 GiB sequential write sustained **240 MiB/s** against a provisioned 200 MiB/s ceiling, mounted with a managed identity and no storage account key (task 1.3).
- The object-storage taxonomy exists as twelve directories, writable by the staging identity and refused to the processing identity, which is also refused a landing-share listing (tasks 1.4, 2.4).
- A Data Factory Copy pipeline stages only files the inventory reports complete; a file still growing between two observations was skipped (task 3.1). Every staged artifact is then checksum-verified, and a deliberately corrupted destination is marked failed and withheld from downstream processing (tasks 3.2, 3.3).
- Tasks 2.1 and 2.2's scheduled scanner persists run/sample identifiers, sizes, first-observed arrivals and states, with two-poll size/mtime stability or optional fresh vendor markers determining completeness. The same rule now runs over both a local directory and the Azure Files share. Interrupted-transfer/retry logic is still pending.
- A local reference-submission gate checks exact workflow/build/annotation versions and rejects incompatible pairings before an allocator callback. Actual Nextflow integration and published references remain pending under task 4.3.
- A local SQLite metadata model traverses the full lineage chain, rejects missing parents, requires file URI/stage/producer/integrity fields, and archives metadata without breaking variant references (6.1 through 6.4). Its 21 tests cover persistence, legacy backfill and concurrent snapshots. Access grants and actual pipeline/storage integration remain pending; see [Data Model and Provenance](Data-Model-and-Provenance#local-metadata-implementation).

- Five real reference versions are published into a write-once zone laid out as `type/name/version`, each with a per-artifact checksum manifest. A direct overwrite is rejected by storage, and a successor version leaves the prior one retrievable (tasks 4.1, 4.2).

The development record has **16/89 completed tasks**, with **101 local tests passing**. Task 1.1's historical evidence predates the authorized solo-maintainer policy.

The deployed environment is disposable and billable: the provisioned share charges on capacity, IOPS and throughput whether or not it is used, and the verification client and Data Factory runtime charge while running. Tear it down when finished. Deployment is verified only in one sandbox subscription whose policies shaped the result; see [Architecture](Architecture#deployed-environment-and-platform-constraints).

## Sources of Truth

This wiki explains the project; it does not replace its reviewed specifications or acceptance records. Behavior contracts live in the [OpenSpec change](https://github.com/samueltauil/genomics-variant-analytics/tree/main/openspec/changes/add-genomics-variant-accelerator), implementation lives in Git, and claims are bounded by the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md).

Start with the [README](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md), [design](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/design.md), and [task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md). When a wiki statement and a source disagree, inspect the linked change and its verification evidence before repeating the claim.

Never upload biological datasets, patient-identifiable content, credentials, or environment-specific identifiers to the repository or wiki. Even openly licensed genomic data stays outside Git.