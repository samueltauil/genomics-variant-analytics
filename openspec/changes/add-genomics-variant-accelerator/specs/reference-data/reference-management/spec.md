## Purpose

Manages the reference genomes, annotations, and knowledge bases that alignment, variant calling, and annotation depend on, so that every pipeline run binds to a known reference version and results stay reproducible.

## ADDED Requirements

### Requirement: Managed reference-data zone

The reference-data zone SHALL hold reference genome builds, gene annotations, transcript definitions, clinical knowledge bases, and population reference data, each identified by name and version.

#### Scenario: Reference inventory is listed

- **WHEN** a consumer lists available reference data
- **THEN** each entry is returned with its type, name, and version

### Requirement: Explicit reference build selection

A pipeline run SHALL declare the reference build it uses, and the run SHALL fail rather than fall back to a default when the declared build is unavailable.

#### Scenario: Declared build is available

- **WHEN** a run declares a reference build that exists in the zone
- **THEN** the run executes against that build
- **AND** the build identifier and version are recorded in the run's provenance

#### Scenario: Declared build is missing

- **WHEN** a run declares a reference build that is not present in the zone
- **THEN** the run fails with the missing build identified
- **AND** no alternative build is substituted

### Requirement: Reference versioning and immutability

A published reference-data version SHALL be immutable. Corrections or updates SHALL be published as a new version, and prior versions SHALL remain retrievable while any run or variant record still references them.

#### Scenario: Reference is updated

- **WHEN** an updated annotation set is published
- **THEN** it is assigned a new version
- **AND** the previous version remains retrievable

#### Scenario: Attempt to overwrite a published version

- **WHEN** a write targets an already-published reference version
- **THEN** the write is rejected

### Requirement: Pipeline compatibility declaration

Each workflow version SHALL declare the reference builds and annotation versions it is compatible with, and a run pairing a workflow with an incompatible reference SHALL be rejected before execution.

#### Scenario: Incompatible pairing is submitted

- **WHEN** a run pairs a workflow version with a reference build outside its declared compatibility
- **THEN** the run is rejected before compute is allocated
- **AND** the incompatibility is reported

### Requirement: Multi-build coexistence

The zone SHALL support multiple reference builds concurrently, and downstream variant records SHALL remain distinguishable by the build they were called against.

#### Scenario: Comparing results across builds

- **WHEN** a sample has been processed against two different reference builds
- **THEN** each set of variant records is attributable to its build
- **AND** the two sets are queryable independently

### Requirement: Reference access control and audit

Access to reference data SHALL be controlled by role, and read and publish operations SHALL be recorded in an audit trail identifying the principal, the entry, the version, and the timestamp.

#### Scenario: Reference version is published

- **WHEN** an authorized principal publishes a new reference version
- **THEN** an audit entry records the principal, entry, version, and timestamp

#### Scenario: Unauthorized publish attempt

- **WHEN** a principal without publish rights attempts to publish a reference version
- **THEN** the operation is denied and the denial is audited
