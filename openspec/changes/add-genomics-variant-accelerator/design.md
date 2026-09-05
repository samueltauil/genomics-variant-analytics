## Context

See [proposal.md](proposal.md) for motivation. This section records only the platform constraints that shaped the approach, each verified against first-party documentation rather than assumed from the background study.

**Constraints established during research:**

1. **Azure Storage Actions does not operate on Azure Files.** It is a serverless framework for data operations on *Azure Blob Storage and Azure Data Lake Storage* — conditions and operations over blobs (tiering, tags, metadata, retention, rehydration, delete). It has no file-share source and no cross-service copy operation. The background study's `Azure Files → Storage Actions → Blob` step therefore cannot be implemented as written. ([What is Azure Storage Actions](https://learn.microsoft.com/azure/storage-actions/overview))
2. **Event Grid publishes storage events for Blob and ADLS Gen2 only.** There is no `Microsoft.Storage.FileCreated` event for Azure file shares, so arrival detection on the SMB landing zone cannot be event-driven. ([Azure Blob Storage as an Event Grid source](https://learn.microsoft.com/azure/event-grid/event-schema-blob-storage))
3. **SMB requires classic file shares.** The newer `Microsoft.FileShares` resource provider supports NFS only; SMB shares must be deployed into a storage account via `Microsoft.Storage`. ([Create an Azure file share](https://learn.microsoft.com/azure/storage/files/create-file-share))
4. **Azure Files caps a single file at 4 TiB.** Per-file throughput on SSD SMB is roughly 3 GiB/s read and 2 GiB/s write; on HDD it drops to 60 MiB/s. Provisioned v2 lets storage, IOPS, and throughput be provisioned independently. ([Scalability and performance targets for Azure Files](https://learn.microsoft.com/azure/storage/files/storage-files-scale-targets))
5. **Purview does not carry sub-item lineage for Fabric lakehouses.** Scanning a Fabric tenant yields item-level metadata and lineage; sub-item metadata scanning is in preview and sub-item *lineage* is unsupported. Record-level provenance cannot be delegated to the catalog. ([Lineage from Microsoft Fabric items into Microsoft Purview](https://learn.microsoft.com/purview/data-map-lineage-fabric))
6. **Healthcare data solutions in Microsoft Fabric already defines a genomics-aware layout.** Its unified folder structure names a genomics modality covering BAM, BCL, FASTQ, and VCF, with top-level `Ingest`, `Process`, `Failed`, `External`, `Inventory`, `ReferenceData`, and `SampleData` folders, a bronze/silver/gold medallion, and record-level lineage columns (`msftCreatedDatetime`, `msftModifiedDatetime`, `msftFilePath`). It also recommends the Bring Your Own Storage shortcut pattern over physical copies specifically because imaging and genomics volumes make direct ingestion infeasible. ([Data foundations in healthcare data solutions](https://learn.microsoft.com/industry/healthcare/healthcare-data-solutions/data-architecture-and-management))
7. **Healthcare data solutions is changing delivery model.** From August 3, 2026 a downloadable source package is available for customer-managed implementations; support for the managed solution ends December 31, 2027, and from October 1, 2026 only existing customers can deploy the managed version. ([Overview of healthcare data solutions in Microsoft Fabric](https://learn.microsoft.com/industry/healthcare/healthcare-data-solutions/overview))
8. **Azure Managed Lustre integrates with Blob via Lustre HSM.** A file system can import from a blob container, run jobs, export changed data back, and then be deleted — so scratch capacity need not be persistent. ([What is Azure Managed Lustre?](https://learn.microsoft.com/azure/azure-managed-lustre/amlfs-overview))
9. **Illumina Platinum Genomes is available through Azure Open Datasets**, with documented GATK `VariantsToTable` usage for flattening VCF INFO and FORMAT fields into tabular form. This gives the accelerator a citable, non-PHI demo dataset and a defensible VCF-to-columns mapping. ([Illumina Platinum Genomes](https://learn.microsoft.com/azure/open-datasets/dataset-illumina-platinum-genomes))
10. **Immutable releases lock a tag to a commit and generate a release attestation.** Assets cannot be modified or deleted, tag names cannot be reused even after repository deletion, and publication produces a cryptographically verifiable record of tag, commit SHA, and assets. ([Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases))
11. **Artifact attestations can target any registry, including ACR.** `actions/attest` accepts a fully-qualified `subject-name` such as `acme.azurecr.io/user/app` with `push-to-registry: true`, and supports SBOM predicates alongside build provenance. Verification runs through `gh attestation verify`, including offline. ([Using artifact attestations](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds))
12. **Environment protection rules are tier-sensitive.** GitHub Free supports environments on public repositories only; private repositories require GitHub Pro or Team. Required reviewers cap at 6, self-review can be prevented, and administrator bypass can be disabled. ([Managing environments for deployment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments))
13. **Push rulesets target private and internal repositories only.** They restrict file extensions, paths, path length, and file size across a repository's whole fork network, but a public repository cannot use them. Branch and tag rulesets are not restricted this way. Repository-level rulesets work on personal accounts; organization-wide rulesets need Team or Enterprise. Release assets are capped at 2 GiB per file with no total size limit. ([About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets), [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases))
14. **Copilot content exclusion, policy management, and audit logs require Copilot Business or Enterprise.** They are unavailable to a personal-account deployment. Agent skills, custom agents, prompt files, MCP servers, Copilot Spaces, repository memory, code review, and scheduled agent automations are not organization-gated. ([GitHub Copilot features](https://docs.github.com/en/copilot/get-started/features))

## Goals / Non-Goals

**Goals:**

- Keep every capability's contract implementable on components that exist today, correcting the background study where documentation contradicts it.
- Make record-level provenance a property of the data model, not of an external catalog.
- Align the variant store with the medallion layout and lineage conventions already established for healthcare genomics on Fabric, so the accelerator composes with that solution instead of competing with it.
- Keep batch and HPC genuinely interchangeable behind one workflow definition.

**Non-Goals:**

- Choosing between Fabric and Databricks as the Delta engine. Both satisfy the specs; the accelerator targets the Delta protocol and OneLake/ADLS storage, and treats the engine as deployment configuration.
- Building a clinical decision-support system or an interpretation product. AI-assisted interpretation is a demonstration surface only.
- Specifying the annotation toolchain (VEP, SnpEff, Annovar). The specs require annotation fields to be populated or null; the tool is an implementation choice.
- Any claim of regulatory compliance. See the governance spec's final requirement.

## Decisions

### 1. Replace Storage Actions with a copy service for the Files-to-Blob hop; keep Storage Actions for blob lifecycle

The staging spec requires movement plus integrity verification plus lineage. Storage Actions cannot read a file share at all, so it cannot be the mover.

Chosen: a Data Factory (Fabric or Azure) Copy activity as the mover, because Copy is one of the three activity types that push lineage into Purview automatically, and it can mount an SMB/Azure Files source and write to ADLS. Storage Actions is retained for what it is actually built for — tiering, retention, and index-tag management on the blob side after landing — which is how the staging spec's lifecycle requirement is met.

Alternatives considered:
- **AzCopy on a scheduled agent.** Simplest and fastest for bulk transfer, but produces no catalog lineage and needs a hosted runner. Kept as the fallback for very large single files where Copy activity throughput is insufficient.
- **Azure Storage Mover.** Built for migration, not steady-state repeating ingestion.
- **Azure File Sync.** Solves the wrong problem — it caches shares on Windows servers rather than landing objects in blob.

### 2. Poll the landing zone; do not wait for events

Given constraint 2, arrival detection uses a scheduled directory scan over the share, with completeness determined by a stability check (size and last-modified unchanged across two consecutive polls) or an instrument-written completion marker where the vendor emits one. The spec's `arriving` state exists precisely because completeness is inferred rather than signalled.

Alternative considered: an on-premises or VM-hosted file-system watcher publishing to Event Grid via a custom topic. Lower latency, but adds a component the lab has to operate, which conflicts with the "change nothing in the lab" goal. Documented as an optional accelerator for latency-sensitive deployments.

### 3. Adopt the healthcare data solutions folder taxonomy and lineage columns

Rather than inventing a layout, the staging destination and the variant store follow the published genomics-modality structure — `Ingest`, `Process`, `Failed`, `ReferenceData`, `SampleData`, namespace subfolders, and `YYYY/MM/DD` partitioning of processed files. The variant store carries lineage columns modelled on `msftFilePath` / `msftCreatedDatetime`, surfaced in the spec as `source_file_uri` and `ingestion_timestamp`.

This directly satisfies the spec requirement that `Failed` handling and rejected-record retention exist, and it means a customer already running healthcare data solutions can point the accelerator at the same lake.

### 4. Shortcut genomic files into the lake; copy only the variant records

Following the BYOS guidance in constraint 6, FASTQ/BAM/CRAM/VCF stay in ADLS and are exposed to the analytics engine through OneLake shortcuts. Only parsed variant rows are materialized into Delta. This keeps the physical copy count at one for multi-terabyte artifacts and keeps `source_file_uri` pointing at a single canonical location, which is what makes the provenance requirement satisfiable after tiering.

### 5. Implement provenance in the table, not in the catalog

Because of constraint 5, every variant row carries its own `source_file_uri`, `pipeline_version`, and `reference_build`, and the metadata store holds the run and artifact graph. Purview is used for what it does support: classification, item-level lineage across the pipeline and lakehouse, and the audit surface. The governance spec's end-to-end lineage requirement is therefore met by joining table columns to the metadata store, with Purview providing the coarse-grained view above it.

### 6. One Nextflow definition, two executors

Nextflow is the reference workflow engine because it has first-class executors for both Azure Batch and Slurm, which is what makes the "interchangeable execution targets" requirement testable rather than aspirational. The same pipeline definition changes executor through configuration only. Snakemake and Cromwell remain supported statements about customer portability, not accelerator deliverables.

For the HPC path, scratch is an Azure Managed Lustre file system created per campaign, hydrated from the blob container via HSM import, and exported and torn down afterwards (constraint 8). This is what keeps the elastic-compute requirement true for HPC as well as batch.

### 7. Reference data is content-addressed and immutable

Reference builds live under the `ReferenceData` folder with `name/version` paths. The immutability requirement is enforced by write-once containers plus a manifest recording a checksum per reference artifact; the workflow records the manifest digest in run provenance. Compatibility between workflow version and reference version is declared in a manifest the submission path validates before allocating compute, which is what allows rejection "before compute is allocated".

### 8. Demo data comes from Illumina Platinum Genomes, with synthetic clinical wrapping

Constraint 9 gives a real, redistributable, consented variant dataset. Subject, cohort, and clinical attributes around it are synthetic and generated, satisfying the no-PHI requirement in every spec while keeping the variant content biologically realistic. ClinVar-derived tables are the reference knowledge base for annotation; community mirrors exist on Hugging Face (for example [huggingworld/clinvar_variant_summary](https://hf.co/datasets/huggingworld/clinvar_variant_summary)), though the accelerator should pull from the NCBI source of record.

For the AI-assisted interpretation surface, genomic language models on Hugging Face such as the DNABERT family ([zhihan1996/DNA_bert_6](https://hf.co/zhihan1996/DNA_bert_6)) and NVIDIA's NV-JEPA-DNA variants are the demonstration options. This remains a proposed component.

### 9. Eight-column question stays open but non-blocking

The source material's "eight required VCF columns" is unenumerated. The specs commit to the eight standard VCF core columns and label it an assumption. GATK `VariantsToTable` treats exactly these as the standard columns, which makes it the most defensible reading. If the source material later names a different eight, only the delta-variant-store spec's first requirement changes.

### 10. GitHub anchors `pipeline_version`; the registry only distributes

`pipeline_version` was a free-text string with no source of truth, which made the reproducibility and provenance requirements unverifiable in practice. Binding it to an immutable release fixes that: the tag locks to one commit, the assets lock against modification, tag names cannot be reused even if the repository is deleted and recreated, and publication generates a release attestation covering tag, commit SHA, and assets.

This is where the platform earns its place next to Azure Container Registry rather than duplicating it. A registry gives you an image digest — content identity. It does not tell you which commit, which workflow, or which runner produced that content. `actions/attest` closes that gap, and because `subject-name` accepts any fully-qualified image name including `<registry>.azurecr.io/...` with `push-to-registry: true`, the attestation travels into ACR itself. ACR stays the distribution point; GitHub becomes the provenance authority. Verification is `gh attestation verify oci://...`, and it works offline for air-gapped clinical environments.

The SBOM attestation carries the part bioinformaticians actually ask about: which aligner and which variant-caller version produced this VCF. That question currently has no answer anywhere in the design, and a container digest does not provide one.

Alternatives considered:
- **A version table in the metadata store.** Keeps everything in one place, but it is self-asserted — nothing prevents a row claiming a version that was never built from that source.
- **Signing with cosign and a self-managed key.** Equivalent cryptography, but adds key custody, which is precisely the operational burden the governance spec's secretless requirement is trying to remove.

### 11. Personal-account constraints shape which controls are specified

The demo repository is public and lives in a personal account, which rules out two classes of control.

**Push rulesets are unavailable.** They block pushes to a *private or internal* repository and its fork network; a public repository cannot use them. The earlier draft of this design paired "make it public" with "use a push ruleset", which does not work. The substitute is a merge-time gate: the default branch is protected, all changes arrive by pull request, and a required data-hygiene status check fails the pull request when a `.vcf`, `.bam`, `.cram`, `.fastq`, or oversized file appears in the diff. Actions minutes are unmetered on public repositories, so the check costs nothing to run.

This is weaker than a push ruleset in one specific way, and the specs say so: a direct push to an unprotected branch is not covered. Branch protection on the default branch plus a pull-request-only workflow closes the path that matters. Secret scanning with push protection remains available and does gate at push time.

**Copilot content exclusion is unavailable**, being a Copilot Business and Enterprise feature. There is no equivalent substitute — the mitigation is structural rather than configured: the repository holds specs, workflow definitions, infrastructure, and documentation, and never holds genomic data, so there is nothing to exclude.

Public is still the right call. It unlocks environments and their protection rules at every tier, unmetered Actions, secret scanning, and code scanning, and it is what makes the repository shareable in the first place. Repository-level rulesets work on personal accounts; only organization-wide rulesets need Team or Enterprise. Release assets cap at 2 GiB per file, which is why reference genomes stay in object storage and releases carry only manifests and checksums.

### 12. Copilot is specified by contract, not by feature

The specs deliberately say "AI assistant" and "governed query interface" rather than naming product features, because the requirements have to stay testable if the tooling changes. The intended implementation uses the less-obvious end of the feature set:

- **Agent skills and prompt files** put the VCF schema rules, the no-PHI constraint, and the positioning constraints under version control, so domain rules reach the assistant through pull-request review rather than through whatever the contributor remembered to type. This repository already demonstrates the pattern — OpenSpec installed exactly these artifacts.
- **An MCP server fronting the variant store** is the load-bearing decision. Giving an assistant table credentials would break the governance spec's access tiers immediately. Fronting the store with an MCP server that enforces the caller's tier server-side means assisted exploration inherits governance for free, and assistant queries land in the same audit trail as any other query.
- **Copilot code review** checks the class of mistake humans miss on these pull requests: a reference build changed without a version bump, or a variant-store column added without a matching spec change.
- **Scheduled agent triage** converts overnight pipeline failures into tracked issues carrying run provenance, which is the operational visibility the laboratory operations manager persona asks for.
- **Copilot Spaces and repository memory** ground responses on the accelerator's own specs rather than generic genomics knowledge.

### 13. One engineer, one flow

The audience is a Microsoft solution engineer who finds this repository, checks whether their subscription can host it, provisions it, and demos it to a customer. That is one person doing one continuous thing, so it is one capability rather than a split between delivery and adoption. Whether this later becomes a blueprint reference is undefined and not an intent here; specifying a redistribution contract now would be designing for a reader who does not exist.

Two requirements exist because the audience is *another* engineer rather than the author:

**Preflight gates provisioning.** Discovering an unmet quota or a missing role partway through a half-built environment is the standard way a borrowed demo fails, and it surfaces the morning of the customer meeting rather than the week before. Provisioning refuses to start until preflight passes.

**The claim register is a repository artifact, not presenter folklore.** The background material already separates confirmed items from proposed ones, and it flags one customer attribution as unverifiable. That distinction does not survive being retold; it survives being written down and reviewed. The register states, per boundary, the supported phrasing and the phrasing to avoid, and presenter material is checked against it.

The documentation splits by document rather than by audience: a front door, a runbook, a claim register, and a limitations list, all for the same reader at different points in the flow.

## Risks / Trade-offs

- **The Storage Actions step in the source material is wrong, and it may appear in earlier architecture decks** → the design keeps the same narrative shape (landing zone → automated movement → object storage) so the demo story survives, while the implementation uses Copy activity; Storage Actions still appears, correctly scoped to blob lifecycle.
- **Polling adds arrival latency and metadata IOPS load on the share** → poll a bounded set of run folders on an interval tuned to run duration; Azure Files charges metadata-heavy workloads with higher latency, so the scan must list run directories rather than walk the whole share.
- **Healthcare data solutions is mid-transition to a customer-managed package** → depend on the folder taxonomy and medallion conventions, which are stable and documented, rather than on the managed solution's deployed artifacts.
- **Purview cannot show record-level lineage** → provenance columns and the metadata store are the system of record for fine-grained lineage; Purview is presented as the coarse-grained catalog, and demo scripts must not promise variant-level lineage from Purview.
- **Per-file 4 TiB ceiling and HDD throughput of 60 MiB/s** → size the landing zone on SSD provisioned v2 with SMB Multichannel; an uncompressed whole-genome BAM sits well under 4 TiB, but the ceiling must be stated in accelerator guidance rather than discovered.
- **"Equivalent outputs across batch and HPC" is hard to guarantee bit-for-bit** → the reproducibility requirement is validated on variant-level concordance, not byte equality, using GATK `Concordance` against a truth set.
- **Cost of keeping variants in Delta on top of retained VCFs** → the store is additive, so the accelerator must report cost per sample alongside query performance rather than implying the Delta store replaces the files.
- **A public demo repository is a permanent, indexed surface** → the push ruleset is the control that makes public tenable, so it must be in place before the first push, not added later; anything already committed stays in history.
- **Immutability is unforgiving of mistakes** → publish releases from drafts with all assets attached first, since a published tag cannot be moved and its name cannot be reclaimed.
- **An MCP server fronting the variant store becomes a new access path to govern** → it enforces the caller's tier server-side and writes to the same audit trail; it must never hold table or storage credentials that exceed the caller's own grant.
- **Assisted interpretation invites over-claiming** → the analytics spec requires assisted output to be labelled exploratory, and the design's non-goals exclude clinical decision support.

## Migration Plan

Not applicable — no existing system, no data to migrate. Deployment order is the task breakdown in [tasks.md](tasks.md): landing zone and staging first, since every later capability consumes staged artifacts.

## Open Questions

- Which Delta engine the reference deployment ships with (Fabric or Databricks). Both satisfy the specs; the choice affects deployment templates and cost modelling, not the contracts.
- Whether the accelerator ships its own annotation step or expects annotated VCFs as input. The specs allow null annotation fields either way.
