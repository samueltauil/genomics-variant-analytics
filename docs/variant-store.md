# Local Bronze variant store

`scripts/variant_store.py` provides a local SQLite implementation of the
accelerator's Delta-compatible Bronze row contract. It is a development and
test harness, not a claim of a production Delta engine deployment.

The `variant_records` table has exactly the 20 fields defined by the
variant-store specification:

`CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`,
`sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`,
`variant_consequence`, `genotype`, `allele_frequency`, `reference_build`,
`pipeline_version`, `source_file_uri`, `ingestion_timestamp`.

VCF input is supplied as runtime-generated text through `ingest_vcf_text`.
The parser follows the relevant `VariantsToTable` behavior: core VCF columns
are retained, INFO keys become annotation values, and FORMAT/sample values
provide `GT` and (when present) `AF`. Missing optional annotations remain
`NULL`. `CHROM`, `POS`, `REF`, and `ALT` are mandatory; invalid records are
captured in `rejected_records` with their source line and reason.

Run provenance is stored separately in `run_provenance`. It requires an
explicit `reference_build` and immutable `reference_version_or_digest`; the
latter is intentionally not a variant column. Idempotency is keyed by
`source_file_uri` plus `pipeline_version`, so a retry does not duplicate rows
while a reprocessing run with a new pipeline version remains distinguishable.

Classification is required at ingestion and is stored with run provenance and
the `variant_classification` sidecar. `records_with_classification()` exposes
the exact 20-field variant row plus its adjacent classification metadata
without adding a 21st column to `variant_records`. Classifications are
declared handling labels from the governed vocabulary; they are not inferred.

## Local/reference architecture evidence for tasks 7.9-7.10

The harness models a OneLake shortcut as metadata in `onelake_shortcuts`:
`onelake://...` resolves to one registered canonical ADLS URI in
`adls_artifacts`. The shortcut declaration does not copy the VCF. A variant
row keeps the supplied `source_file_uri`, while `resolve_source_file_uri`
returns the canonical ADLS URI, artifact identifier, shortcut name, and
current storage tier. Updating an artifact from `hot` to `cool` leaves the
canonical URI and artifact identity unchanged, demonstrating tier-independent
lineage locally.

The table layout is metadata, not a claim that SQLite or a deployed Delta
engine is clustering data. The default reference strategy is clustered on
`gene`, `sample_id`, and `cohort_id` with no physical partition columns; this
keeps the three governed query scopes inspectable without high-cardinality
partitions. `inspect_table_layout()` reports the strategy, columns, rationale,
and maintenance state. `record_maintenance()` records a local maintenance
operation and timestamp, and ingestion results include that snapshot.

These checks are runtime-generated synthetic tests only. They do not execute
OneLake, ADLS, Delta optimization, or Azure tiering, and they do not establish
cloud performance. A deployment must map this metadata model to its selected
Delta engine and Azure configuration before treating the behavior as live.

All identifiers used by the harness and tests are synthetic. No VCF or other
genomic payload is committed to the repository.
