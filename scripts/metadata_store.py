import json
import re
import sqlite3
from urllib.parse import unquote, urlsplit

from scripts.scan_landing import local_path
from scripts.validate_submission import fields, text
from scripts.governance import AuthorizationError, GovernancePolicy, synthetic_id


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
METADATA_DOMAINS = frozenset({"research", "clinical"})
ACCESS_GRANTS = frozenset({"research_metadata", "clinical_metadata", "subject_linkage"})
METADATA_FIELDS = {
    "research": frozenset({"assay_type", "cohort_id", "study_arm", "study_id"}),
    "clinical": frozenset({"clinical_status", "diagnosis_code", "phenotype_code"}),
}


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
            elif application != APPLICATION_ID or version not in {1, 2, 3}:
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
            if version < 3:
                with self._connection:
                    self._connection.execute("BEGIN IMMEDIATE")
                    for domain in METADATA_DOMAINS:
                        self._connection.execute(f"""
                            CREATE TABLE IF NOT EXISTS {domain}_metadata (
                                sample_id TEXT PRIMARY KEY NOT NULL
                                    REFERENCES entities(entity_id) ON DELETE RESTRICT,
                                attributes_json TEXT NOT NULL
                            )
                        """)
                    self._connection.execute("""
                        CREATE TABLE IF NOT EXISTS access_grants (
                            principal_id TEXT NOT NULL,
                            grant_name TEXT NOT NULL CHECK (grant_name IN (
                                'research_metadata', 'clinical_metadata', 'subject_linkage'
                            )),
                            PRIMARY KEY (principal_id, grant_name)
                        )
                    """)
                    self._connection.execute("PRAGMA user_version = 3")
            self.governance = GovernancePolicy(self._connection)
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

    def add_pipeline_run(self, run_id, workflow_id, workflow_version,
                         principal_id="SYN-SYSTEM-PIPELINE"):
        synthetic_id(run_id)
        synthetic_id(principal_id, "principal_id")
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
            self.governance.record_pipeline_execution(
                principal_id, run_id, workflow_id=workflow_id,
                workflow_version=workflow_version, outcome="registered",
            )

    def set_research_metadata(self, sample_id, attributes):
        self._set_metadata("research", sample_id, attributes)

    def set_clinical_metadata(self, sample_id, attributes):
        self._set_metadata("clinical", sample_id, attributes)

    def _set_metadata(self, domain, sample_id, attributes):
        synthetic_id(sample_id)
        if domain not in METADATA_DOMAINS:
            raise ValueError("Unsupported metadata domain.")
        if not isinstance(attributes, dict) or not attributes:
            raise ValueError("Metadata attributes must be a non-empty dictionary.")
        if set(attributes) - METADATA_FIELDS[domain]:
            raise ValueError(f"Unsupported {domain} metadata attribute.")
        for key, value in attributes.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"{key} must be a scalar value or null.")
        payload = json.dumps(
            attributes, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        with self._connection:
            sample = self._connection.execute(
                "SELECT kind FROM entities WHERE entity_id = ?", (sample_id,)
            ).fetchone()
            if sample is None or sample["kind"] != "sample":
                raise ValueError(f"No sample with identifier: {sample_id}")
            self._connection.execute(
                f"""INSERT INTO {domain}_metadata (sample_id, attributes_json) VALUES (?, ?)
                    ON CONFLICT(sample_id) DO UPDATE
                    SET attributes_json = excluded.attributes_json""",
                (sample_id, payload),
            )

    def grant_access(self, principal_id, grant_name):
        synthetic_id(principal_id)
        if grant_name not in ACCESS_GRANTS:
            raise ValueError("Unsupported metadata grant.")
        with self._connection:
            self._connection.execute(
                "INSERT INTO access_grants (principal_id, grant_name) VALUES (?, ?)",
                (principal_id, grant_name),
            )

    def revoke_access(self, principal_id, grant_name):
        synthetic_id(principal_id)
        if grant_name not in ACCESS_GRANTS:
            raise ValueError("Unsupported metadata grant.")
        with self._connection:
            result = self._connection.execute(
                "DELETE FROM access_grants WHERE principal_id = ? AND grant_name = ?",
                (principal_id, grant_name),
            )
            if result.rowcount != 1:
                raise ValueError("Metadata grant does not exist.")

    def read_sample_metadata(self, principal_id, sample_id):
        grants = self._grants(principal_id)
        domains = [
            domain for domain in ("research", "clinical")
            if f"{domain}_metadata" in grants
        ]
        if not domains:
            raise AuthorizationError(
                f"Principal {principal_id} has no metadata-domain grant."
            )
        self._sample(sample_id)
        result = {"sample_id": sample_id}
        for domain in domains:
            row = self._connection.execute(
                f"SELECT attributes_json FROM {domain}_metadata WHERE sample_id = ?",
                (sample_id,),
            ).fetchone()
            result[domain] = json.loads(row["attributes_json"]) if row else None
        self.governance.audit.record(
            "data_access", principal_id, "read_sample_metadata",
            {"sample_id": sample_id, "domains": domains, "subject_linked": False},
        )
        return result

    def read_research_metadata(self, principal_id, sample_id):
        return self._read_domain_metadata(principal_id, sample_id, "research")

    def read_clinical_metadata(self, principal_id, sample_id):
        return self._read_domain_metadata(principal_id, sample_id, "clinical")

    def _read_domain_metadata(self, principal_id, sample_id, domain):
        self._require_grant(principal_id, f"{domain}_metadata")
        self._sample(sample_id)
        row = self._connection.execute(
            f"SELECT attributes_json FROM {domain}_metadata WHERE sample_id = ?",
            (sample_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No {domain} metadata for sample: {sample_id}")
        result = json.loads(row["attributes_json"])
        self.governance.audit.record(
            "data_access", principal_id, f"read_{domain}_metadata",
            {"sample_id": sample_id, "domain": domain, "subject_linked": domain == "clinical"},
        )
        return result

    def resolve_subject(self, principal_id, sample_id):
        self._require_grant(principal_id, "subject_linkage")
        self._sample(sample_id)
        subject = self._connection.execute("""
            SELECT parent_id FROM links
            JOIN entities ON entities.entity_id = links.parent_id
            WHERE child_id = ? AND entities.kind = 'subject'
        """, (sample_id,)).fetchone()
        if subject is None:
            raise ValueError(f"Sample has no subject linkage: {sample_id}")
        self.governance.audit.record(
            "data_access", principal_id, "resolve_subject",
            {"sample_id": sample_id, "subject_linked": True},
        )
        return subject["parent_id"]

    def grant_tier(self, principal_id, access_tier):
        self.governance.grant_tier(principal_id, access_tier)

    def revoke_tier(self, principal_id, access_tier):
        self.governance.revoke_tier(principal_id, access_tier)

    def grant_capability(self, principal_id, capability):
        self.governance.grant_capability(principal_id, capability)

    def grant_workspace(self, principal_id, workspace):
        self.governance.grant_workspace(principal_id, workspace)

    def transfer_workspace(self, principal_id, source, destination, dataset, approval_id=None):
        return self.governance.transfer_workspace(
            principal_id, source, destination, dataset, approval_id
        )

    def record_reprocessing(self, principal_id, sample_id, prior_pipeline_version,
                            new_pipeline_version):
        return self.governance.record_reprocessing(
            principal_id, sample_id, prior_pipeline_version, new_pipeline_version
        )

    def authorize_raw_file(self, principal_id, artifact_uri):
        return self.governance.authorize_raw_file(principal_id, artifact_uri)

    def authorize_variant_store(self, principal_id):
        return self.governance.authorize_variant_store(principal_id)

    def read_cohort_aggregates(self, principal_id, aggregate):
        return self.governance.read_cohort_aggregates(principal_id, aggregate)

    def audit_entries(self):
        return self.governance.audit.entries()

    def verify_audit(self):
        return self.governance.audit.verify()

    def _sample(self, sample_id):
        synthetic_id(sample_id)
        sample = self._connection.execute(
            "SELECT kind FROM entities WHERE entity_id = ?", (sample_id,)
        ).fetchone()
        if sample is None or sample["kind"] != "sample":
            raise ValueError(f"No sample with identifier: {sample_id}")

    def _grants(self, principal_id):
        synthetic_id(principal_id)
        return {
            row["grant_name"] for row in self._connection.execute(
                "SELECT grant_name FROM access_grants WHERE principal_id = ?",
                (principal_id,),
            )
        }

    def _require_grant(self, principal_id, grant_name):
        if grant_name not in self._grants(principal_id):
            raise AuthorizationError(
                f"Principal {principal_id} is not authorized for {grant_name}."
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