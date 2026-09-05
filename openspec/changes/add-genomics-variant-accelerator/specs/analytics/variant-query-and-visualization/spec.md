## Purpose

Provides the tertiary-analysis surface where research and clinical users query the governed variant store and view results, turning stored variants into cohort analysis, interpretation, and operational visibility.

## ADDED Requirements

### Requirement: Supported query scenarios

The analytics surface SHALL answer, over the governed variant store, queries that filter by gene, by quality filter status, by cohort membership including variants shared across cohorts, by allele present in a sample, by pipeline version, and by originating sequencing run.

#### Scenario: Gene-scoped query

- **WHEN** a user queries for variants in a named gene
- **THEN** matching variant records are returned with their sample, cohort, quality filter status, reference build, and pipeline version

#### Scenario: Quality-filter query

- **WHEN** a user queries for variants that pass quality filters
- **THEN** only records whose `FILTER` status indicates a pass are returned

#### Scenario: Cross-cohort query

- **WHEN** a user queries for variants appearing in more than one cohort
- **THEN** each returned variant is accompanied by the cohorts it appears in

#### Scenario: Pipeline-version query

- **WHEN** a user queries for records produced by an older pipeline version
- **THEN** matching records are returned with their pipeline version and producing run

### Requirement: Query access is governed

Query results SHALL be constrained by the caller's access tier. A caller without subject-linkage access SHALL receive de-identified results rather than a denial of the whole query.

#### Scenario: De-identified caller queries a gene

- **WHEN** a caller holding de-identified variant access runs a gene-scoped query
- **THEN** variant, sample, and cohort attributes are returned
- **AND** subject linkage is withheld

### Requirement: Notebook and SQL access

The variant store SHALL be reachable from both a notebook environment and a SQL endpoint, and both SHALL return equivalent results for an equivalent query.

#### Scenario: Same query through two surfaces

- **WHEN** the same logical query is issued through the notebook environment and through the SQL endpoint by the same principal
- **THEN** both return equivalent result sets

### Requirement: Result traceability

Every query result row SHALL be traceable to its source VCF, producing pipeline run, reference build, and pipeline version without requiring a separate lookup path outside the analytics surface.

#### Scenario: User inspects a result row

- **WHEN** a user selects a returned variant and requests its origin
- **THEN** source file URI, producing run, reference build, and pipeline version are shown

### Requirement: Reproducible analysis

An analysis notebook SHALL record the variant store version or snapshot it read, so that re-running it against that recorded version yields the same result set.

#### Scenario: Notebook is re-run later

- **WHEN** a notebook is re-run against the store version it originally recorded
- **THEN** it produces the same result set as the original run

### Requirement: AI-assisted exploration

The analytics surface SHALL offer AI-assisted exploration of the variant store for query authoring and cohort investigation. Assisted queries SHALL be subject to the same access-tier constraints as hand-written queries, and every assisted result SHALL carry the same traceability as a direct query result.

> Assumption: AI-assisted interpretation is named in the background material as a demonstration surface. It is not a clinical decision-support capability and must not be positioned as one.

#### Scenario: Analyst asks a cohort question in natural language

- **WHEN** a research scientist asks for variants in a named gene that appear in more than one cohort
- **THEN** the assistant returns results drawn from the governed query interface
- **AND** each result carries its source file URI, producing run, reference build, and pipeline version

#### Scenario: Assisted query cannot widen access

- **WHEN** a caller without subject-linkage access phrases a request that would require subject identity
- **THEN** the response withholds subject linkage rather than returning it

#### Scenario: Positioning of assisted output

- **WHEN** assisted interpretation output is presented
- **THEN** it is labelled as exploratory and not as a clinical determination

### Requirement: Visualization views

The analytics surface SHALL provide a gene-centric variant view, a variant-frequency view, a cohort comparison view, a quality-filter funnel, a sample-to-file lineage view, and a processing-status view. Each view SHALL respect the caller's access tier.

> Assumption: these specific screens are proposed accelerator components; the visualization requirement itself is confirmed, the screen set is not.

#### Scenario: Gene-centric view is opened

- **WHEN** a user opens the gene-centric view for a named gene
- **THEN** variants in that gene are displayed with cohort and quality-filter context

#### Scenario: Processing-status view is opened

- **WHEN** an operator opens the processing-status view
- **THEN** runs are displayed with their state, execution target, and failure reasons where applicable

#### Scenario: Restricted caller opens a view

- **WHEN** a caller without subject-linkage access opens the sample-to-file lineage view
- **THEN** lineage is shown to the sample level
- **AND** subject identity is not displayed

### Requirement: Query responsiveness target

The analytics surface SHALL define and report a response-time target for the supported query scenarios against a representative dataset, and SHALL make the measured response time observable for each query.

> Assumption: specific query-performance targets are proposed and require validation against representative data volumes.

#### Scenario: Query performance is measured

- **WHEN** a supported query is executed against the representative dataset
- **THEN** its measured response time is reported alongside the result
