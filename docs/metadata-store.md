# Local Genomic Metadata Store

The local SQLite model implements tasks 6.1 through 6.5: bidirectional lineage,
file metadata, referential integrity, archival, and persisted metadata-domain grants.
It is a trusted, single-machine development API, not a deployed service,
governed query endpoint or Delta variant store.
No Azure account, network connection or genomic payload is needed.

## Model

Entities have an immutable, globally unique `entity_id` and a `kind`.
Identifiers must match `SYN-[A-Z0-9][A-Z0-9_-]*`. This naming check does not
detect PHI: use invented identifiers only. No patient attributes are accepted.
Variant entities identify record occurrences, not globally deduplicated alleles.

| Kind | Required parents |
| --- | --- |
| `subject` | None |
| `sample` | Exactly one subject |
| `sequencing_run` | One or more samples |
| `fastq` | Exactly one sequencing run |
| `bam`, `cram` | One or more FASTQ artifacts |
| `vcf`, `gvcf` | One or more BAM/CRAM artifacts |
| `variant` | Exactly one VCF/GVCF artifact |

Every parent must exist before insertion. Inserts add the entity and all links
in one transaction; missing parents, duplicate identifiers and invalid stage
transitions are rejected. File details and links are immutable; only the archive
flag can change. No replace or delete API is exposed. SQLite
foreign keys are enabled on every store connection and restrict deletion of
referenced entities. Callers bypassing this API can alter the database; these
checks are not an authorization or tamper-resistance boundary.

Multiple parents preserve merged-file and joint-call ancestry. A multiplexed
run links all contributing samples. Traversal reports artifact ancestry, not
proof that an allele belongs to every contributing sample. Sample-specific
genotype attribution and demultiplexing provenance need the future pipeline
and variant ingestion integration; do not infer them from reachability.

`trace_subject` returns descendants; `trace_variant` returns ancestors. Both
include the requested root, deduplicate shared nodes, return deterministically
sorted entities and links, and read one consistent database snapshot. Unknown
or incorrectly typed roots raise `ValueError`. A disconnected subject is not
included, nor is a sibling variant when tracing upward from another variant.
These lineage methods are trusted operator APIs and expose subject linkage.
They are not principal-facing de-identified query methods.

## Metadata Domains And Grants

Research and clinical sample metadata are persisted in separate
`research_metadata` and `clinical_metadata` tables. The accepted fields are
intentionally narrow and synthetic:

| Domain | Accepted fields |
| --- | --- |
| Research | `assay_type`, `cohort_id`, `study_arm`, `study_id` |
| Clinical | `clinical_status`, `diagnosis_code`, `phenotype_code` |

Values must be scalar JSON values or null. Metadata is accepted only for an
existing synthetic sample. Direct identifiers and arbitrary attributes are not
accepted, so examples cannot add names, medical-record numbers, birth dates,
contact details, or other PHI-bearing fields.

`grant_access(principal_id, grant_name)` persists one explicit grant. Supported
grants are `research_metadata`, `clinical_metadata`, and `subject_linkage`;
principal identifiers must also use the `SYN-...` convention. Duplicate grants
are rejected by the database. `revoke_access` explicitly rejects a grant that
does not exist.

`read_sample_metadata(principal_id, sample_id)` returns only the domains granted
to that principal. A research-only principal receives `sample_id` and the
`research` object, with no `clinical` key and no subject identifier. A principal
with no metadata-domain grant receives `AuthorizationError`, rather than an
empty or partial success. The domain-specific read methods also raise
`AuthorizationError` when their exact grant is absent.

Subject linkage is never included in metadata projections. It is available only
through the separate `resolve_subject` operation and requires the independent
`subject_linkage` grant. This makes de-identified metadata access sample-scoped
even if the lineage graph contains a subject parent.

## File Details And Archival

Every new `fastq`, `bam`, `cram`, `vcf` or `gvcf` entity requires a
`file_metadata` dictionary with these fields:

| Field | Contract |
| --- | --- |
| `storage_uri` | Absolute `file`, `https` or `abfss` URI without credentials, query or fragment; recorded only, never opened |
| `analysis_stage` | `sequencing` for FASTQ, `alignment` for BAM/CRAM, `variant-calling` for VCF/GVCF |
| `producing_run` | Existing sequencing-run parent for FASTQ; registered pipeline-run ID for processed artifacts |
| `integrity_result` | Explicit `passed`, `failed` or `not-checked`; caller-reported, not verified by this API |
| `sha256` | Optional 64-character lowercase hexadecimal digest; recorded, not computed |

Sequencing-run producers are registered automatically. Register processing runs
with `add_pipeline_run(run_id, workflow_id, workflow_version)` before inserting
their artifacts. This registry records a producer identity and workflow version,
not the complete execution provenance or submission integration from task 5.5.
It does not establish that a pipeline actually ran or used the declared inputs.

`get_artifact(entity_id)` returns the file fields, kind, workflow identity and
version (null for sequencing runs), and an `archived` boolean. Invalid metadata
rolls back the entire entity and its parent links. File details cannot be
attached to subjects, samples, runs or individual variant records.

`archive_artifact(entity_id)` idempotently sets `archived` to true. URI,
producer, integrity fields and lineage links remain unchanged. Both trace
directions expose the flag in schema-version-2 entity records; archived
ancestors still resolve. This is metadata archival, not file deletion, blob
tiering, retention enforcement or access revocation. Legacy artifacts require
file-detail backfill before archival. There is no unarchive operation.

Opening a schema-version-1 or version-2 database upgrades it transactionally to
version 3 without fabricating missing file details or metadata grants. Its
lineage remains readable.
`get_artifact` rejects a legacy file until `backfill_file_metadata(entity_id,
metadata)` supplies validated details, once only. Register its pipeline producer
first when applicable. New file entries cannot omit details. Back up existing
databases before upgrading; older code cannot open the upgraded schema.

## Use Locally

Use Python 3.10+ from the repository root. The database path must be absolute,
on a trusted local filesystem, with an existing parent directory. The shared
local-path guard rejects UNC/device paths, relative paths and symlink/reparse
ancestors; on Windows it requires a fixed drive. It is not a race-proof sandbox
or a detector of every POSIX network mount. Keep databases outside source
control and separate from the scanner's inventory. Existing foreign databases
and unsupported schema versions are refused.

```python
from pathlib import Path
import tempfile

from scripts.metadata_store import MetadataStore

with tempfile.TemporaryDirectory() as directory:
    with MetadataStore(Path(directory) / "metadata.sqlite3") as store:
        store.add_entity("SYN-SUBJECT-001", "subject")
        store.add_entity("SYN-SAMPLE-001", "sample", ["SYN-SUBJECT-001"])
        store.add_entity("SYN-RUN-001", "sequencing_run", ["SYN-SAMPLE-001"])
        store.add_pipeline_run("SYN-PIPELINE-001", "synthetic-workflow", "1.0")
        for identifier, kind, parent, stage, producer in (
            ("SYN-FASTQ-001", "fastq", "SYN-RUN-001", "sequencing", "SYN-RUN-001"),
            ("SYN-BAM-001", "bam", "SYN-FASTQ-001", "alignment", "SYN-PIPELINE-001"),
            ("SYN-VCF-001", "vcf", "SYN-BAM-001", "variant-calling", "SYN-PIPELINE-001"),
        ):
            store.add_entity(identifier, kind, [parent], file_metadata={
                "storage_uri": f"file:///synthetic/{identifier}.{kind}",
                "analysis_stage": stage,
                "producing_run": producer,
                "integrity_result": "not-checked",
            })
        store.add_entity("SYN-VARIANT-001", "variant", ["SYN-VCF-001"])
        store.set_research_metadata("SYN-SAMPLE-001", {
            "cohort_id": "SYN-COHORT-001",
            "study_arm": "synthetic-case",
        })
        store.set_clinical_metadata("SYN-SAMPLE-001", {
            "clinical_status": "synthetic-observed",
        })
        store.grant_access("SYN-PRINCIPAL-RESEARCH", "research_metadata")
        projection = store.read_sample_metadata(
            "SYN-PRINCIPAL-RESEARCH", "SYN-SAMPLE-001"
        )
        assert "research" in projection
        assert "clinical" not in projection
        assert "subject_id" not in projection
        assert len(store.trace_subject("SYN-SUBJECT-001")["entities"]) == 7
        assert len(store.trace_variant("SYN-VARIANT-001")["links"]) == 6
        store.archive_artifact("SYN-VCF-001")
        assert store.get_artifact("SYN-VCF-001")["archived"]
        assert len(store.trace_variant("SYN-VARIANT-001")["links"]) == 6
```

The context manager closes the connection, including on failure. Use a separate
store connection per thread. This module is a Python API, not a CLI.

## Verification And Limits

```powershell
python -m unittest discover -s tests -p test_metadata_store.py -v
```

Twenty-five tests cover full-chain traversal in both directions, BAM/CRAM and
VCF/GVCF alternatives, shared ancestors, multiplexed runs, unrelated branches,
atomic rejection of a missing sample, stage and identifier validation, database
foreign keys, persistence, path guards and snapshot consistency during a write.
They also cover complete file-detail retrieval, invalid metadata rollback,
producer typing, legacy backfill, archival, and concurrent archive/read behavior.
Focused access tests verify separate persisted metadata tables and grants,
research-only projection without clinical attributes or subject linkage,
explicit authorization errors, and rejection of unapproved metadata fields.
Fixtures are synthetic metadata generated in temporary directories, not the
future Platinum Genomes demo dataset or actual pipeline outputs.

Audit, service authentication, a deployed server-side authorization boundary,
and Delta/Purview integration remain pending. Direct database access can bypass
this Python API, so protect the database with local filesystem controls and do
not expose trusted lineage methods to analysts. Graph reachability does not
establish transfer integrity, validate FASTQ, or provide biological evidence.

The metadata store does not change scanner completeness, transfer-failure
classification, or authorize staging. Azure readiness is explicitly
`not-evaluated` in every trace response.