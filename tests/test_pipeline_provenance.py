"""Tests for secondary-analysis pipeline run provenance persistence.

Covers task 5.5: all provenance fields present for a successful run, and all
provenance fields plus the failing stage present for a failed run, with
strict fail-closed validation (missing/extra fields, malformed URIs/
timestamps, inconsistent published-output-vs-terminal-state combinations,
and duplicate run_id rejection).
"""

import sqlite3
import unittest

from scripts.pipeline_provenance import (
    PROVENANCE_FIELDS,
    ensure_schema,
    get_run,
    present_fields,
    record_run,
    validate_run_record,
)


def _base_record(**overrides):
    record = {
        "run_id": "SYN-RUN-0001",
        "workflow_id": "genomics-secondary-analysis",
        "workflow_version": "v0.1.0",
        "reference_build": "SYN-demo-genome",
        "reference_version": "synthetic-abc123def456",
        "execution_target": "local",
        "compute_pool": "local-dev",
        "input_uris": ["file:///tmp/a/reads_R1.fastq"],
        "output_uris": ["file:///tmp/a/out.bam"],
        "start_time": "2026-01-01T00:00:00+00:00",
        "end_time": "2026-01-01T00:01:00+00:00",
        "terminal_state": "succeeded",
        "log_location": "file:///tmp/a/run.log",
        "failing_stage": None,
    }
    record.update(overrides)
    return record


class ProvenanceFieldsTestCase(unittest.TestCase):
    def test_provenance_fields_enumerates_twelve_content_fields(self):
        # The secondary-analysis spec text names workflow id/version,
        # reference build/version, execution target/pool, input/output
        # URIs, start/end time, terminal state, and log location -- twelve
        # distinct content fields (plus run_id as the record key, and
        # failing_stage as the failure-only discriminator). This constant
        # is the single source of truth for "all fields present" checks.
        self.assertEqual(len(PROVENANCE_FIELDS), 12)

    def test_all_provenance_fields_present_on_success(self):
        record = validate_run_record(_base_record())
        present = present_fields(record)
        self.assertEqual(set(present), set(PROVENANCE_FIELDS))
        self.assertIsNone(record["failing_stage"])

    def test_all_provenance_fields_present_on_failure_including_failing_stage(self):
        record = validate_run_record(_base_record(
            terminal_state="failed", output_uris=[], failing_stage="variant_calling",
        ))
        present = present_fields(record)
        self.assertEqual(set(present), set(PROVENANCE_FIELDS))
        self.assertEqual(record["failing_stage"], "variant_calling")


class ValidateRunRecordTestCase(unittest.TestCase):
    def test_rejects_missing_field(self):
        record = _base_record()
        del record["log_location"]
        with self.assertRaises(ValueError):
            validate_run_record(record)

    def test_rejects_extra_field(self):
        record = _base_record(unexpected_field="nope")
        with self.assertRaises(ValueError):
            validate_run_record(record)

    def test_rejects_unknown_terminal_state(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(terminal_state="partial"))

    def test_succeeded_run_must_have_at_least_one_output_uri(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(output_uris=[]))

    def test_succeeded_run_must_not_set_failing_stage(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(failing_stage="alignment"))

    def test_failed_run_must_not_publish_output_uris(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(
                terminal_state="failed", failing_stage="alignment",
                output_uris=["file:///tmp/a/partial.bam"],
            ))

    def test_failed_run_requires_failing_stage(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(terminal_state="failed", output_uris=[]))

    def test_rejects_end_time_before_start_time(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(
                start_time="2026-01-01T00:05:00+00:00", end_time="2026-01-01T00:00:00+00:00",
            ))

    def test_rejects_naive_timestamp_without_timezone(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(start_time="2026-01-01T00:00:00"))

    def test_rejects_empty_input_uris(self):
        with self.assertRaises(ValueError):
            validate_run_record(_base_record(input_uris=[]))


class RecordRunPersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)

    def test_record_and_retrieve_success_run(self):
        record_run(self.connection, _base_record())
        stored = get_run(self.connection, "SYN-RUN-0001")
        self.assertEqual(stored["terminal_state"], "succeeded")
        self.assertEqual(stored["output_uris"], ["file:///tmp/a/out.bam"])
        self.assertIsNone(stored["failing_stage"])

    def test_record_and_retrieve_failed_run(self):
        record_run(self.connection, _base_record(
            run_id="SYN-RUN-0002", terminal_state="failed", output_uris=[],
            failing_stage="quality_control",
        ))
        stored = get_run(self.connection, "SYN-RUN-0002")
        self.assertEqual(stored["terminal_state"], "failed")
        self.assertEqual(stored["output_uris"], [])
        self.assertEqual(stored["failing_stage"], "quality_control")

    def test_duplicate_run_id_is_rejected_append_only(self):
        record_run(self.connection, _base_record())
        with self.assertRaises(ValueError):
            record_run(self.connection, _base_record())

    def test_get_run_returns_none_for_unknown_run_id(self):
        ensure_schema(self.connection)
        self.assertIsNone(get_run(self.connection, "SYN-RUN-MISSING"))


if __name__ == "__main__":
    unittest.main()