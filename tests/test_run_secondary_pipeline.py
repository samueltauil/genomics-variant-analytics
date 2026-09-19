"""Tests for the CLI orchestrator (scripts/run_secondary_pipeline.py) that
ties synthetic sample generation, the QC/alignment/variant-calling pipeline,
and provenance persistence together as one local/containerized entry point.
"""

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

from scripts.pipeline_provenance import get_run
from scripts.run_secondary_pipeline import execute


class RunSecondaryPipelineExecuteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run-secondary-pipeline-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_execute_success_persists_full_provenance(self):
        report = execute(
            run_id="SYN-RUN-EXEC-OK", work_dir=self.tmp / "work",
            publish_dir=self.tmp / "publish", provenance_db=self.tmp / "prov.sqlite3",
        )
        self.assertEqual(report["terminal_state"], "succeeded")
        self.assertIsNone(report["failing_stage"])
        connection = sqlite3.connect(self.tmp / "prov.sqlite3")
        connection.row_factory = sqlite3.Row
        stored = get_run(connection, "SYN-RUN-EXEC-OK")
        connection.close()
        self.assertIsNotNone(stored)
        self.assertEqual(stored["terminal_state"], "succeeded")
        self.assertTrue(len(stored["output_uris"]) >= 3)

    def test_execute_forced_failure_persists_failing_stage_and_no_outputs(self):
        report = execute(
            run_id="SYN-RUN-EXEC-FAIL", work_dir=self.tmp / "work",
            publish_dir=self.tmp / "publish", provenance_db=self.tmp / "prov.sqlite3",
            force_fail_stage="variant_calling",
        )
        self.assertEqual(report["terminal_state"], "failed")
        self.assertEqual(report["failing_stage"], "variant_calling")
        connection = sqlite3.connect(self.tmp / "prov.sqlite3")
        connection.row_factory = sqlite3.Row
        stored = get_run(connection, "SYN-RUN-EXEC-FAIL")
        connection.close()
        self.assertEqual(stored["output_uris"], [])
        self.assertFalse((self.tmp / "publish").exists())

    def test_cli_invocation_success_exit_code_zero(self):
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.run_secondary_pipeline",
             "--run-id", "SYN-RUN-CLI-OK",
             "--work-dir", str(self.tmp / "work"),
             "--publish-dir", str(self.tmp / "publish"),
             "--provenance-db", str(self.tmp / "prov.sqlite3")],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["terminal_state"], "succeeded")

    def test_cli_invocation_forced_failure_exit_code_one(self):
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.run_secondary_pipeline",
             "--run-id", "SYN-RUN-CLI-FAIL",
             "--work-dir", str(self.tmp / "work"),
             "--publish-dir", str(self.tmp / "publish"),
             "--provenance-db", str(self.tmp / "prov.sqlite3"),
             "--force-fail-stage", "alignment"],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["terminal_state"], "failed")
        self.assertEqual(payload["failing_stage"], "alignment")


if __name__ == "__main__":
    unittest.main()