## Purpose

Holds variant records parsed from pipeline VCF output in a Delta-based Bronze store, so that variants become queryable, traceable to their source files, and efficient to store compared with keeping VCFs in object storage alone.

## ADDED Requirements

### Requirement: Core VCF record fields

Every variant record SHALL carry the core VCF fields: `CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, and `INFO`. A record missing `CHROM`, `POS`, `REF`, or `ALT` SHALL be rejected.

> Assumption: the background material states that eight VCF-related columns are required but does not enumerate them. This standard VCF core is a proposed accelerator schema and requires confirmation.

#### Scenario: Well-formed VCF line is ingested

- **WHEN** a VCF data line containing all core fields is parsed
- **THEN** a variant record is written with each core field populated

#### Scenario: Record missing a mandatory field

- **WHEN** a VCF data line lacks `REF` or `ALT`
- **THEN** the record is rejected and not written to the variant table

### Requirement: Accelerator context fields

Every variant record SHALL additionally carry `sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`, `variant_consequence`, `genotype`, `allele_frequency`, `reference_build`, `pipeline_version`, `source_file_uri`, and `ingestion_timestamp`. Fields not derivable from the source VCF or its annotations SHALL be recorded as null rather than fabricated.

> Assumption: these extension fields are a proposed accelerator/demo schema, not a confirmed implementation.

#### Scenario: Annotated variant is ingested

- **WHEN** an annotated VCF record is ingested for a known sample and cohort
- **THEN** the written record carries sample, subject, cohort, gene, transcript, consequence, genotype, allele frequency, reference build, pipeline version, source file URI, and ingestion timestamp

#### Scenario: Unannotated variant is ingested

- **WHEN** a VCF record has no gene or transcript annotation available
- **THEN** those fields are written as null
- **AND** the record is still accepted

### Requirement: Provenance to source file and run

Every variant record SHALL resolve to the VCF artifact it came from, the pipeline run that produced that artifact, and the reference build used. This linkage SHALL remain resolvable after the source artifact is tiered to cooler storage.

#### Scenario: Tracing a variant to its origin

- **WHEN** a consumer resolves provenance for a variant record
- **THEN** the source VCF URI, producing run identifier, and reference build are returned

#### Scenario: Source artifact has been tiered

- **WHEN** the source VCF has transitioned to a cooler storage tier
- **THEN** the variant record's provenance still resolves to that artifact

### Requirement: Rejected-record handling

Records rejected during ingestion SHALL be retained with the rejection reason, the source file URI, and the source line reference, and the ingestion run SHALL report the accepted and rejected counts.

#### Scenario: Ingestion run with rejections

- **WHEN** an ingestion run rejects some records
- **THEN** the run reports counts of accepted and rejected records
- **AND** each rejected record is retrievable with its reason and source location

### Requirement: Ingestion idempotency

Re-ingesting the same source VCF artifact SHALL NOT create duplicate variant records for that artifact. Ingesting output from a re-processing run SHALL create records distinguishable from the earlier run by pipeline version.

#### Scenario: Same file ingested twice

- **WHEN** an ingestion run is executed twice against the same source VCF artifact
- **THEN** the variant count attributable to that artifact is unchanged after the second run

#### Scenario: Reprocessed sample is ingested

- **WHEN** a sample reprocessed under a new pipeline version is ingested
- **THEN** its records are distinguishable from the prior run's records by `pipeline_version`

### Requirement: Ingestion run reporting

Each ingestion run SHALL report the number of variants ingested, the reference build, the pipeline version, the source-file links, the rejected-record count, and the resulting table maintenance state.

#### Scenario: Operator reviews an ingestion run

- **WHEN** an operator inspects a completed ingestion run
- **THEN** variant count, reference build, pipeline version, source links, rejection count, and maintenance state are shown

### Requirement: Table layout and maintenance

The variant store SHALL be organized to keep gene-scoped, sample-scoped, and cohort-scoped queries efficient as data volume grows, and its current layout and maintenance state SHALL be inspectable.

> Assumption: the specific partitioning and optimization strategy is proposed and requires validation against representative data volumes.

#### Scenario: Layout is inspected

- **WHEN** an operator inspects the variant table
- **THEN** the current partitioning or clustering strategy and the last maintenance state are reported

### Requirement: No real patient identity in accelerator data

Variant records used in accelerator and demo datasets SHALL use synthetic identifiers only, and SHALL NOT contain real patient-identifiable information.

#### Scenario: Demo variant dataset is loaded

- **WHEN** an accelerator demo dataset is loaded into the variant store
- **THEN** all subject, sample, and cohort identifiers are synthetic
