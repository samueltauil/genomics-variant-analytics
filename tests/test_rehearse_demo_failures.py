"""Tests for scripts/rehearse_demo_failures.py (OpenSpec task 11.8).

Each test drives one rehearsed failure demonstration through the harness and
asserts it produces the exact response its capability spec states, using the
same synthetic identifiers and real local stores as the demo runbook.
"""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from scripts.rehearse_demo_failures import (
    rehearse_all,
    rehearse_denied_access,
    rehearse_failed_transfer,
    rehearse_rejected_variant,
)


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "rehearse_demo_failures.py"


class RehearseDemoFailuresTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_root = Path(self.temporary.name)

    def test_failed_transfer_demonstration_matches_the_ingestion_spec_response(self):
        outcome = rehearse_failed_transfer(self.state_root)
        self.assertTrue(outcome["passed"], outcome)
        self.assertEqual(outcome["actual_response"], outcome["expected_response"])
        self.assertEqual(outcome["actual_response"]["failed_state"], "failed")
        self.assertEqual(outcome["actual_response"]["failure_reason"], "sender-aborted")
        self.assertTrue(outcome["actual_response"]["withheld_from_staging_while_failed"])
        self.assertTrue(outcome["actual_response"]["retry_completes"])
        self.assertTrue(outcome["actual_response"]["retry_available_for_staging"])

    def test_rejected_variant_demonstration_matches_the_variant_store_spec_response(self):
        outcome = rehearse_rejected_variant(self.state_root)
        self.assertTrue(outcome["passed"], outcome)
        self.assertEqual(outcome["actual_response"]["accepted_count"], 1)
        self.assertEqual(outcome["actual_response"]["rejected_count"], 1)
        self.assertTrue(outcome["actual_response"]["rejected_reason_contains_alt"])
        self.assertTrue(outcome["actual_response"]["rejected_row_has_source_uri_and_line"])
        self.assertTrue(outcome["actual_response"]["bad_row_not_written"])

    def test_denied_access_demonstration_matches_the_governance_spec_response(self):
        outcome = rehearse_denied_access(self.state_root)
        self.assertTrue(outcome["passed"], outcome)
        self.assertTrue(outcome["actual_response"]["raised_authorization_error"])
        self.assertTrue(outcome["actual_response"]["denial_audit_entry_recorded"])
        self.assertTrue(outcome["actual_response"]["denial_audit_entry_has_affected_data"])

    def test_rehearse_all_runs_every_demonstration_and_records_run_history(self):
        report = rehearse_all(self.state_root)

        self.assertTrue(report["all_passed"], report)
        self.assertFalse(report["infrastructure_touched"])
        self.assertEqual(
            {entry["demonstration"] for entry in report["demonstrations"]},
            {"failed_transfer", "rejected_variant", "denied_access"},
        )

        connection = sqlite3.connect(self.state_root / "run_history.sqlite3")
        try:
            rows = connection.execute(
                "SELECT demonstration, passed FROM demonstration_runs ORDER BY run_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(passed == 1 for _, passed in rows))

    def test_rehearse_all_never_touches_infrastructure_or_paths_outside_state_root(self):
        sentinel = self.state_root.parent / "sentinel.sqlite3"
        sentinel.write_text("untouched")
        self.addCleanup(sentinel.unlink)

        rehearse_all(self.state_root)

        self.assertEqual(sentinel.read_text(), "untouched")

    def test_cli_exits_zero_and_reports_all_passed(self):
        result = subprocess.run(
            [sys.executable, str(HARNESS), "--state-root", str(self.state_root)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["all_passed"])
        self.assertEqual(len(report["demonstrations"]), 3)


if __name__ == "__main__":
    unittest.main()
