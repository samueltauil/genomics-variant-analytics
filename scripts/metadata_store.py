import re
import sqlite3
from urllib.parse import unquote, urlsplit

from scripts.scan_landing import local_path
from scripts.validate_submission import fields, text


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
FILE_STAGES = {
    "fastq": "sequencing", "bam": "alignment", "cram": "alignment",
    "vcf": "variant-calling", "gvcf": "variant-calling",
}


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
            elif application != APPLICATION_ID or version not in {1, 2}:
                raise ValueError("Database is not a supported genomic metadata store.")
            if version < 2:
                with self._connection:
                    self._connection.execute("BEGIN IMMEDIATE")
                    self._connection.execute("""
                        CREATE TABLE producing_runs (
                            run_id TEXT PRIMARY KEY NOT NULL,
                            sequencing_run_id TEXT REFERENCES entities(entity_id) ON DELETE RESTRICT,
                            workflow_id TEXT,
                            workflow_version TEXT,
                            CHECK ((sequencing_run_id IS NOT NULL AND workflow_id IS NULL
                                    AND workflow_version IS NULL)
                                OR (sequencing_run_id IS NULL AND workflow_id IS NOT NULL
                                    AND workflow_version IS NOT NULL))
                        )
                    """)
                    self._connection.execute("""
                        INSERT INTO producing_runs (run_id, sequencing_run_id)
                        SELECT entity_id, entity_id FROM entities WHERE kind = 'sequencing_run'
                    """)
                    self._connection.execute("""
                        CREATE TABLE file_metadata (
                            entity_id TEXT PRIMARY KEY NOT NULL
                                REFERENCES entities(entity_id) ON DELETE RESTRICT,
                            storage_uri TEXT NOT NULL,
                            analysis_stage TEXT NOT NULL CHECK (analysis_stage IN (
                                'sequencing', 'alignment', 'variant-calling')),
                            producing_run TEXT NOT NULL REFERENCES producing_runs(run_id) ON DELETE RESTRICT,
                            integrity_result TEXT NOT NULL CHECK (integrity_result IN (
                                'passed', 'failed', 'not-checked')),
                            sha256 TEXT,
                            archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
                        )
                    """)
                    self._connection.execute("PRAGMA user_version = 2")
        except Exception:
            self._connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        self.close()

    def close(self):
        self._connection.close()

    def add_entity(self, entity_id, kind, parents=(), *, file_metadata=None):
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
        if kind in FILE_STAGES and file_metadata is None:
            raise ValueError("File artifacts require file metadata.")
        if kind not in FILE_STAGES and file_metadata is not None:
            raise ValueError("Only file artifacts accept file metadata.")
        with self._connection:
            if self._connection.execute(
                "SELECT 1 FROM producing_runs WHERE run_id = ?", (entity_id,)
            ).fetchone():
                raise ValueError("Identifier already registered as a producing run.")
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
            if kind == "sequencing_run":
                self._connection.execute(
                    "INSERT INTO producing_runs (run_id, sequencing_run_id) VALUES (?, ?)",
                    (entity_id, entity_id),
                )
            if kind in FILE_STAGES:
                self._insert_file_metadata(entity_id, kind, file_metadata)

    def add_pipeline_run(self, run_id, workflow_id, workflow_version):
        synthetic_id(run_id)
        text(workflow_id, "workflow_id")
        text(workflow_version, "workflow_version")
        with self._connection:
            if self._connection.execute(
                "SELECT 1 FROM entities WHERE entity_id = ?", (run_id,)
            ).fetchone():
                raise ValueError("Identifier already registered as a lineage entity.")
            self._connection.execute(
                "INSERT INTO producing_runs (run_id, workflow_id, workflow_version) VALUES (?, ?, ?)",
                (run_id, workflow_id, workflow_version),
            )

    def _insert_file_metadata(self, entity_id, kind, metadata):
        required = {"storage_uri", "analysis_stage", "producing_run", "integrity_result"}
        expected = required | ({"sha256"} if isinstance(metadata, dict) and "sha256" in metadata else set())
        fields(metadata, expected, "File metadata")
        location = text(metadata["storage_uri"], "storage_uri")
        uri = urlsplit(location)
        if (uri.scheme not in {"file", "https", "abfss"} or not uri.path.startswith("/")
                or uri.path == "/" or uri.query or uri.fragment or uri.password
                or (uri.scheme == "file" and uri.netloc not in {"", "localhost"})
                or (uri.scheme != "file" and not uri.hostname)
                or (uri.scheme == "https" and uri.username)
                or (uri.scheme == "abfss" and not uri.username)
                or any(character.isspace() or ord(character) < 32 for character in location)
                or "\\" in location or "\\" in unquote(uri.path)
                or any(part in {".", ".."} for part in unquote(uri.path).split("/"))):
            raise ValueError("Storage URI must be an absolute credential-free file, HTTPS or ABFSS location.")
        if metadata["analysis_stage"] != FILE_STAGES[kind]:
            raise ValueError("Analysis stage does not match artifact kind.")
        if metadata["integrity_result"] not in ("passed", "failed", "not-checked"):
            raise ValueError("Integrity result must be passed, failed or not-checked.")
        checksum = metadata.get("sha256")
        if "sha256" in metadata and (
            not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters.")
        run_id = synthetic_id(metadata["producing_run"])
        producer = self._connection.execute(
            "SELECT sequencing_run_id FROM producing_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if producer is None:
            raise ValueError("Producing run does not exist.")
        if kind == "fastq":
            parent = self._connection.execute(
                "SELECT parent_id FROM links WHERE child_id = ?", (entity_id,)
            ).fetchone()
            if producer["sequencing_run_id"] != parent["parent_id"]:
                raise ValueError("FASTQ producer must be its sequencing-run parent.")
        elif producer["sequencing_run_id"] is not None:
            raise ValueError("Processed artifacts require a pipeline run.")
        self._connection.execute(
            """INSERT INTO file_metadata
               (entity_id, storage_uri, analysis_stage, producing_run, integrity_result, sha256)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_id, location, metadata["analysis_stage"], run_id, metadata["integrity_result"], checksum),
        )

    def backfill_file_metadata(self, entity_id, metadata):
        synthetic_id(entity_id)
        with self._connection:
            entity = self._connection.execute(
                "SELECT kind FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if entity is None or entity["kind"] not in FILE_STAGES:
                raise ValueError("No file artifact with this identifier.")
            self._insert_file_metadata(entity_id, entity["kind"], metadata)

    def get_artifact(self, entity_id):
        synthetic_id(entity_id)
        artifact = self._connection.execute("""
            SELECT entities.entity_id, entities.kind, file_metadata.storage_uri,
                   file_metadata.analysis_stage, file_metadata.producing_run,
                     file_metadata.integrity_result, file_metadata.sha256, file_metadata.archived,
                   producing_runs.workflow_id, producing_runs.workflow_version
            FROM file_metadata JOIN entities USING (entity_id)
            JOIN producing_runs ON file_metadata.producing_run = producing_runs.run_id
            WHERE entity_id = ?
        """, (entity_id,)).fetchone()
        if artifact is None:
            raise ValueError("Artifact is missing or requires legacy file-metadata backfill.")
        return {**dict(artifact), "archived": bool(artifact["archived"])}

    def archive_artifact(self, entity_id):
        synthetic_id(entity_id)
        with self._connection:
            updated = self._connection.execute(
                "UPDATE file_metadata SET archived = 1 WHERE entity_id = ?", (entity_id,)
            )
            if updated.rowcount != 1:
                raise ValueError("Artifact is missing or requires legacy file-metadata backfill.")

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
                          SELECT entities.entity_id, entities.kind,
                              COALESCE(file_metadata.archived, 0) AS archived FROM entities
                          JOIN traced USING (entity_id)
                          LEFT JOIN file_metadata USING (entity_id) ORDER BY entities.entity_id
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
            "schema_version": 2,
            "mode": "local-only",
            "root_id": entity_id,
            "direction": direction,
            "entities": [{**dict(entity), "archived": bool(entity["archived"])} for entity in entities],
            "links": [dict(link) for link in links],
            "azure_readiness": "not-evaluated",
        }