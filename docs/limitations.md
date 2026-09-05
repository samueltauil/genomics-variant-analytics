# Known limitations

What you will run into. Each entry says whether it is inherent to the platform — meaning it applies to a customer's production deployment too — or specific to this demo configuration.

## Platform constraints

These shaped the design. They are not defects, and they apply in production.

### Azure Storage Actions cannot move data out of a file share

**Inherent.** Storage Actions operates on Azure Blob Storage and Azure Data Lake Storage. It has no file-share source and no cross-service copy operation.

The Files-to-Blob hop uses a Data Factory Copy activity, which also pushes lineage into Purview automatically. Storage Actions is retained for blob-side lifecycle — tiering, retention, index tags. If you have seen an earlier deck showing `Azure Files → Storage Actions → Blob`, that step does not work as drawn.

### No file-created events for Azure file shares

**Inherent.** Event Grid publishes storage events for Blob and ADLS Gen2 only. There is no `Microsoft.Storage.FileCreated` event.

Arrival detection on the landing zone is a scheduled scan with a stability check — size and last-modified unchanged across two consecutive polls — or a vendor completion marker where the instrument writes one. This adds latency and metadata IOPS load, so scan run directories rather than walking the whole share.

*Workaround:* a VM-hosted file-system watcher publishing to a custom Event Grid topic cuts latency, at the cost of a component the lab has to operate.

### Azure Files caps a single file at 4 TiB

**Inherent.** Per-file throughput on SSD SMB is roughly 3 GiB/s read and 2 GiB/s write. On HDD it drops to 60 MiB/s, which is not viable for sequencing output.

Size the landing zone on SSD provisioned v2 with SMB Multichannel. An uncompressed whole-genome BAM sits well under the ceiling, but the ceiling exists.

### SMB requires classic file shares

**Inherent.** The `Microsoft.FileShares` resource provider supports NFS only. SMB shares must be deployed into a storage account via `Microsoft.Storage`.

### Purview does not carry record-level lineage for Fabric lakehouses

**Inherent.** Scanning a Fabric tenant yields item-level metadata and lineage. Sub-item metadata scanning is in preview, and sub-item *lineage* is unsupported.

Variant-level provenance therefore lives in the table itself — `source_file_uri`, `pipeline_version`, `reference_build` — joined to the metadata store. Purview provides the coarse-grained catalog above that.

**Do not promise variant-level lineage from Purview in a demo.** It will not be there.

### Release assets cap at 2 GiB per file

**Inherent.** Reference genomes do not fit. Releases carry reference manifests and checksums; the reference data itself stays in object storage, and the manifest resolves to its location.

## GitHub account-tier constraints

Specific to this repository being public and personal.

### Push rulesets are unavailable

**Demo-specific.** Push rulesets — which would block `.vcf`, `.bam`, `.cram`, and `.fastq` at push time across the whole fork network — target private and internal repositories only.

The substitute is a merge-time gate: the default branch requires a pull request, and a required data-hygiene check fails any pull request introducing those extensions or oversized files.

**Residual gap:** a direct push to an unprotected branch is not covered. Branch protection on the default branch closes the path that matters, but the guarantee is weaker than a push ruleset.

If you fork this into a private organization repository, add the push ruleset. It is strictly better.

### Copilot content exclusion is unavailable

**Demo-specific.** Content exclusion, centrally managed policy, and Copilot audit logs require Copilot Business or Enterprise.

No substitute exists. The mitigation is structural: the repository holds specs, workflows, infrastructure, and documentation, and never holds genomic data — so there is nothing to exclude.

### Environments depend on visibility and tier

**Demo-specific.** GitHub Free supports environments on public repositories only; private repositories need Pro or Team. This repository is public, so environments and their protection rules are available.

If you fork to a private repository on a free account, deployment approvals stop working.

## Demo configuration

### The data is synthetic

**Demo-specific.** Variant content comes from Illumina Platinum Genomes via Azure Open Datasets. Subject, sample, and cohort identifiers are generated.

Biologically realistic, clinically meaningless. Do not present cohort findings as clinical results, and do not add real patient data.

### Batch and HPC equivalence is concordance-based

**Demo-specific.** "Equivalent outputs across execution targets" is validated on variant-level concordance against a truth set using GATK `Concordance`, not bit-for-bit equality. Byte equality across different compute environments is not a realistic guarantee.

### The variant store is additive

**Inherent.** Delta variant records sit on top of retained VCFs — they do not replace them. Both are paid for.

Report cost per sample alongside query performance rather than implying the store replaces file storage.

### Healthcare data solutions is mid-transition

**Inherent.** A downloadable source package for customer-managed implementations became available August 3, 2026. Support for the managed solution ends December 31, 2027, and from October 1, 2026 only existing customers can deploy the managed version.

This accelerator depends on the folder taxonomy and medallion conventions, which are stable and documented, rather than on the managed solution's deployed artifacts.

## Open questions

Not yet decided, and they do not block the specs:

- Which Delta engine the reference deployment ships with — Fabric or Databricks. Both satisfy the specs; the choice affects deployment templates and cost modelling.
- Whether the accelerator ships an annotation step or expects annotated VCFs as input. The specs allow null annotation fields either way.
