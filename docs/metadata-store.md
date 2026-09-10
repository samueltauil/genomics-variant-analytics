# Local Genomic Metadata Store

The local SQLite model implements tasks 6.1 and 6.3: bidirectional lineage
and referential integrity. It is a trusted, single-machine development API,
not a deployed service, governed query endpoint or Delta variant store.
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
transitions are rejected. No replace, update or delete API is exposed. SQLite
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
        store.add_entity("SYN-FASTQ-001", "fastq", ["SYN-RUN-001"])
        store.add_entity("SYN-BAM-001", "bam", ["SYN-FASTQ-001"])
        store.add_entity("SYN-VCF-001", "vcf", ["SYN-BAM-001"])
        store.add_entity("SYN-VARIANT-001", "variant", ["SYN-VCF-001"])
        assert len(store.trace_subject("SYN-SUBJECT-001")["entities"]) == 7
        assert len(store.trace_variant("SYN-VARIANT-001")["links"]) == 6
```

The context manager closes the connection, including on failure. Use a separate
store connection per thread. This module is a Python API, not a CLI.

## Verification And Limits

```powershell
python -m unittest discover -s tests -p test_metadata_store.py -v
```

Thirteen tests cover full-chain traversal in both directions, BAM/CRAM and
VCF/GVCF alternatives, shared ancestors, multiplexed runs, unrelated branches,
atomic rejection of a missing sample, stage and identifier validation, database
foreign keys, persistence, path guards and snapshot consistency during a write.
Fixtures are synthetic metadata generated in temporary directories, not the
future Platinum Genomes demo dataset or actual pipeline outputs.

File URI, producing workflow run and integrity attributes (6.2), archive
semantics (6.4), clinical/research grants (6.5), subject-linkage authorization,
audit and Delta/Purview integration remain pending. This API returns subject
linkage and must not be exposed to analysts. Protect the database and any
printed reports with local filesystem controls. Graph reachability does not
establish transfer integrity, validate FASTQ, or provide biological evidence.

Task 2.3 remains blocked on a trusted transfer-failure contract. The metadata
store does not change scanner completeness or authorize staging. Azure
readiness is explicitly `not-evaluated` in every trace response.