# Data Model and Provenance

**Variant store specified; metadata lineage implemented locally as of 2026-09-10.** This page distinguishes the planned variant store from the synthetic SQLite lineage model. The metadata implementation is committed and pushed under [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12), not merged into `main` or deployed as a service. Read the linked specs before choosing ingestion libraries or physical table layouts.

## Variant Records

The current proposal uses the eight standard VCF core fields:

| Field | Meaning |
|---|---|
| `CHROM` | Reference sequence or chromosome |
| `POS` | Variant position |
| `ID` | Variant identifiers, when supplied |
| `REF` | Reference allele |
| `ALT` | Alternate allele or alleles |
| `QUAL` | Variant quality value |
| `FILTER` | Filter outcome |
| `INFO` | Additional VCF annotations |

`CHROM`, `POS`, `REF`, and `ALT` are mandatory under the proposed ingestion contract. The eight-field selection is a documented proposal, not a claim that the originating requirements enumerated these fields.

The proposed context fields add sample, analysis, and provenance information:

| Group | Fields |
|---|---|
| Research context | `sample_id`, `research_subject_id`, `cohort_id` |
| Annotation | `gene`, `transcript`, `variant_consequence` |
| Sample and population values | `genotype`, `allele_frequency` |
| Reproducibility | `reference_build`, `pipeline_version` |
| Source and ingestion | `source_file_uri`, `ingestion_timestamp` |

Annotations may be absent according to the specification. Missing annotations must not be invented. Genotype and other context are not substitutes for retaining the original source artifact.

## Traceability

The metadata model is intended to connect:

```text
research subject -> sample -> sequencing run -> source file
                                                |
                                                v
                                processing run and output artifact
                                                |
                                                v
                                      parsed variant record
```

Reference manifests and pipeline versions supply the additional context needed to interpret and reproduce the processing run. A result must resolve to its source file, processing version, and reference build rather than relying on a catalog entry alone.

`research_subject_id` is not an authorization grant. The planned de-identified query surface must withhold identity-linked information according to the caller's tier. Do not assume pseudonymous identifiers make unrestricted access acceptable.

## Local Metadata Implementation

Tasks 6.1 through 6.4 now have a persistent SQLite model with 21 passing synthetic tests. Entities carry an immutable, globally unique identifier and kind; identifiers match `SYN-[A-Z0-9][A-Z0-9_-]*`. Links preserve this chain:

```text
subject -> sample -> sequencing_run -> fastq -> bam/cram -> vcf/gvcf -> variant
```

Samples have one subject; FASTQ artifacts have one sequencing run; variant occurrences have one source VCF/GVCF. Runs can have multiple sample parents, alignments multiple FASTQ parents, and joint VCFs multiple alignment parents. Every parent must already exist and match the allowed stage. Atomic inserts reject missing parents, duplicates and invalid transitions. Database foreign keys prevent dangling links through the store connection. There is no replace or delete API.

`MetadataStore.trace_subject` returns descendants and `trace_variant` returns ancestors, including the root, sorted entities and links, deduplicated shared nodes and a consistent database snapshot. Tests cover both full-chain directions, BAM/CRAM and VCF/GVCF alternatives, branches, missing-sample rejection, persistence and a concurrent append between trace queries. No genomic payload is opened.

This is artifact ancestry, not sample-genotype assignment: a multiplexed run or joint-call VCF can have several contributing samples. Reachability does not prove an allele belongs to all of them. Sample-specific genotype attribution and demultiplexing provenance require later integration. Test fixtures are invented metadata, not the future Platinum Genomes demo dataset or actual pipeline outputs.

The API requires a trusted absolute local database path, separate from scanner inventory. It rejects network/redirect paths using the shared local-path guard and rejects foreign database schemas. It accepts no clinical attributes, but returns subject linkage: **do not expose it to analysts or treat it as access-controlled**. Identifier syntax is not PHI detection, and direct database access can bypass application rules. Protect files and reports with local filesystem controls.

New file artifacts require `storage_uri`, `analysis_stage`, `producing_run` and `integrity_result`, with an optional SHA-256. Sequencing producers are registered from their lineage entities; processing producers use `add_pipeline_run` with workflow identity and version. `get_artifact` returns those details and the archive flag. URIs and integrity assertions are recorded, not resolved or verified; no pipeline execution is implied by registering a producer.

`archive_artifact` marks metadata idempotently without deleting files or links. Variants still resolve to the same source entry with `archived: true`; both trace directions expose this flag in schema version 2. Version-1 databases migrate without invented file details; `backfill_file_metadata` supplies missing details once before file retrieval or archival.

Task 6.5's clinical/research grants, audit and Delta/Purview integration remain pending. Trace responses declare `mode: local-only` and `azure_readiness: not-evaluated`. Development sources are the [metadata API](https://github.com/samueltauil/genomics-variant-analytics/blob/security/secret-push-protection/scripts/metadata_store.py), [synthetic tests](https://github.com/samueltauil/genomics-variant-analytics/blob/security/secret-push-protection/tests/test_metadata_store.py) and [usage guide](https://github.com/samueltauil/genomics-variant-analytics/blob/security/secret-push-protection/docs/metadata-store.md). Publication is not evidence of cloud readiness or governed access.

## Versioning and Retention

- `pipeline_version` is intended to resolve to an immutable GitHub release and its build provenance. Release and attestation automation are not implemented yet.
- Reference builds are to be versioned with checksums and immutable manifests. Reference genome bytes remain in object storage, not Git or release attachments.
- Parsed Delta rows are additive to retained VCF and other file artifacts; the store does not replace those artifacts.
- Reprocessing must remain traceable to the processing version and source artifact. A new run must not silently rewrite the evidence for an earlier result.

## Sources

- [Delta variant-store specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/variant-store/delta-variant-store/spec.md)
- [Genomic metadata specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/variant-store/genomic-metadata/spec.md)
- [Reference-management specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/reference-data/reference-management/spec.md)
- [Access and lineage specification](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/specs/governance/access-and-lineage/spec.md)