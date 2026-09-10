from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.metadata_store import MetadataStore


class MetadataStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "metadata.sqlite3"
        self.store = MetadataStore(self.database)
        self.addCleanup(self.store.close)

    def seed_chain(self, suffix="001", aligned_kind="bam", variant_kind="vcf"):
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
        self.store.add_entity("SYN-FASTQ-MATE", "fastq", ["SYN-RUN-001"])
        self.store.add_entity("SYN-MERGED-BAM", "bam", ["SYN-FASTQ-001", "SYN-FASTQ-MATE"])
        self.store.add_entity("SYN-JOINT-VCF", "vcf", ["SYN-MERGED-BAM", "SYN-ALIGNED-002"])
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

    def test_foreign_database_and_network_paths_are_rejected(self):
        foreign = self.database.parent / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        with self.assertRaisesRegex(ValueError, "not a supported"):
            MetadataStore(foreign)
        for database in ("relative.sqlite3", r"\\synthetic.invalid\share\metadata.sqlite3"):
            with self.subTest(database=database), self.assertRaises(ValueError):
                MetadataStore(database)


if __name__ == "__main__":
    unittest.main()