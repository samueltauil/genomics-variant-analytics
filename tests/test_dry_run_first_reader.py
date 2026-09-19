"""Tests for scripts/dry_run_first_reader.py (OpenSpec task 11.16).

Exercises the first-time-reader dry-run harness end to end against the real
local scripts it drives, and proves it distinguishes locally executable
phases from live-cloud phases and would surface a genuine documentation
mismatch rather than silently accepting it.
"""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from scripts.dry_run_first_reader import (
    LIVE_CLOUD,
    LOCAL_DRY_RUN,
    REPO_ROOT,
    phase_preflight,
    run_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]


class DryRunFirstReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name) / "scratch"

    def test_full_dry_run_matches_documentation_with_no_gaps(self):
        report = run_dry_run(self.scratch)
        self.assertTrue(report["local_dry_run_phases_matched_documentation"])
        self.assertEqual(report["documentation_gaps_found"], [])
        self.assertTrue(report["acceptance"]["met"])

    def test_local_and_live_cloud_phases_are_correctly_classified(self):
        report = run_dry_run(self.scratch)
        categories = {phase["phase"]: phase["category"] for phase in report["phases"]}
        self.assertEqual(categories["phase0_preflight"], LOCAL_DRY_RUN)
        self.assertEqual(categories["phase2_seeding"], LOCAL_DRY_RUN)
        self.assertEqual(categories["phase4_rehearsal"], LOCAL_DRY_RUN)
        self.assertEqual(categories["phase5_reset"], LOCAL_DRY_RUN)
        self.assertEqual(categories["phase1_bringup"], LIVE_CLOUD)
        self.assertEqual(categories["phase6_teardown"], LIVE_CLOUD)
        # Live-cloud phases are reported as not executed and excluded from
        # the pass/fail acceptance signal; they are a stated scope limit.
        for phase_id in ("phase1_bringup", "phase6_teardown"):
            phase = next(p for p in report["phases"] if p["phase"] == phase_id)
            self.assertFalse(phase["executed"])
            self.assertIsNone(phase["matched_documentation"])
        self.assertEqual(
            set(report["live_cloud_phases_requiring_authorized_subscription"]),
            {"phase1_bringup", "phase6_teardown"},
        )

    def test_live_cloud_phases_cite_why_no_published_input_exists(self):
        report = run_dry_run(self.scratch)
        bringup = next(p for p in report["phases"] if p["phase"] == "phase1_bringup")
        teardown = next(p for p in report["phases"] if p["phase"] == "phase6_teardown")
        self.assertIn("SubscriptionId", bringup["command"])
        self.assertIn("environment.env.json", bringup["notes"])
        self.assertIn("SubscriptionId", teardown["command"])
        self.assertIn("not executable", teardown["notes"])

    def test_local_phases_execute_the_documented_command_exactly(self):
        report = run_dry_run(self.scratch)
        seeding = next(p for p in report["phases"] if p["phase"] == "phase2_seeding")
        self.assertIn("stage_demo_landing.py", seeding["command"])
        self.assertEqual(seeding["actual"]["file_count"], 34)
        rehearsal = next(p for p in report["phases"] if p["phase"] == "phase4_rehearsal")
        self.assertTrue(rehearsal["actual"]["all_passed"])
        reset = next(p for p in report["phases"] if p["phase"] == "phase5_reset")
        self.assertTrue(reset["actual"]["second_removed_nothing"])

    def test_preflight_phase_records_the_exact_documented_snippet_result(self):
        result = phase_preflight(self.scratch)
        self.assertEqual(result.actual["Mode"], "local-preflight")
        self.assertFalse(result.actual["Ready"])
        self.assertEqual(result.actual["BlockingFailures"], 0)
        self.assertTrue(result.matched_documentation)

    def test_a_broken_documented_promise_is_reported_as_a_gap_not_swallowed(self):
        # Simulate the exact class of defect this harness exists to catch: a
        # phase's actual result no longer matching the documented promise.
        result = phase_preflight(self.scratch)
        result.expected["Ready"] = True
        result.matched_documentation = (
            result.actual["Mode"] == result.expected["Mode"]
            and result.actual["Ready"] == result.expected["Ready"]
            and result.actual["BlockingFailures"] == result.expected["BlockingFailures"]
        )
        self.assertFalse(result.matched_documentation)

    def test_dry_run_never_touches_infrastructure(self):
        report = run_dry_run(self.scratch)
        rehearsal = next(p for p in report["phases"] if p["phase"] == "phase4_rehearsal")
        reset = next(p for p in report["phases"] if p["phase"] == "phase5_reset")
        self.assertFalse(rehearsal["actual"]["infrastructure_touched"])
        self.assertTrue(reset["actual"]["infrastructure_touched"])

    def test_cli_entry_point_writes_the_report_and_exits_zero_when_met(self):
        output = self.scratch.parent / "evidence.json"
        completed = subprocess.run(
            [
                sys.executable, "scripts/dry_run_first_reader.py",
                "--scratch-root", str(self.scratch / "cli"),
                "--write-report", str(output),
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(written["acceptance"]["met"])
        self.assertEqual(written["documentation_gaps_found"], [])

    def test_dated_evidence_artifact_is_checked_in_and_clean(self):
        evidence_path = ROOT / "docs" / "dry-run-evidence-2026-09-19.json"
        self.assertTrue(evidence_path.is_file())
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["generated_on"][:10], "2026-09-19")
        self.assertTrue(evidence["acceptance"]["met"])
        self.assertEqual(evidence["documentation_gaps_found"], [])


if __name__ == "__main__":
    unittest.main()