# Genomics Variant Analytics Accelerator

A project knowledge base for the proposed path from an unchanged laboratory SMB workflow to a governed, queryable Delta variant store on Azure.

**Status as of 2026-09-10:** repository guardrails are implemented and live-tested. The local infrastructure validator, write smoke test, scheduled inventory, completeness checks, reference-submission gate and metadata lineage model are committed and pushed through [development commit 4900f26](https://github.com/samueltauil/genomics-variant-analytics/tree/4900f26), under [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12). They pass synthetic tests but are not merged into `main`. The Azure platform is not deployed and there is no runnable end-to-end demo.

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
- Local-only preparation validates a 12-group candidate asset inventory; no IaC templates or deployment command exist.
- A bounded local write harness verifies SHA-256 read-back and scratch cleanup, without claiming SMB performance or IOPS acceptance.
- Tasks 2.1 and 2.2's scheduled local scanner persists run/sample identifiers, sizes, first-observed arrivals and states, with two-poll size/mtime stability or optional fresh vendor markers determining completeness. Changes revoke completeness; interrupted-transfer/retry logic is still pending.
- A local reference-submission gate checks exact workflow/build/annotation versions and rejects incompatible pairings before an allocator callback. Actual Nextflow integration and published references remain pending under task 4.3.
- A local SQLite metadata model traverses the full lineage chain, rejects missing parents, requires file URI/stage/producer/integrity fields, and archives metadata without breaking variant references (6.1 through 6.4). Its 21 tests cover persistence, legacy backfill and concurrent snapshots. Access grants and actual pipeline/storage integration remain pending; see [Data Model and Provenance](Data-Model-and-Provenance#local-metadata-implementation).

[PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12) carries the local implementation. The development record has **8/89 completed tasks** (1.1, 1.2, 2.1, 2.2 and 6.1 through 6.4), with **84 local tests passing**. Task 1.1's historical evidence predates the authorized solo-maintainer policy. Default-branch records remain stale until merge; all cloud acceptance remains unverified.

Azure authentication, account discovery, provisioning, uploads and live benchmarks are paused. No Azure resources were created by this implementation; any existing subscription charges are unknown. A numeric spending limit and approved, sized plan are required before billable deployment. See the [Development Guide](Development-Guide#local-only-implementation) for commands and publication limits.

## Sources of Truth

This wiki explains the project; it does not replace its reviewed specifications or acceptance records. Behavior contracts live in the [OpenSpec change](https://github.com/samueltauil/genomics-variant-analytics/tree/main/openspec/changes/add-genomics-variant-accelerator), implementation lives in Git, and claims are bounded by the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md).

Start with the [README](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md), [design](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/design.md), and [task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md). When a wiki statement and a source disagree, inspect the linked change and its verification evidence before repeating the claim.

Never upload biological datasets, patient-identifiable content, credentials, or environment-specific identifiers to the repository or wiki. Even openly licensed genomic data stays outside Git.