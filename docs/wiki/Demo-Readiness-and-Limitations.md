# Demo Readiness and Limitations

**There is still no runnable end-to-end demo as of 2026-09-11.** Repository guardrails have live acceptance evidence, and ingestion, object-storage layout and the first staging hop are now deployed and measured in a disposable sandbox environment. Processing pipelines, variant tables, notebooks, visualizations, governance tiers and delivery automation remain specified only.

## Readiness

| Area | State |
|---|---|
| Data-hygiene checker and trusted workflow | Implemented and live-tested |
| Branch checks and PR rule | Retained; zero required approvals now authorized for solo development; historical direct-push rejection evidence no longer describes the current guarantee |
| Secret push protection | Enabled; never-issued credential-pattern push rejected, evidence in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12) awaiting review |
| Candidate asset inventory and validator | Implemented locally; parameterized Bicep now deploys the storage, identity and network foundation |
| SMB landing zone (1.3) | Deployed SSD provisioned v2 with Multichannel; 100 GiB write sustained 240 MiB/s against a 200 MiB/s provisioned ceiling, mounted by managed identity with no account key |
| Object-storage taxonomy and least privilege (1.4, 2.4) | Twelve directories exist; staging identity writes, processing identity refused write and refused a landing-share listing |
| Scheduled landing inventory and completeness (2.1, 2.2) | 21 local tests pass; the same rule runs over a local directory and the Azure Files share; failure/retry pending |
| Staging to object storage (3.1, 3.2, 3.3) | Data Factory Copy over private endpoints stages only complete files; a growing file was skipped. Checksums are compared and a corrupted destination is marked failed and withheld; the staging record carries all six required fields. Purview lineage and lifecycle tiering pending |
| Reference-submission gate (4.3 preparation) | 12 local tests pass; real workflow and published reference inventory integration pending |
| Metadata lineage, file details, integrity and archival (6.1 through 6.4) | 21 synthetic local tests pass; access grants and actual pipeline/storage integration pending |
| Nextflow, Batch, and Slurm processing | Specified only |
| Reference data and Delta store | Specified only |
| Access tiers, catalog integration, and analytics | Specified only |
| Preflight, reset, teardown, and cost measurements | Teardown script exists and is tag-guarded; preflight, reset and cost measurement not implemented |

The development task record is **14/89 completed**, including historical guardrail acceptance, and all **92 local tests pass**.

The deployed environment is disposable and billable. The provisioned share charges on capacity, IOPS and throughput whether or not it is used; the verification client and Data Factory integration runtime charge while running. Deployment has been exercised in exactly one sandbox subscription, so regional availability, quota and policy differences should be expected elsewhere. No cost per delivery or per sample has been measured.

The [demo runbook](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/demo-runbook.md) is a draft outline, not executable delivery instructions. Its planned phases are bring-up, seeding, presentation, rehearsed failures, reset, and teardown. Do not attempt a customer delivery from it.

## Planned Demo Data

The design proposes Illumina Platinum Genomes via Azure Open Datasets for variant content, with generated subject, sample, and cohort identifiers. Dataset assembly and staging are not verified. Open licensing does not authorize placing genomic files in this Git repository or wiki; retain datasets in the approved external storage location and track manifests separately.

The hereditary-cancer scenario and query set are proposed demo choices. They are not evidence of a clinical use case or a validated clinical system.

## Constraints That Shape the Design

- Arrival discovery on the SMB share is planned as scheduled scanning, with stability checks or completion markers. Do not present it as native Azure Files file-created Event Grid delivery.
- Identity-based SMB is the landing-zone contract, not a convenience. A governed subscription is likely to disable shared-key access, which removes NTLMv2 mounting entirely; plan for managed identity or a domain-joined client rather than a share key.
- Private endpoints should be assumed, not added later. Policy disabled public network access on both storage accounts, so every client and service had to sit inside the network from the first deployment.
- Data Factory Copy is the planned file-share staging mechanism. Do not show Storage Actions as a cross-service file-share mover.
- Purview is a coarse-grained catalog and lineage surface in this design. Variant-level traceability comes from record fields and the metadata model.
- Batch/HPC equivalence is to be validated using variant concordance, not byte equality. The draft runbook's "identical outputs" shorthand must not be repeated as a guarantee.
- Delta rows are additional to retained VCF and other artifacts. Cost estimates must include both rather than imply that queryable rows replace file storage.
- GitHub visibility and account tier affect available controls. Forks must reassess protection settings; a repository clone does not activate them.

Exact service limits, regional availability, billing, and lifecycle dates must be checked against current official documentation when deployment is implemented. No throughput, cost, or query-performance target has been demonstrated by this project.

## Open Decisions

The reference deployment still needs an engine choice between Fabric and Databricks, an annotation strategy, measured sizing and cost, and validated physical table optimizations. These are implementation decisions to resolve through the specs, not choices this wiki silently makes.

Task 2.3 is blocked on transfer-failure evidence: two unchanged polls cannot distinguish a completed file from a paused or truncated write. A trusted expected-size/checksum manifest or vendor status/timeout contract is needed before failure and retry behavior can be completed. The new task 4.3 gate also needs reviewed compatibility declarations, a published reference inventory and a real pipeline integration. Synthetic hashes are not reference publication evidence.

Before billable deployment, supply a currency and numeric per-delivery/idle spending limit, approve region and sizing, and review a dated estimate. Both Batch and HPC remain alternative planned paths, not services enabled together by default. No subscription spending cap or deployed budget control is claimed.

## Claims to Avoid

Do not describe the accelerator as a released Microsoft blueprint, supported product, compliance solution, or confirmed end-to-end customer deployment. Do not include unverified customer names. Assisted exploration is a proposed research aid, not diagnosis, pathogenicity determination, or clinical decision-making.

Before presenting, read the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md), check the current [coverage](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md#coverage), and resolve any pending status updates using their linked acceptance evidence. Clearly distinguish a design diagram from demonstrated behavior.

## Sources

- [Known limitations and open questions](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/limitations.md)
- [Demo-enablement specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/platform/demo-enablement/spec.md)
- [Repository Guardrails](Repository-Guardrails)