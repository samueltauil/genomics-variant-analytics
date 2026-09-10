# Genomics Variant Analytics Accelerator

A project knowledge base for the proposed path from an unchanged laboratory SMB workflow to a governed, queryable Delta variant store on Azure.

**Status as of 2026-09-10:** repository guardrails are implemented and live-tested. Local infrastructure validation, a write smoke test, and scheduled landing inventory now pass synthetic tests in the author's working tree. That code is uncommitted and unavailable from `main`; this wiki update publishes documentation only. The Azure platform is not deployed and there is no runnable end-to-end demo.

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
- Synthetic tests, required checks, independent review, and administrator rejection probes verify the repository guardrails.
- Secret scanning and push protection are enabled; a never-issued credential-pattern push was rejected before advancing the remote branch.
- Local-only preparation validates a 12-group candidate asset inventory; no IaC templates or deployment command exist.
- A bounded local write harness verifies SHA-256 read-back and scratch cleanup, without claiming SMB performance or IOPS acceptance.
- Task 2.1's scheduled local scanner persists run/sample identifiers, sizes, first-observed arrival times and states. Files remain `arriving`; completeness and retry logic are still pending.

[PR #1](https://github.com/samueltauil/genomics-variant-analytics/pull/1) installed the guardrails. [PR #10](https://github.com/samueltauil/genomics-variant-analytics/pull/10) records task 1.1's acceptance; [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12) adds task 1.2's secret-protection evidence. Both await review as of the date above. The local task record now has **3/89 completed tasks** (1.1, 1.2 and 2.1), with **42 local tests passing**. Default-branch checkboxes and published code do not yet include all this evidence. All cloud acceptance remains unverified.

Azure authentication, account discovery, provisioning, uploads and live benchmarks are paused. Local validation does not authorize cloud operations. See the [Development Guide](Development-Guide#local-only-implementation) for commands and publication limits.

## Sources of Truth

This wiki explains the project; it does not replace its reviewed specifications or acceptance records. Behavior contracts live in the [OpenSpec change](https://github.com/samueltauil/genomics-variant-analytics/tree/main/openspec/changes/add-genomics-variant-accelerator), implementation lives in Git, and claims are bounded by the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md).

Start with the [README](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md), [design](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/design.md), and [task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md). When a wiki statement and a source disagree, inspect the linked change and its verification evidence before repeating the claim.

Never upload biological datasets, patient-identifiable content, credentials, or environment-specific identifiers to the repository or wiki. Even openly licensed genomic data stays outside Git.