## Purpose

Holds the clinical and research metadata that gives variant records meaning, linking subjects and samples through sequencing runs and file artifacts down to individual variants.

## ADDED Requirements

### Requirement: Subject-to-variant chain

The metadata store SHALL represent the chain Subject → Sample → Sequencing Run → FASTQ → BAM/CRAM → VCF → variant records, and each link SHALL be traversable in both directions.

#### Scenario: Traversing downward from a subject

- **WHEN** a consumer requests the artifacts derived from a subject
- **THEN** the subject's samples, sequencing runs, and resulting FASTQ, BAM/CRAM, and VCF artifacts are returned

#### Scenario: Traversing upward from a variant

- **WHEN** a consumer resolves the origin of a variant record
- **THEN** the source VCF, the BAM/CRAM and FASTQ it derives from, the sequencing run, the sample, and the subject are returned

### Requirement: Clinical and research metadata separation

The metadata store SHALL distinguish clinical metadata from research metadata, and access SHALL be grantable to one without granting the other.

#### Scenario: Research-only access

- **WHEN** a principal is granted research metadata access only
- **THEN** research metadata is readable
- **AND** clinical metadata is not returned

### Requirement: Links to primary genomic files

Every file-level metadata entry SHALL carry the artifact's storage URI, its stage in the analysis chain, its producing run where applicable, and its checksum or integrity result.

#### Scenario: File metadata is retrieved

- **WHEN** a consumer retrieves metadata for a genomic file artifact
- **THEN** its URI, analysis stage, producing run, and integrity result are returned

### Requirement: Referential integrity

A metadata entry SHALL NOT reference a subject, sample, run, or artifact that does not exist in the store. Deleting or archiving an entry SHALL NOT leave dangling references from variant records.

#### Scenario: Entry references a missing parent

- **WHEN** an entry is written referencing a non-existent sample
- **THEN** the write is rejected

#### Scenario: Artifact is archived

- **WHEN** a file artifact is archived
- **THEN** variant records that referenced it still resolve to a valid metadata entry marked archived

### Requirement: Synthetic identifiers in accelerator data

Subject, sample, run, and cohort identifiers in accelerator and demo metadata SHALL be synthetic. Real patient-identifiable metadata SHALL NOT be included in demo datasets.

#### Scenario: Demo metadata is loaded

- **WHEN** an accelerator demo metadata set is loaded
- **THEN** every subject and sample identifier is synthetic
- **AND** no real patient-identifiable attribute is present

### Requirement: Restricted access to patient-linked metadata

Metadata that links a variant or sample to a subject identity SHALL be access-restricted separately from de-identified variant data, so that broad variant query access does not imply access to subject linkage.

#### Scenario: Analyst with de-identified access

- **WHEN** an analyst holding de-identified variant access queries the metadata store
- **THEN** sample- and cohort-level attributes are returned
- **AND** subject linkage is withheld
