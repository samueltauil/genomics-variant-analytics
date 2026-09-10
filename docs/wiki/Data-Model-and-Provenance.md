# Data Model and Provenance

**Specified contract, not an implemented database.** This page is an orientation to the variant-store and metadata specifications. Read the linked specs before choosing schemas, ingestion libraries, or physical table layouts.

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