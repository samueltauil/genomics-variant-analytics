from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.metadata_store import AuthorizationError, FILE_STAGES, MetadataStore


class MetadataStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "metadata.sqlite3"
        self.store = MetadataStore(self.database)
        self.addCleanup(self.store.close)

    def file_details(self, entity_id, kind, run_id="SYN-PIPELINE-001"):
        return {
            "storage_uri": f"file:///synthetic/{entity_id}.{kind}",
            "analysis_stage": FILE_STAGES[kind],
            "producing_run": run_id,
            "integrity_result": "not-checked",
        }

    def add_artifact(self, entity_id, kind, parents, run_id="SYN-PIPELINE-001"):
        if kind == "fastq":
            run_id = parents[0]
        self.store.add_entity(entity_id, kind, parents,
                              file_metadata=self.file_details(entity_id, kind, run_id))

    def seed_chain(self, suffix="001", aligned_kind="bam", variant_kind="vcf"):
        self.store.add_pipeline_run(f"SYN-PIPELINE-{suffix}", "synthetic-workflow", "1.0")
        chain = [
            (f"SYN-SUBJECT-{suffix}", "subject"),
            (f"SYN-SAMPLE-{suffix}", "sample"),
            (f"SYN-RUN-{suffix}", "sequencing_run"),
            (f"SYN-FASTQ-{suffix}", "fastq"),
            (f"SYN-ALIGNED-{suffix}", aligned_kind),
            (f"SYN-VCF-{suffix}", variant_kind),
            (f"SYN-VARIANT-{suffix}", "variant"),
        ]
        parents = ()
        for entity_id, kind in chain:
            if kind in FILE_STAGES:
                self.add_artifact(entity_id, kind, parents, f"SYN-PIPELINE-{suffix}")
            else:
                self.store.add_entity(entity_id, kind, parents)
            parents = (entity_id,)
        return {entity_id for entity_id, _ in chain}

    def test_full_chain_is_traversable_in_both_directions_without_payload_reads(self):
        with patch.object(Path, "open", side_effect=AssertionError("No genomic payload reads")):
            expected = self.seed_chain()
            downward = self.store.trace_subject("SYN-SUBJECT-001")
            upward = self.store.trace_variant("SYN-VARIANT-001")
        for report in (downward, upward):
            self.assertEqual({entry["entity_id"] for entry in report["entities"]}, expected)
            self.assertEqual(len(report["links"]), 6)
            self.assertEqual(report["mode"], "local-only")
            self.assertEqual(report["azure_readiness"], "not-evaluated")
        self.assertEqual(downward["entities"], upward["entities"])
        self.assertEqual(downward["links"], upward["links"])

    def test_cram_and_gvcf_are_supported(self):
        expected = self.seed_chain(aligned_kind="cram", variant_kind="gvcf")
        report = self.store.trace_variant("SYN-VARIANT-001")
        self.assertEqual({entry["entity_id"] for entry in report["entities"]}, expected)

    def test_disconnected_subjects_and_sibling_variants_are_not_upward_ancestors(self):
        expected = self.seed_chain()
        self.seed_chain("002")
        self.store.add_entity("SYN-VARIANT-SIBLING", "variant", ["SYN-VCF-001"])
        upward = self.store.trace_variant("SYN-VARIANT-001")
        downward = self.store.trace_subject("SYN-SUBJECT-001")
        self.assertEqual({entry["entity_id"] for entry in upward["entities"]}, expected)
        self.assertEqual({entry["entity_id"] for entry in downward["entities"]},
                         expected | {"SYN-VARIANT-SIBLING"})

    def test_multiple_inputs_are_deduplicated_and_joint_ancestry_is_preserved(self):
        first = self.seed_chain()
        second = self.seed_chain("002")
        self.add_artifact("SYN-FASTQ-MATE", "fastq", ["SYN-RUN-001"])
        self.add_artifact("SYN-MERGED-BAM", "bam", ["SYN-FASTQ-001", "SYN-FASTQ-MATE"])
        self.add_artifact("SYN-JOINT-VCF", "vcf", ["SYN-MERGED-BAM", "SYN-ALIGNED-002"])
        self.store.add_entity("SYN-JOINT-VARIANT", "variant", ["SYN-JOINT-VCF"])
        report = self.store.trace_variant("SYN-JOINT-VARIANT")
        identifiers = [entry["entity_id"] for entry in report["entities"]]
        excluded = {"SYN-ALIGNED-001", "SYN-VCF-001", "SYN-VCF-002",
                    "SYN-VARIANT-001", "SYN-VARIANT-002"}
        self.assertEqual(set(identifiers), (first | second) - excluded | {
            "SYN-FASTQ-MATE", "SYN-MERGED-BAM", "SYN-JOINT-VCF", "SYN-JOINT-VARIANT",
        })
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_multiplexed_run_accepts_multiple_sample_parents(self):
        self.store.add_entity("SYN-SUBJECT-001", "subject")
        for sample_id in ("SYN-SAMPLE-001", "SYN-SAMPLE-002"):
            self.store.add_entity(sample_id, "sample", ["SYN-SUBJECT-001"])
        self.store.add_entity("SYN-RUN-001", "sequencing_run", ["SYN-SAMPLE-001", "SYN-SAMPLE-002"])
        report = self.store.trace_subject("SYN-SUBJECT-001")
        self.assertEqual(len(report["entities"]), 4)
        self.assertEqual(len(report["links"]), 4)

    def test_missing_sample_is_rejected_without_partial_entity_or_link(self):
        self.store.add_entity("SYN-SUBJECT-001", "subject")
        self.store.add_entity("SYN-SAMPLE-001", "sample", ["SYN-SUBJECT-001"])
        with self.assertRaisesRegex(ValueError, "Missing parent"):
            self.store.add_entity("SYN-RUN-001", "sequencing_run", ["SYN-SAMPLE-001", "SYN-MISSING"])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)

    def test_invalid_stages_parent_counts_and_identifiers_are_rejected(self):
        self.seed_chain()
        cases = [
            ("real-id", "subject", []),
            ("SYN-NEW", "unknown", []),
            ("SYN-NEW", "sample", []),
            ("SYN-NEW", "subject", ["SYN-SUBJECT-001"]),
            ("SYN-NEW", "sample", ["SYN-SUBJECT-001", "SYN-SUBJECT-001"]),
            ("SYN-NEW", "sample", "SYN-SUBJECT-001"),
            ("SYN-NEW", "vcf", ["SYN-FASTQ-001"]),
            ("SYN-NEW", "fastq", ["SYN-ALIGNED-001"]),
            ("SYN-NEW", "variant", ["SYN-MISSING"]),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.store.add_entity(*arguments)

    def test_duplicate_entity_does_not_replace_lineage(self):
        self.seed_chain()
        before = self.store.trace_subject("SYN-SUBJECT-001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_entity("SYN-VARIANT-001", "subject")
        self.assertEqual(self.store.trace_subject("SYN-SUBJECT-001"), before)

    def test_database_foreign_keys_reject_dangling_links_and_parent_deletion(self):
        self.seed_chain()
        self.assertEqual(self.store._connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError), self.store._connection:
            self.store._connection.execute(
                "INSERT INTO links VALUES (?, ?)", ("SYN-MISSING", "SYN-SAMPLE-001")
            )
        with self.assertRaises(sqlite3.IntegrityError), self.store._connection:
            self.store._connection.execute("DELETE FROM entities WHERE entity_id = ?", ("SYN-VCF-001",))
        self.assertEqual(len(self.store.trace_variant("SYN-VARIANT-001")["entities"]), 7)

    def test_store_reopens_with_identical_trace(self):
        self.seed_chain()
        expected = self.store.trace_variant("SYN-VARIANT-001")
        self.store.close()
        with MetadataStore(self.database) as reopened:
            self.assertEqual(reopened.trace_variant("SYN-VARIANT-001"), expected)

    def test_trace_uses_one_snapshot_during_concurrent_append(self):
        self.seed_chain()
        self.store._connection.execute("PRAGMA journal_mode = WAL")
        with MetadataStore(self.database) as writer:
            appended = False

            def append_between_queries(statement):
                nonlocal appended
                if "SELECT parent_id, child_id FROM links" in statement and not appended:
                    appended = True
                    writer.add_entity("SYN-CONCURRENT", "variant", ["SYN-VCF-001"])

            self.store._connection.set_trace_callback(append_between_queries)
            try:
                report = self.store.trace_subject("SYN-SUBJECT-001")
            finally:
                self.store._connection.set_trace_callback(None)
        self.assertTrue(appended)
        self.assertEqual(len(report["entities"]), 7)
        self.assertEqual(len(report["links"]), 6)
        self.assertEqual(len(self.store.trace_subject("SYN-SUBJECT-001")["entities"]), 8)

    def test_unknown_and_wrong_kind_trace_roots_are_rejected(self):
        self.seed_chain()
        for trace, identifier in ((self.store.trace_variant, "SYN-MISSING"),
                                  (self.store.trace_variant, "SYN-SUBJECT-001"),
                                  (self.store.trace_subject, "SYN-VARIANT-001")):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                trace(identifier)

    def test_every_artifact_has_persisted_file_details_without_payload_access(self):
        with patch.object(Path, "open", side_effect=AssertionError("No payload reads")):
            self.seed_chain()
            self.seed_chain("002", aligned_kind="cram", variant_kind="gvcf")
            for subject in ("SYN-SUBJECT-001", "SYN-SUBJECT-002"):
                for entity in self.store.trace_subject(subject)["entities"]:
                    if entity["kind"] not in FILE_STAGES:
                        continue
                    artifact = self.store.get_artifact(entity["entity_id"])
                    for field in ("storage_uri", "analysis_stage", "producing_run", "integrity_result"):
                        self.assertTrue(artifact[field])
                    self.assertEqual(artifact["analysis_stage"], FILE_STAGES[entity["kind"]])
                    with MetadataStore(self.database) as reopened:
                        self.assertEqual(reopened.get_artifact(entity["entity_id"]), artifact)

    def test_invalid_file_metadata_rolls_back_artifact_and_links(self):
        self.seed_chain()
        valid = self.file_details("SYN-NEW", "bam")
        cases = [None, {}, {**valid, "unexpected": 1}]
        cases.extend({**valid, "storage_uri": uri} for uri in (
            "relative.bam", "file:relative.bam", "http://synthetic.invalid/file",
            "https://user:secret@synthetic.invalid/file", "https://synthetic.invalid/file?sig=secret",
            "https://synthetic.invalid/file#fragment", "file://remote.invalid/share/file",
            "file:///synthetic/%2e%2e/file", "https://synthetic.invalid/white space",
        ))
        cases.extend({**valid, field: value} for field, value in (
            ("analysis_stage", "sequencing"), ("integrity_result", "maybe"),
            ("sha256", "invalid"), ("sha256", None),
            ("producing_run", "SYN-MISSING"), ("producing_run", "SYN-RUN-001"),
        ))
        before = self.store.trace_subject("SYN-SUBJECT-001")
        for metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.store.add_entity("SYN-NEW", "bam", ["SYN-FASTQ-001"], file_metadata=metadata)
            self.assertEqual(self.store.trace_subject("SYN-SUBJECT-001"), before)
        with self.assertRaises(ValueError):
            self.store.add_entity("SYN-SUBJECT-NEW", "subject", file_metadata=valid)

    def test_file_integrity_results_and_uris_are_recorded_not_inferred(self):
        self.seed_chain()
        for index, result in enumerate(("passed", "failed", "not-checked")):
            entity_id = f"SYN-FILE-{index}"
            metadata = self.file_details(entity_id, "bam")
            metadata.update(storage_uri=(
                "file:///synthetic/output.bam", "https://synthetic.invalid/output.bam",
                "abfss://container@synthetic.invalid/output.bam",
            )[index], integrity_result=result, sha256="a" * 64)
            self.store.add_entity(entity_id, "bam", ["SYN-FASTQ-001"], file_metadata=metadata)
            artifact = self.store.get_artifact(entity_id)
            for field, value in metadata.items():
                self.assertEqual(artifact[field], value)
            self.assertEqual(artifact["workflow_version"], "1.0")

    def test_producing_runs_are_typed_existing_and_immutable(self):
        self.seed_chain()
        self.seed_chain("002")
        for run_id in ("SYN-RUN-002", "SYN-PIPELINE-001"):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.store.add_entity("SYN-NEW", "fastq", ["SYN-RUN-001"],
                                      file_metadata=self.file_details("SYN-NEW", "fastq", run_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_pipeline_run("SYN-PIPELINE-001", "replacement", "2.0")
        with self.assertRaises(ValueError):
            self.store.add_pipeline_run("SYN-SAMPLE-001", "workflow", "1.0")
        with self.assertRaises(ValueError):
            self.store.add_entity("SYN-PIPELINE-001", "subject")
        with self.assertRaises(sqlite3.IntegrityError), self.store._connection:
            self.store._connection.execute("DELETE FROM producing_runs WHERE run_id = 'SYN-PIPELINE-001'")

    def test_legacy_metadata_requires_explicit_write_once_backfill(self):
        self.seed_chain()
        before = self.store.trace_variant("SYN-VARIANT-001")
        self.store.close()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("DROP TABLE file_metadata")
            connection.execute("DROP TABLE producing_runs")
            connection.execute("PRAGMA user_version = 1")
        with MetadataStore(self.database) as legacy:
            self.assertEqual(legacy.trace_variant("SYN-VARIANT-001"), before)
            with self.assertRaisesRegex(ValueError, "backfill"):
                legacy.get_artifact("SYN-FASTQ-001")
            metadata = self.file_details("SYN-FASTQ-001", "fastq", "SYN-RUN-001")
            legacy.backfill_file_metadata("SYN-FASTQ-001", metadata)
            self.assertEqual(legacy.get_artifact("SYN-FASTQ-001")["producing_run"], "SYN-RUN-001")
            with self.assertRaises(sqlite3.IntegrityError):
                legacy.backfill_file_metadata("SYN-FASTQ-001", metadata)
            for identifier in ("SYN-MISSING", "SYN-SUBJECT-001"):
                with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                    legacy.backfill_file_metadata(identifier, metadata)

    def test_archiving_preserves_variant_resolution_and_file_metadata(self):
        self.seed_chain()
        before = self.store.get_artifact("SYN-VCF-001")
        trace = self.store.trace_variant("SYN-VARIANT-001")
        with patch.object(Path, "unlink", side_effect=AssertionError("No payload deletion")):
            self.store.archive_artifact("SYN-VCF-001")
            self.store.archive_artifact("SYN-VCF-001")
        self.assertEqual(self.store.get_artifact("SYN-VCF-001"), {**before, "archived": True})
        for report in (self.store.trace_variant("SYN-VARIANT-001"),
                       self.store.trace_subject("SYN-SUBJECT-001")):
            self.assertEqual(report["links"], trace["links"])
            self.assertEqual(len(report["entities"]), 7)
            self.assertEqual([entity["entity_id"] for entity in report["entities"] if entity["archived"]],
                             ["SYN-VCF-001"])
        with MetadataStore(self.database) as reopened:
            self.assertTrue(reopened.get_artifact("SYN-VCF-001")["archived"])
            self.assertEqual(reopened.trace_variant("SYN-VARIANT-001"),
                             self.store.trace_variant("SYN-VARIANT-001"))

    def test_archiving_rejects_unknown_and_nonfile_entities(self):
        self.seed_chain()
        before = self.store.trace_variant("SYN-VARIANT-001")
        for entity_id in ("SYN-MISSING", "SYN-SUBJECT-001", "SYN-VARIANT-001", "SYN-PIPELINE-001"):
            with self.subTest(entity_id=entity_id), self.assertRaises(ValueError):
                self.store.archive_artifact(entity_id)
        self.assertEqual(self.store.trace_variant("SYN-VARIANT-001"), before)

    def test_archive_during_trace_does_not_mix_read_snapshots(self):
        self.seed_chain()
        self.store._connection.execute("PRAGMA journal_mode = WAL")
        with MetadataStore(self.database) as writer:
            archived = False

            def archive_between_queries(statement):
                nonlocal archived
                if "SELECT parent_id, child_id FROM links" in statement and not archived:
                    archived = True
                    writer.archive_artifact("SYN-VCF-001")

            self.store._connection.set_trace_callback(archive_between_queries)
            try:
                report = self.store.trace_variant("SYN-VARIANT-001")
            finally:
                self.store._connection.set_trace_callback(None)
        self.assertTrue(archived)
        self.assertFalse(any(entity["archived"] for entity in report["entities"]))
        self.assertTrue(self.store.get_artifact("SYN-VCF-001")["archived"])

    def test_foreign_database_and_network_paths_are_rejected(self):
        foreign = self.database.parent / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        with self.assertRaisesRegex(ValueError, "not a supported"):
            MetadataStore(foreign)
        for database in ("relative.sqlite3", r"\\synthetic.invalid\share\metadata.sqlite3"):
            with self.subTest(database=database), self.assertRaises(ValueError):
                MetadataStore(database)

    def test_research_only_grant_returns_research_without_clinical_or_subject_linkage(self):
        self.seed_chain()
        self.store.set_research_metadata("SYN-SAMPLE-001", {
            "cohort_id": "SYN-COHORT-001",
            "study_arm": "synthetic-case",
        })
        self.store.set_clinical_metadata("SYN-SAMPLE-001", {
            "clinical_status": "synthetic-observed",
            "phenotype_code": "SYN-PHENOTYPE-001",
        })
        self.store.grant_access("SYN-PRINCIPAL-RESEARCH", "research_metadata")

        result = self.store.read_sample_metadata(
            "SYN-PRINCIPAL-RESEARCH", "SYN-SAMPLE-001"
        )

        self.assertEqual(result, {
            "sample_id": "SYN-SAMPLE-001",
            "research": {
                "cohort_id": "SYN-COHORT-001",
                "study_arm": "synthetic-case",
            },
        })
        self.assertNotIn("clinical", result)
        self.assertNotIn("subject_id", result)
        with self.assertRaisesRegex(AuthorizationError, "clinical_metadata"):
            self.store.read_clinical_metadata(
                "SYN-PRINCIPAL-RESEARCH", "SYN-SAMPLE-001"
            )
        with self.assertRaisesRegex(AuthorizationError, "subject_linkage"):
            self.store.resolve_subject("SYN-PRINCIPAL-RESEARCH", "SYN-SAMPLE-001")

    def test_metadata_domains_and_grants_persist_separately(self):
        self.seed_chain()
        research = {"assay_type": "synthetic-wgs", "study_id": "SYN-STUDY-001"}
        clinical = {"diagnosis_code": "SYN-DIAGNOSIS-001"}
        self.store.set_research_metadata("SYN-SAMPLE-001", research)
        self.store.set_clinical_metadata("SYN-SAMPLE-001", clinical)
        for grant in ("clinical_metadata", "subject_linkage"):
            self.store.grant_access("SYN-PRINCIPAL-CLINICAL", grant)
        self.store.close()

        with MetadataStore(self.database) as reopened:
            self.assertEqual(
                reopened.read_sample_metadata(
                    "SYN-PRINCIPAL-CLINICAL", "SYN-SAMPLE-001"
                ),
                {"sample_id": "SYN-SAMPLE-001", "clinical": clinical},
            )
            self.assertEqual(
                reopened.resolve_subject(
                    "SYN-PRINCIPAL-CLINICAL", "SYN-SAMPLE-001"
                ),
                "SYN-SUBJECT-001",
            )
            tables = {
                row[0] for row in reopened._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue({
                "research_metadata", "clinical_metadata", "access_grants"
            }.issubset(tables))

    def test_unauthorized_metadata_operations_raise_explicit_errors(self):
        self.seed_chain()
        self.store.set_research_metadata(
            "SYN-SAMPLE-001", {"cohort_id": "SYN-COHORT-001"}
        )
        for operation in (
            lambda: self.store.read_sample_metadata(
                "SYN-PRINCIPAL-NONE", "SYN-SAMPLE-001"
            ),
            lambda: self.store.read_research_metadata(
                "SYN-PRINCIPAL-NONE", "SYN-SAMPLE-001"
            ),
            lambda: self.store.resolve_subject(
                "SYN-PRINCIPAL-NONE", "SYN-SAMPLE-001"
            ),
        ):
            with self.subTest(operation=operation), self.assertRaises(AuthorizationError):
                operation()

    def test_metadata_rejects_non_samples_unapproved_fields_and_invalid_grants(self):
        self.seed_chain()
        cases = [
            ("SYN-SUBJECT-001", {"cohort_id": "SYN-COHORT-001"}),
            ("SYN-MISSING", {"cohort_id": "SYN-COHORT-001"}),
            ("SYN-SAMPLE-001", {"patient_name": "Synthetic Person"}),
            ("SYN-SAMPLE-001", {"cohort_id": ["SYN-COHORT-001"]}),
        ]
        for sample_id, attributes in cases:
            with self.subTest(sample_id=sample_id, attributes=attributes), self.assertRaises(ValueError):
                self.store.set_research_metadata(sample_id, attributes)
        with self.assertRaises(ValueError):
            self.store.grant_access("SYN-PRINCIPAL-001", "all_metadata")
        with self.assertRaises(ValueError):
            self.store.revoke_access("SYN-PRINCIPAL-001", "research_metadata")


if __name__ == "__main__":
    unittest.main()