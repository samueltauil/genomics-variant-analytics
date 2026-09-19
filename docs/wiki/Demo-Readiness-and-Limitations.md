# Demo Readiness and Limitations

**There is still no runnable end-to-end demo as of 2026-09-19.** Repository guardrails, ingestion, staging, reference publication, the secondary-analysis pipeline, the Delta variant store, metadata lineage, governance, analytics/visualization, and the engineering-platform controls all have local synthetic or measured-cloud acceptance evidence. Batch/Slurm execution, Managed Lustre scratch, private-endpoint-only deployment, Azure OIDC deployment, ACR-hosted attestation, and the live seven-step presentation remain unverified or unimplemented.

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
| Staging to object storage (3.1, 3.2, 3.3) | Data Factory Copy over private endpoints stages only complete files; a growing file was skipped. Checksums are compared and a corrupted destination is marked failed and withheld; the staging record carries all six required fields. Purview lineage (3.4) and Storage Actions lifecycle tiering (3.5) remain absent |
| Reference publication, immutability, and compatibility gate (4.1-4.4) | Five pinned Ensembl versions published with per-artifact checksum manifests; overwrite rejected by container-level WORM and by the publisher; successor version leaves the prior retrievable. The submission-time compatibility gate rejects an incompatible workflow/reference pairing before allocation, and publish/read operations are audited. Cloud-side audit retention on the Azure client drivers is not claimed |
| Secondary-analysis pipeline (5.1, 5.5, 5.6) | A local synthetic Nextflow pipeline runs quality control through variant calling, producing both BAM/CRAM and VCF/GVCF outputs, with run provenance and stage-level failure handling. Azure Batch and Slurm/HPC executor profiles, executor concordance, and compute-release verification (5.2-5.4, 5.7) remain unimplemented |
| Metadata lineage, file details, integrity, archival, and clinical/research grants (6.1 through 6.5) | Local synthetic tests pass; a research-only principal reads research attributes with no clinical attribute or subject identifier returned. Actual pipeline/storage integration and Delta/Purview integration remain absent |
| Delta variant store (7.1-7.10) | A local SQLite Bronze harness implements the exact 20-field contract, VCF parsing, mandatory-field rejection, null annotations, provenance, rejected-record capture, idempotency, and inspectable layout/maintenance metadata. It is not a deployed Delta table, OneLake shortcut, or production layout/performance result |
| Governance (8.1-8.6, 8.8, 8.9) | Local implementation of four access tiers, de-identified projection, research/clinical workspace separation, classification labelling, a hash-chained tamper-evident audit trail, an external-sharing approval gate, and lineage assembly across variant, metadata, and staging records. Private-endpoint-only deployment (8.7) is unverified |
| Analytics, visualization, and AI-assisted exploration (9.1-9.7, 10.7, 10.8) | A local governed analytics harness answers all six query scenarios through equivalent notebook-style and SQL-adapter surfaces with per-row traceability, snapshot reruns, six view models, and measured local response time. An in-process MCP facade fronts the same engine with server-side tier enforcement and audit logging. No deployed notebook workspace, SQL warehouse, dashboard, or network-reachable MCP endpoint exists |
| Engineering platform (10.3, 10.6, 10.7, 10.9-10.11) | Immutable release `v0.1.0-pipeline` published with a verified attestation; attestation is enforced in the submission path; repository AI context (instructions, prompts, skill) is authored; automated PR review and scheduled triage are implemented and live-accepted; account-tier substitutes are documented. The `clinical` and `research` environments are configured, but independent-review and approved-deployment evidence is absent. Azure OIDC and ACR-hosted build/SBOM attestation (10.1, 10.2, 10.4, 10.5) remain partial or blocked |
| Preflight, reset, teardown, and cost measurements | Local snapshot preflight and named-store reset diagnostics are implemented and tested. The earlier environment was torn down on 2026-09-18; a fresh tagged resource group now exists, but fresh-deployment acceptance, idempotency, teardown verification, and numeric billed cost remain unverified |

The development task record is **71/89 completed**, including historical guardrail acceptance, and the full local test suite passes **299 tests** (verified 2026-09-19). Remaining open tasks are Purview lineage and lifecycle tiering (3.4, 3.5), Batch/Slurm/Lustre execution and concordance (5.2-5.4, 5.7), private-endpoint-only deployment (8.7), Azure OIDC, independently approved environment deployment, and ACR-hosted attestation (10.1, 10.2, 10.4, 10.5), demo parameterization/idempotency/cost/bring-up documentation (11.3-11.7), and the full seven-step demo run plus end-to-end release trace (12.1, 12.3).

The 2026-09-10/11 disposable environment was billable while it ran and was removed on 2026-09-18. A separate fresh resource group, `rg-genomics-20260919`, now exists in `eastus2` with an October 3, 2026 expiry tag. Its verification VM is deallocated, but storage and networking resources remain billable. Fresh object-storage and Storage Actions deployments failed, so its presence does not establish component acceptance or a runnable demo. Deployment has been exercised only in the current sandbox subscription, so regional availability, quota and policy differences should be expected elsewhere. No cost per delivery or per sample has been measured; a dated `eastus2` cost model exists for share, VM, and disk sizing only.

The [demo runbook](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/demo-runbook.md) is executable for the documented local harnesses and diagnostics, and its first-reader dry run confirms every local phase matches its documented observation as of 2026-09-19. Its live cloud bring-up and teardown phases are not yet accepted against the fresh resource group. Do not present local, synthetic evidence or the resource group's presence as a fully governed environment.

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
- Purview is a coarse-grained catalog and lineage surface in this design; the current lineage assembly (task 8.9) is a local join over variant, metadata, and staging records with Purview explicitly simulated (`live: false`). Variant-level traceability comes from record fields and the metadata model.
- Batch/HPC equivalence is to be validated using variant concordance, not byte equality. The draft runbook's "identical outputs" shorthand must not be repeated as a guarantee.
- Delta rows are additional to retained VCF and other artifacts. Cost estimates must include both rather than imply that queryable rows replace file storage.
- GitHub visibility and account tier affect available controls. Forks must reassess protection settings; a repository clone does not activate them.

Exact service limits, regional availability, billing, and lifecycle dates must be checked against current official documentation when deployment is implemented. No throughput, cost, or query-performance target beyond the documented local measurements has been demonstrated by this project.

## Open Decisions

The reference deployment still needs an engine choice between Fabric and Databricks, an annotation strategy, measured sizing and cost, and validated physical table optimizations. These are implementation decisions to resolve through the specs, not choices this wiki silently makes.

Task 2.3 resolved its blocker by refusing to infer failure from stability: the sending run must declare an expected size per file in a transfer manifest, and only a file that contradicts or never reaches that declaration is failed. A run with no usable manifest is held at `arriving` rather than completed, so the contract fails closed. This is local synthetic evidence; no interrupted transfer has been observed from an instrument or over SMB, and the guarantee is bounded by the honesty of the declaration and by a deployment-specific stall deadline. Task 4.3's compatibility gate is implemented and locally tested against a synthetic allocator; a real pipeline integration is still outside the local task evidence.

Before billable deployment, supply a currency and numeric per-delivery/idle spending limit, approve region and sizing, and review a dated estimate. Both Batch and HPC remain alternative planned paths, not services enabled together by default. No subscription spending cap or deployed budget control is claimed.

## Claims to Avoid

Do not describe the accelerator as a released Microsoft blueprint, supported product, compliance solution, or confirmed end-to-end customer deployment. Do not include unverified customer names. Assisted exploration is a governed, exploratory research aid, not diagnosis, pathogenicity determination, or clinical decision-making.

Before presenting, read the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md), check the current [coverage](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md#coverage), and resolve any open status updates using their linked acceptance evidence. Clearly distinguish a design diagram from demonstrated behavior.

## Sources

- [Known limitations and open questions](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/limitations.md)
- [Demo-enablement specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/platform/demo-enablement/spec.md)
- [Repository Guardrails](Repository-Guardrails)
