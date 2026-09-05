## Purpose

Defines how access to genomic data is tiered, authenticated, classified, traced, and audited across the accelerator, so that raw files, governed variant data, and aggregated analytics are separable and every result is attributable to its source.

## ADDED Requirements

### Requirement: Tiered access model

Access SHALL be granted against four distinct tiers: raw genomic files (highly restricted), the variant store (governed, purpose-limited), aggregated cohort analytics (broader approved access), and public or synthetic demo data (no patient identity). Access to one tier SHALL NOT imply access to a more restricted tier.

#### Scenario: Cohort analyst access

- **WHEN** a principal is granted aggregated cohort analytics access
- **THEN** aggregated results are readable
- **AND** raw genomic files are not readable

#### Scenario: Variant store access does not grant raw file access

- **WHEN** a principal holds governed variant store access
- **THEN** variant queries succeed
- **AND** direct reads of raw FASTQ or BAM artifacts are denied

### Requirement: Identity-based service access

Services and pipeline components SHALL authenticate to storage, compute, and data services using managed identities. Long-lived credentials or connection strings SHALL NOT be embedded in workflow definitions, notebooks, or configuration files; secrets required by external tools SHALL be retrieved from a managed secret store at run time.

#### Scenario: Pipeline reads staged input

- **WHEN** a pipeline run reads a staged artifact
- **THEN** it authenticates with its managed identity
- **AND** no storage key or connection string is present in the workflow definition

#### Scenario: External tool needs a secret

- **WHEN** a component requires a credential for an external tool
- **THEN** the credential is retrieved from the managed secret store at run time
- **AND** it is not persisted in source or configuration

### Requirement: Role-based authorization

Every data operation SHALL be authorized against the calling principal's assigned role, and an unauthorized operation SHALL be denied rather than silently returning empty or partial results.

#### Scenario: Unauthorized query

- **WHEN** a principal without variant store access issues a variant query
- **THEN** the request is denied with an explicit authorization error

### Requirement: Research and clinical workspace separation

Research and clinical work SHALL be performed in separate workspaces with independent access grants, and data SHALL NOT move between them without an explicit, recorded authorization.

#### Scenario: Cross-workspace data movement

- **WHEN** data is moved from the clinical workspace to the research workspace
- **THEN** the movement requires an explicit authorization
- **AND** the authorization and movement are recorded

### Requirement: Data classification

Genomic artifacts and variant tables SHALL carry a data classification, assigned at staging or ingestion, and the classification SHALL be visible to consumers alongside the data.

#### Scenario: Consumer inspects classification

- **WHEN** a consumer inspects a staged artifact or variant table
- **THEN** its assigned classification is returned

### Requirement: End-to-end lineage

Lineage SHALL be resolvable from any variant record back through the VCF, the pipeline run, the staged artifacts, and the landing-zone file, and forward from a landing-zone file to the variant records derived from it.

#### Scenario: Backward trace from a query result

- **WHEN** a user selects a variant returned by a query and requests its lineage
- **THEN** the source VCF, pipeline run, staged artifacts, and originating landing-zone file are returned

#### Scenario: Forward trace from an ingested file

- **WHEN** a user requests the downstream impact of a landing-zone file
- **THEN** the derived artifacts and variant records are returned

### Requirement: Audit trail

Pipeline executions, data access operations, reprocessing events, and cross-workspace transfers SHALL be recorded in an audit trail containing the principal, the operation, the affected data, and the timestamp. Audit entries SHALL NOT be modifiable by the principals they record.

#### Scenario: Reprocessing event is audited

- **WHEN** a sample is reprocessed
- **THEN** an audit entry records the principal, the sample, the prior and new pipeline versions, and the timestamp

#### Scenario: Access is audited

- **WHEN** a principal queries patient-linked metadata
- **THEN** an audit entry records the principal, the operation, the data accessed, and the timestamp

### Requirement: Private network access paths

Access paths between the landing zone, object storage, compute, and the variant store SHALL be configurable to use private networking, without requiring public endpoints for data-plane traffic.

#### Scenario: Deployment with public endpoints disabled

- **WHEN** the accelerator is deployed with public data-plane endpoints disabled
- **THEN** ingestion, staging, processing, and query paths continue to function over private networking

### Requirement: Controlled external sharing

Sharing data outside the deployment SHALL require an explicit, recorded approval identifying the dataset, the recipient, and the purpose. Sharing SHALL NOT be possible as a side effect of read access.

#### Scenario: External share is requested

- **WHEN** a user attempts to share a dataset externally
- **THEN** the share requires explicit approval recording dataset, recipient, and purpose
- **AND** the approval is auditable

### Requirement: No compliance claim

Accelerator documentation and demo material SHALL state that governance controls are configurable building blocks and SHALL NOT assert that deploying the accelerator makes genomic data compliant. Compliance depends on the customer's configuration, jurisdiction, policies, and operating procedures.

#### Scenario: Positioning is reviewed

- **WHEN** accelerator-facing material describes governance
- **THEN** it presents configurable controls
- **AND** it makes no claim of automatic regulatory compliance
