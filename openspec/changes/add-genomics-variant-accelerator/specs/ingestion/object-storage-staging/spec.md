## Purpose

Moves completed files from the SMB landing zone into object storage so that analytics and pipeline workloads run against scalable, lifecycle-managed storage rather than the ingestion file share.

## ADDED Requirements

### Requirement: Staging of completed files only

Staging SHALL move or copy a landed file into object storage only after the landing zone reports that file as complete. Files in an arriving or failed state SHALL NOT be staged.

#### Scenario: Complete file is staged

- **WHEN** a landed file is marked complete
- **THEN** it becomes eligible for staging and is transferred to the object-storage destination

#### Scenario: Incomplete file is skipped

- **WHEN** a staging cycle encounters a file still in the arriving state
- **THEN** the file is skipped and remains eligible for a later cycle

### Requirement: Integrity verification

Every staging operation SHALL verify that the object-storage copy matches the source, using a checksum or equivalent integrity check. A file whose verification fails SHALL be marked failed and SHALL NOT be advertised as available to downstream processing.

#### Scenario: Checksum matches

- **WHEN** a file is transferred and its destination checksum matches the source checksum
- **THEN** the staging record is marked verified and the file is available for processing

#### Scenario: Checksum mismatch

- **WHEN** the destination checksum does not match the source
- **THEN** the staging record is marked failed with the mismatch recorded
- **AND** downstream processing does not consume the file

### Requirement: Staging status reporting

Staging SHALL report, for each operation, the source path, the destination URI, the transfer state, the integrity result, the assigned storage tier, and the data classification applied.

#### Scenario: Operator reviews a staging run

- **WHEN** an operator inspects the staging results for a sequencing run
- **THEN** each file shows source, destination, state, integrity result, storage tier, and classification

### Requirement: Lineage from landing zone to object storage

Staging SHALL record a lineage link between the landing-zone source file and the resulting object-storage artifact, and that link SHALL remain resolvable for the lifetime of the staged artifact.

#### Scenario: Tracing a staged artifact to its source

- **WHEN** a consumer resolves lineage for a staged object-storage artifact
- **THEN** the originating landing-zone path, run identifier, and sample identifier are returned

### Requirement: Lifecycle and tiering policy

Staged artifacts SHALL be assigned a storage tier according to a configured lifecycle policy, and the policy SHALL be able to transition artifacts to cooler tiers over time without breaking lineage links or downstream URI references.

#### Scenario: Artifact is tiered down

- **WHEN** a staged artifact meets the lifecycle policy's age threshold
- **THEN** it transitions to the configured cooler tier
- **AND** its lineage link and URI continue to resolve

### Requirement: Separation of ingestion and analytics storage

Staged artifacts SHALL reside in an object-storage account or container that is distinct from the SMB landing zone, so that ingestion load and analytics load do not share the same storage boundary.

#### Scenario: Analytics read load is applied

- **WHEN** analytics workloads read heavily from staged artifacts
- **THEN** the reads are served from object storage
- **AND** the landing zone remains available for instrument writes
