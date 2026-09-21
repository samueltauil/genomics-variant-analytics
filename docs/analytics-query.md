# Local governed analytics query engine

`scripts/analytics_query.py` implements the six supported query scenarios
from the analytics/variant-query-and-visualization spec as a local, governed
query core over `VariantStore` and `MetadataStore`. It is a SQLite harness
against runtime-generated synthetic VCF/metadata, not a deployed notebook
environment or SQL warehouse endpoint.

## Supported query scenarios (task 9.1)

`AnalyticsQueryEngine` exposes one method per scenario, each authorized
against the caller's `variant_store` access tier before any row is read:

- `query_by_gene(principal_id, gene)`
- `query_pass_filter(principal_id)` — `FILTER == "PASS"`
- `query_cross_cohort(principal_id)` — variants shared across more than one
  cohort, each row carrying a `cohorts` list
- `query_allele_in_sample(principal_id, sample_id, chrom, pos, ref, alt)`
- `query_by_pipeline_version(principal_id, pipeline_version)`
- `query_by_sequencing_run(principal_id, sequencing_run_id)` — resolves the
  sample(s) under the sequencing run via `MetadataStore.samples_for_sequencing_run`
  and filters variant rows by `sample_id`

Every returned row keeps the exact 20-field variant-store schema plus a
`producing_run` field attached from `run_provenance`; no scenario adds,
renames, or drops a variant-store column. An unauthorized principal is
denied with `AuthorizationError` rather than receiving an empty result, and
a principal without the `subject_linkage` capability keeps `sample_id` and
`cohort_id` but has `research_subject_id` withheld from every row.

## Notebook and SQL-endpoint surfaces (task 9.2)

`AnalyticsQueryEngine.execute_sql` is the SQL-endpoint surface: it runs a
governed, read-only `SELECT` through the same authorization,
de-identification, and traceability pipeline as the scenario methods. The six
scenario methods are convenience wrappers that execute the identical SQL
template text (`GENE_QUERY`, `PASS_FILTER_QUERY`, `CROSS_COHORT_QUERY`,
`ALLELE_IN_SAMPLE_QUERY`, `PIPELINE_VERSION_QUERY`) through `execute_sql`.
`SqlQueryAdapter` is a thin façade over `execute_sql` used to address the
SQL-endpoint surface distinctly from the Python method-call ("notebook")
surface in tests and documentation.

Because both surfaces share one query core and one set of SQL templates,
equivalence between them for the same principal is structural, and
`tests/test_analytics_query.py::test_notebook_and_sql_surfaces_return_equivalent_results`
verifies it directly. A deployed notebook environment and a deployed SQL
warehouse endpoint remain separate services that still require independent
deployment validation.

## Result traceability (task 9.3)

Every result row carries `source_file_uri`, `reference_build`, and
`pipeline_version` as native variant-store columns, plus `producing_run`
attached from `run_provenance` by the query core. `AnalyticsQueryEngine.trace(row)`
returns exactly those four values for a previously returned row without a
separate lookup path outside the analytics surface.

## Reproducible store snapshots (task 9.4)

`AnalyticsQueryEngine.create_snapshot()` records an immutable
`analytics_snapshots` entry bounding the current `MAX(rowid)` of
`variant_records` and `run_provenance`. Every query accepts an
`as_of_snapshot` argument; `NotebookSession` records a snapshot once at
construction and binds every query it issues to that recorded snapshot.
Re-running a notebook by constructing a new `NotebookSession` against the
same recorded `snapshot` reproduces the original result set even after
further ingestion, while a session with no recorded snapshot picks up the
newly ingested rows —
`tests/test_analytics_query.py::test_notebook_session_reproduces_recorded_snapshot`
demonstrates both cases.

## Scope and limitations

This module is local/reference evidence only. It does not implement or
exercise a deployed notebook workspace or Fabric/Databricks SQL endpoint.
Task 8.7 is therefore blocked: the current private Azure environment has
storage, staging, processing, and verification-client paths, but no approved
analytics engine or governed query endpoint with a private endpoint and
private-DNS path. A private blob read or this local harness is not evidence
for the missing query acceptance. Completion requires an approved engine,
managed-identity grants, governed access policy, private connectivity, an
authorized synthetic dataset, and an in-network query/audit check.
All identifiers used by the harness and its tests are synthetic; no genomic
payload is committed to the repository.

## Visualization view models (task 9.5)

`scripts/analytics_experience.py` provides six access-aware view models over
the governed query engine: gene-centric, variant-frequency, cohort-comparison,
quality-filter-funnel, sample-to-file-lineage, and processing-status. Each
view invokes the existing access check before reading its source data. The
lineage view starts from `MetadataStore.trace_sample`, so a restricted caller
sees sample-to-file lineage and never traverses to the subject; its response
states `subject_linkage_withheld: true`.

The processing-status model reflects the local ingestion provenance currently
available. It reports `ingestion-completed` for persisted ingestion runs and
uses null for execution target and failure reason because this local harness
does not persist pipeline-execution status. It does not infer unavailable
values.

## Query timing target (task 9.6)

Every supported `AnalyticsQueryEngine` scenario returns a list-compatible
`QueryResults` value with `scenario`, `snapshot_id`, and measured
`response_time_ms`; `engine.query_measurements` retains the execution-time
record for observability.

> **Assumption to validate:** the local reference target is no more than
> **1,000 ms per supported query** against the runtime-generated synthetic
> 51-record, two-cohort representative harness dataset, in one local SQLite process with no
> concurrent load. This is neither a production SLO nor a claim about
> Fabric, Databricks, network latency, customer data volume, or deployed
> infrastructure. A production target requires measurements on the selected
> engine, approved workload volume, concurrency, cache state, and reference
> configuration.

`tests/test_analytics_experience.py` exercises each of the six supported
queries and verifies a measured response time is published alongside the
result. The generated records and identifiers are synthetic.

## AI-assisted cohort exploration (task 9.7)

`AssistedCohortExploration` accepts only bounded questions that name a gene,
then maps them to `query_by_gene` or `query_cross_cohort`. It has no direct
table or file access. The caller principal is passed unchanged to
`AnalyticsQueryEngine`, so rephrasing a request cannot grant
`research_subject_id`: the governed projection still withholds it for callers
without `subject_linkage`.

Each assisted response returns source-file URI, producing run, reference
build, and pipeline version for every result and is labelled:
“Exploratory AI-assisted analysis only; not a diagnosis, clinical
determination, treatment recommendation, or clinical decision support.”