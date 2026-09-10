# Demo Readiness and Limitations

**There is no runnable end-to-end demo as of 2026-09-10.** The current demonstration surface is repository guardrails and their synthetic tests. Storage, pipelines, variant tables, notebooks, visualizations, and deployment automation remain specified only.

## Readiness

| Area | State |
|---|---|
| Data-hygiene checker and trusted workflow | Implemented and live-tested |
| Branch checks, review, and rejection tests | Verified; acceptance documentation in PR #10 awaiting review |
| Secret push protection | Enabled; never-issued credential-pattern push rejected, evidence in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12) awaiting review |
| SMB landing zone and staging | Specified only |
| Nextflow, Batch, and Slurm processing | Specified only |
| Reference data, metadata, and Delta store | Specified only |
| Access tiers, catalog integration, and analytics | Specified only |
| Preflight, reset, teardown, and cost measurements | Not implemented or measured |

The [demo runbook](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/demo-runbook.md) is a draft outline, not executable delivery instructions. Its planned phases are bring-up, seeding, presentation, rehearsed failures, reset, and teardown. Do not attempt a customer delivery from it.

## Planned Demo Data

The design proposes Illumina Platinum Genomes via Azure Open Datasets for variant content, with generated subject, sample, and cohort identifiers. Dataset assembly and staging are not verified. Open licensing does not authorize placing genomic files in this Git repository or wiki; retain datasets in the approved external storage location and track manifests separately.

The hereditary-cancer scenario and query set are proposed demo choices. They are not evidence of a clinical use case or a validated clinical system.

## Constraints That Shape the Design

- Arrival discovery on the SMB share is planned as scheduled scanning, with stability checks or completion markers. Do not present it as native Azure Files file-created Event Grid delivery.
- Data Factory Copy is the planned file-share staging mechanism. Do not show Storage Actions as a cross-service file-share mover.
- Purview is a coarse-grained catalog and lineage surface in this design. Variant-level traceability comes from record fields and the metadata model.
- Batch/HPC equivalence is to be validated using variant concordance, not byte equality. The draft runbook's "identical outputs" shorthand must not be repeated as a guarantee.
- Delta rows are additional to retained VCF and other artifacts. Cost estimates must include both rather than imply that queryable rows replace file storage.
- GitHub visibility and account tier affect available controls. Forks must reassess protection settings; a repository clone does not activate them.

Exact service limits, regional availability, billing, and lifecycle dates must be checked against current official documentation when deployment is implemented. No throughput, cost, or query-performance target has been demonstrated by this project.

## Open Decisions

The reference deployment still needs an engine choice between Fabric and Databricks, an annotation strategy, measured sizing and cost, and validated physical table optimizations. These are implementation decisions to resolve through the specs, not choices this wiki silently makes.

## Claims to Avoid

Do not describe the accelerator as a released Microsoft blueprint, supported product, compliance solution, or confirmed end-to-end customer deployment. Do not include unverified customer names. Assisted exploration is a proposed research aid, not diagnosis, pathogenicity determination, or clinical decision-making.

Before presenting, read the [claim register](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/claim-register.md), check the current [coverage](https://github.com/samueltauil/genomics-variant-analytics/blob/main/README.md#coverage), and resolve any pending status updates using their linked acceptance evidence. Clearly distinguish a design diagram from demonstrated behavior.

## Sources

- [Known limitations and open questions](https://github.com/samueltauil/genomics-variant-analytics/blob/main/docs/limitations.md)
- [Demo-enablement specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/platform/demo-enablement/spec.md)
- [Repository Guardrails](Repository-Guardrails)