from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.stage_records import StagingLog

SOURCE_DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


class StagingLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "staging.sqlite3"
        self.log = StagingLog(self.database)
        self.addCleanup(self.log.close)

    def record(self, source="RUN-A/SAMPLE-1_S1_L001_R1_001.fastq.gz", destination_checksum=None):
        return {
            "source_path": source,
            "run_id": "RUN-A",
            "sample_id": "SAMPLE-1",
            "destination_uri": "abfss://healthcare@synthetic.dfs.core.windows.net/"
                               "Ingest/Genomics/FASTQ/RUN-A/read1.fastq.gz",
            "storage_tier": "Hot",
            "classification": "genomic-primary",
            "source_checksum": SOURCE_DIGEST,
            "destination_checksum": destination_checksum or SOURCE_DIGEST,
        }

    def test_matching_checksums_report_every_required_field(self):
        entry = self.log.record(self.record(), "2026-09-11T00:00:00Z")

        for field in ("source_path", "destination_uri", "state", "integrity_result",
                      "storage_tier", "classification"):
            self.assertIsNotNone(entry[field], f"{field} must be populated")
        self.assertEqual(entry["state"], "staged")
        self.assertEqual(entry["integrity_result"], "verified")
        self.assertEqual(entry["run_id"], "RUN-A")
        self.assertEqual(entry["sample_id"], "SAMPLE-1")
        self.assertEqual([e["source_path"] for e in self.log.available_for_processing()],
                         [entry["source_path"]])

    def test_mismatch_fails_the_record_and_withholds_it(self):
        entry = self.log.record(self.record(destination_checksum=OTHER_DIGEST),
                                "2026-09-11T00:00:00Z")

        self.assertEqual(entry["state"], "failed")
        self.assertEqual(entry["integrity_result"], "mismatch")
        self.assertEqual(entry["source_checksum"], SOURCE_DIGEST)
        self.assertEqual(entry["destination_checksum"], OTHER_DIGEST)
        self.assertEqual(self.log.available_for_processing(), [])
        # A failure stays visible to operators even though downstream cannot consume it.
        self.assertEqual(len(self.log.report()), 1)

    def test_corrupted_destination_revokes_an_earlier_verified_record(self):
        self.log.record(self.record(), "2026-09-11T00:00:00Z")
        self.assertEqual(len(self.log.available_for_processing()), 1)

        revised = self.log.record(self.record(destination_checksum=OTHER_DIGEST),
                                  "2026-09-11T01:00:00Z")

        self.assertEqual(revised["state"], "failed")
        self.assertEqual(self.log.available_for_processing(), [])
        self.assertEqual(len(self.log.report()), 1, "re-verification revises, not duplicates")

    def test_every_file_of_a_run_is_reported_independently(self):
        self.log.record(self.record(source="RUN-A/one.fastq.gz"), "2026-09-11T00:00:00Z")
        self.log.record(self.record(source="RUN-A/two.fastq.gz",
                                    destination_checksum=OTHER_DIGEST), "2026-09-11T00:00:00Z")

        report = self.log.report()
        self.assertEqual(len(report), 2)
        self.assertEqual({e["source_path"] for e in self.log.available_for_processing()},
                         {"RUN-A/one.fastq.gz"})

    def test_invalid_records_are_rejected_without_writing(self):
        rejected = [
            ({**self.record(), "storage_tier": "Warm"}, "unknown tier"),
            ({**self.record(), "classification": "secret"}, "unknown classification"),
            ({**self.record(), "source_checksum": "abc"}, "short digest"),
            ({**self.record(), "destination_checksum": SOURCE_DIGEST.upper()}, "uppercase digest"),
            ({**self.record(), "destination_uri": "/Ingest/read1.fastq.gz"}, "relative uri"),
            ({**self.record(), "destination_uri": "ftp://host/Ingest/read1"}, "unsupported scheme"),
            ({**self.record(), "destination_uri":
                "https://user:pass@host/Ingest/read1"}, "credential in uri"),
            ({**self.record(), "destination_uri":
                "abfss://fs@host.dfs.core.windows.net/Ingest/../read1"}, "relative segment"),
            ({**self.record(), "destination_uri":
                "abfss://fs@host.dfs.core.windows.net/"}, "container root"),
            ({**self.record(), "source_path": "  "}, "blank source path"),
        ]
        for record, reason in rejected:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    self.log.record(record, "2026-09-11T00:00:00Z")

        extra = {**self.record(), "unexpected": True}
        with self.assertRaises(ValueError):
            self.log.record(extra, "2026-09-11T00:00:00Z")

        del extra["unexpected"]
        del extra["storage_tier"]
        with self.assertRaises(ValueError):
            self.log.record(extra, "2026-09-11T00:00:00Z")

        self.assertEqual(self.log.report(), [])

    def test_records_persist_across_restart(self):
        self.log.record(self.record(), "2026-09-11T00:00:00Z")
        self.log.close()

        with StagingLog(self.database) as reopened:
            self.assertEqual(len(reopened.available_for_processing()), 1)

    def test_foreign_database_is_rejected(self):
        other = Path(self.temporary.name) / "other.sqlite3"
        connection = sqlite3.connect(other)
        try:
            connection.execute("CREATE TABLE unrelated (id INTEGER)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ValueError):
            StagingLog(other)

    def test_database_constraints_reject_inconsistent_state(self):
        self.log.record(self.record(), "2026-09-11T00:00:00Z")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.log._connection:
                self.log._connection.execute(
                    "UPDATE staging SET integrity_result = 'mismatch' WHERE state = 'staged'"
                )


if __name__ == "__main__":
    unittest.main()
