# Demo Readiness and Limitations

**There is still no accepted live seven-step end-to-end demo as of 2026-09-29.** Repository guardrails, ingestion, staging, reference publication, Azure Batch secondary analysis, the Delta variant store, metadata lineage, governance, analytics/visualization, and the engineering-platform controls all have local synthetic or measured-cloud acceptance evidence. OIDC-backed ACR publication and registry-hosted provenance/SBOM verification are live. Slurm/AMLFS live campaign acceptance, executor concordance, and the live seven-step presentation remain open.

## Readiness

| Area | State |
|---|---|
| Data-hygiene checker and trusted workflow | Implemented and live-tested; a deterministic automated PR reviewer and a scheduled failure-triage adapter are also implemented and live-accepted |
| Branch checks and PR rule | Retained; zero required approvals now authorized for solo development; historical direct-push rejection evidence no longer describes the current guarantee |
| Secret push protection | Enabled; never-issued credential-pattern push rejected. Evidence merged in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12). A repository-wide secret scanner also runs in the required hygiene check and reports zero embedded credentials |
| Candidate asset inventory and validator | Implemented locally; parameterized Bicep deploys the storage, identity and network foundation |
| SMB landing zone (1.3) | Deployed SSD provisioned v2 with Multichannel; 100 GiB write sustained 240 MiB/s against a 200 MiB/s provisioned ceiling, mounted by managed identity with no account key |
| Object-storage taxonomy and least privilege (1.4, 2.4) | Twelve directories exist; staging identity writes, processing identity refused write and refused a landing-share listing |
| Scheduled landing inventory, completeness, and failure/retry (2.1, 2.2, 2.3) | Local tests pass; the same rule runs over a local directory and the Azure Files share; failure detection and retry require an authoritative transfer manifest and failure marker; no instrument or SMB transfer was exercised |
| Staging to object storage (3.1-3.5) | Data Factory Copy over private endpoints stages only complete files; a growing file was skipped. Checksums are compared and a corrupted destination is marked failed and withheld; the staging record carries all six required fields. Account-native lifecycle tiering moved the synthetic acceptance object from `Hot` to `Cool` while its private URI and lineage source link still resolved. Private Purview lineage push succeeded and the staged asset was cataloged, but the Purview lineage graph exposed zero source-to-sink relations; repository staging records remain authoritative. |
| Reference publication, immutability, and compatibility gate (4.1-4.4) | Five pinned Ensembl versions published with per-artifact checksum manifests; overwrite rejected by container-level WORM and by the publisher; successor version leaves the prior retrievable. The submission-time compatibility gate rejects an incompatible workflow/reference pairing before allocation, and publish/read operations are audited. Cloud-side audit retention on the Azure client drivers is not claimed |
| Secondary-analysis pipeline (5.1, 5.2, 5.5, 5.6, 5.7) | A local synthetic Nextflow pipeline runs quality control through variant calling, producing both BAM/CRAM and VCF/GVCF outputs, with run provenance and stage-level failure handling. Azure Batch completed a live managed-identity run with no embedded storage key or connection string, and a concurrent burst scaled to two nodes before returning to zero. The Slurm/AMLFS path is implemented with managed-identity AzCopy/SDK stage-in and copy-out and a private Trusted Launch Compute Gallery image path, but the required live single-campaign acceptance (5.3) and Batch-vs-Slurm concordance (5.4) remain open. |
| Metadata lineage, file details, integrity, archival, and clinical/research grants (6.1 through 6.5) | Local synthetic tests pass; a research-only principal reads research attributes with no clinical attribute or subject identifier returned. Actual pipeline/storage integration and Delta/Purview integration remain absent |
| Delta variant store (7.1-7.10) | A local SQLite Bronze harness implements the exact 20-field contract, VCF parsing, mandatory-field rejection, null annotations, provenance, rejected-record capture, idempotency, and inspectable layout/maintenance metadata. It is not a deployed Delta table, OneLake shortcut, or production layout/performance result |
| Governance (8.1-8.9) | Local implementation of four access tiers, de-identified projection, research/clinical workspace separation, classification labelling, a hash-chained tamper-evident audit trail, an external-sharing approval gate, and lineage assembly across variant, metadata, and staging records. Live private-endpoint-only evidence covers ingestion, staging, processing, and a private governed query path that returned de-identified synthetic results and denied subject linkage. Purview supplies supplementary catalog context only. |
| Analytics, visualization, and AI-assisted exploration (9.1-9.7, 10.7, 10.8) | A local governed analytics harness answers all six query scenarios through equivalent notebook-style and SQL-adapter surfaces with per-row traceability, snapshot reruns, six view models, and measured local response time. An in-process MCP facade fronts the same engine with server-side tier enforcement and audit logging. No deployed notebook workspace, SQL warehouse, dashboard, or network-reachable MCP endpoint exists |
| Engineering platform (10.1-10.11) | Immutable release `v0.2.1-pipeline` authenticated to Azure through OIDC, pushed its image to the admin-disabled ACR, and published verified registry-backed SLSA provenance and CycloneDX SBOM attestations. A stored synthetic variant resolves through the release and image digest to the signed tool versions. Attestation is enforced in the submission path; repository AI context, automated PR review, scheduled triage, and account-tier substitutes are also implemented. The `clinical` and `research` environments are configured with branch-deployment refusal and self-approval refusal verified; a distinct-reviewer approved deployment remains a production consideration for this solo-maintainer accelerator. |
| Preflight, reset, teardown, and cost measurements | Local snapshot preflight and named-store reset diagnostics are implemented and tested. The earlier environment was torn down on 2026-09-18; the fresh tagged foundation reached its documented ready state and has a dated size-based cost statement. Complete-environment no-effective-change reporting is live-verified after fail-closed normalization. |

The development task record is **86/89 completed**. Remaining open tasks are Slurm/AMLFS live campaign acceptance (5.3), Batch-vs-Slurm executor concordance (5.4), and the full seven-step demo run (12.1).

The 2026-09-10/11 disposable environment was billable while it ran and was removed on 2026-09-18. A separate resource group, `rg-genomics-20260919`, exists in `eastus2` with an October 3, 2026 expiry tag. Its verification VM is deallocated, but storage and networking resources remain billable. The private foundation, account-native lifecycle transition, ACR deployments, Azure Batch run, compute release to zero, and private governed query path succeeded. Slurm/AMLFS campaign acceptance and the full demo remain incomplete. Deployment has been exercised only in the current sandbox subscription, so regional availability, quota and policy differences should be expected elsewhere. The dated `eastus2` cost model covers the deployed foundation sizing; Managed Lustre campaign runtime, analytics capacity, payload processing, and actual cost per sample remain excluded.

The [demo runbook](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/demo-runbook.md) is executable for the documented local harnesses and diagnostics, and its first-reader dry run confirmed every local phase matched its documented observation on 2026-09-19. Do not present local, synthetic evidence or the resource group's presence as a fully governed environment.

## Demo Data Manifest

The repository now includes a metadata-only Illumina Platinum Genomes manifest
with generated subject, sample, and cohort identifiers. Its validator enforces
the documented synthetic patterns and rejects patient-identifying fields,
values, and source donor identifiers. No genomic payload is committed. Remote
download integrity and landing-zone staging are not verified; retain genomic
files in approved external storage and keep them out of Git and the wiki.

The hereditary-cancer scenario and query set are proposed demo choices. They are not evidence of a clinical use case or a validated clinical system.

## Constraints That Shape the Design

- Arrival discovery on the SMB share is scheduled scanning, with stability checks or completion markers. Do not present it as native Azure Files file-created Event Grid delivery.
- Identity-based SMB is the landing-zone contract, not a convenience. A governed subscription is likely to disable shared-key access, which removes NTLMv2 mounting entirely; plan for managed identity or a domain-joined client rather than a share key.
- Private endpoints should be assumed, not added later. Policy disabled public network access on both storage accounts, so every client and service had to sit inside the network from the first deployment.
- Data Factory Copy is the file-share staging mechanism. Do not show Storage Actions as a cross-service file-share mover.
- Purview is supplementary, best-effort catalog context in this design. The live Copy activity reported `reportLineageToPurview` as `Succeeded` and the staged ADLS asset was cataloged, but the Purview INPUT lineage graph showed zero relations. Authoritative lineage comes from repository staging records plus metadata and variant joins, not from a Purview backtrace.
- Batch/HPC equivalence is to be validated using variant concordance, not byte equality. The draft runbook's "identical outputs" shorthand must not be repeated as a guarantee.
- Delta rows are additional to retained VCF and other artifacts. Cost estimates must include both rather than imply that queryable rows replace file storage.
- GitHub visibility and account tier affect available controls. Forks must reassess protection settings; a repository clone does not activate them.

Exact service limits, regional availability, billing, and lifecycle dates must be checked against current official documentation when deployment is implemented. No throughput, cost, or query-performance target beyond the documented local measurements has been demonstrated by this project.

## Open Decisions

The reference deployment still needs an engine choice between Fabric and Databricks, an annotation strategy, measured sizing and cost, and validated physical table optimizations. These are implementation decisions to resolve through the specs, not choices this wiki silently makes.

Task 2.3 resolved its blocker by refusing to infer failure from stability: the sending run must declare an expected size per file in a transfer manifest, and only a file that contradicts or never reaches that declaration is failed. A run with no usable manifest is held at `arriving` rather than completed, so the contract fails closed. This is local synthetic evidence; no interrupted transfer has been observed from an instrument or over SMB, and the guarantee is bounded by the honesty of the declaration and by a deployment-specific stall deadline. Task 4.3's compatibility gate is implemented and locally tested against a synthetic allocator; a real pipeline integration is still outside the local task evidence.

Before billable deployment, supply a currency and numeric per-delivery/idle spending limit, approve region and sizing, and review a dated estimate. Azure Batch is validated for the demo path; HPC remains a separate open validation path and is not enabled together with Batch by default. No subscription spending cap or deployed budget control is claimed.

## Claims to Avoid

Do not describe the accelerator as a released Microsoft blueprint, supported product, compliance solution, or confirmed end-to-end customer deployment. Do not include unverified customer names. Assisted exploration is a governed, exploratory research aid, not diagnosis, pathogenicity determination, or clinical decision-making.

Before presenting, read the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md), check the current [coverage](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md#coverage), and resolve any open status updates using their linked acceptance evidence. Clearly distinguish a design diagram from demonstrated behavior.

## Sources

- [Known limitations and open questions](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/limitations.md)
- [Demo-enablement specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/platform/demo-enablement/spec.md)
- [Repository Guardrails](Repository-Guardrails)
