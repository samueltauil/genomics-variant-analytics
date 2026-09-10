import re
import sqlite3

from scripts.scan_landing import local_path


PARENT_KINDS = {
    "subject": frozenset(),
    "sample": frozenset({"subject"}),
    "sequencing_run": frozenset({"sample"}),
    "fastq": frozenset({"sequencing_run"}),
    "bam": frozenset({"fastq"}),
    "cram": frozenset({"fastq"}),
    "vcf": frozenset({"bam", "cram"}),
    "gvcf": frozenset({"bam", "cram"}),
    "variant": frozenset({"vcf", "gvcf"}),
}
APPLICATION_ID = 0x47564D31


def synthetic_id(value):
    if not isinstance(value, str) or re.fullmatch(r"SYN-[A-Z0-9][A-Z0-9_-]*", value) is None:
        raise ValueError("Metadata identifiers must match SYN-[A-Z0-9][A-Z0-9_-]*.")
    return value


class MetadataStore:
    def __init__(self, database):
        self._connection = sqlite3.connect(local_path(database))
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            application = self._connection.execute("PRAGMA application_id").fetchone()[0]
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            tables = self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if application == 0 and version == 0 and not tables:
                with self._connection:
                    self._connection.execute("""
                        CREATE TABLE entities (
                            entity_id TEXT PRIMARY KEY NOT NULL,
                            kind TEXT NOT NULL CHECK (kind IN (
                                'subject', 'sample', 'sequencing_run', 'fastq',
                                'bam', 'cram', 'vcf', 'gvcf', 'variant'
                            ))
                        )
                    """)
                    self._connection.execute("""
                        CREATE TABLE links (
                            parent_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE RESTRICT,
                            child_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE RESTRICT,
                            PRIMARY KEY (parent_id, child_id),
                            CHECK (parent_id <> child_id)
                        )
                    """)
                    self._connection.execute("CREATE INDEX links_child ON links(child_id)")
                    self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                    self._connection.execute("PRAGMA user_version = 1")
            elif application != APPLICATION_ID or version != 1:
                raise ValueError("Database is not a supported genomic metadata store.")
        except Exception:
            self._connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        self.close()

    def close(self):
        self._connection.close()

    def add_entity(self, entity_id, kind, parents=()):
        synthetic_id(entity_id)
        if not isinstance(kind, str) or kind not in PARENT_KINDS:
            raise ValueError("Unsupported metadata entity kind.")
        if not isinstance(parents, (list, tuple)):
            raise ValueError("Parents must be a list or tuple of identifiers.")
        for parent_id in parents:
            synthetic_id(parent_id)
        if len(set(parents)) != len(parents):
            raise ValueError("Parent identifiers must be unique.")
        if kind == "subject" and parents:
            raise ValueError("A subject cannot have parents.")
        if kind != "subject" and not parents:
            raise ValueError("Non-subject entities require existing parents.")
        if kind in {"sample", "fastq", "variant"} and len(parents) != 1:
            raise ValueError("Samples, FASTQ files and variant occurrences require exactly one parent.")
        with self._connection:
            for parent_id in parents:
                parent = self._connection.execute(
                    "SELECT kind FROM entities WHERE entity_id = ?", (parent_id,)
                ).fetchone()
                if parent is None:
                    raise ValueError(f"Missing parent: {parent_id}")
                if parent["kind"] not in PARENT_KINDS[kind]:
                    raise ValueError(f"Invalid lineage link: {parent['kind']} -> {kind}")
            self._connection.execute(
                "INSERT INTO entities (entity_id, kind) VALUES (?, ?)", (entity_id, kind)
            )
            self._connection.executemany(
                "INSERT INTO links (parent_id, child_id) VALUES (?, ?)",
                [(parent_id, entity_id) for parent_id in parents],
            )

    def trace_subject(self, subject_id):
        return self._trace(subject_id, "subject", "down")

    def trace_variant(self, variant_id):
        return self._trace(variant_id, "variant", "up")

    def _trace(self, entity_id, expected_kind, direction):
        synthetic_id(entity_id)
        match = self._connection.execute(
            "SELECT kind FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if match is None or match["kind"] != expected_kind:
            raise ValueError(f"No {expected_kind} with identifier: {entity_id}")
        start, destination = (
            ("parent_id", "child_id") if direction == "down" else ("child_id", "parent_id")
        )
        closure = f"""
            WITH RECURSIVE traced(entity_id) AS (
                SELECT entity_id FROM entities WHERE entity_id = ?
                UNION
                SELECT links.{destination} FROM links
                JOIN traced ON links.{start} = traced.entity_id
            )
        """
        with self._connection:
            self._connection.execute("BEGIN")
            entities = self._connection.execute(
                closure + """
                    SELECT entities.entity_id, entities.kind FROM entities
                    JOIN traced USING (entity_id) ORDER BY entities.entity_id
                """, (entity_id,)
            ).fetchall()
            links = self._connection.execute(
                closure + """
                    SELECT parent_id, child_id FROM links
                    WHERE parent_id IN (SELECT entity_id FROM traced)
                      AND child_id IN (SELECT entity_id FROM traced)
                    ORDER BY parent_id, child_id
                """, (entity_id,)
            ).fetchall()
        return {
            "schema_version": 1,
            "mode": "local-only",
            "root_id": entity_id,
            "direction": direction,
            "entities": [dict(entity) for entity in entities],
            "links": [dict(link) for link in links],
            "azure_readiness": "not-evaluated",
        }