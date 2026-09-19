from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "demo-runbook.md"


class DemoRunbookTests(unittest.TestCase):
    def test_seven_step_sequence_names_contract_outputs_and_implemented_evidence(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        expected_rows = {
            "1. Ingest": (
                "run/sample identifiers",
                ROOT / "scripts" / "scan_landing.py",
                "arrival_timestamp",
            ),
            "2. Stage": (
                "integrity result",
                ROOT / "scripts" / "stage_records.py",
                "integrity_result",
            ),
            "3. Process": (
                "BAM/CRAM",
                ROOT / "scripts" / "secondary_pipeline.py",
                "variant_calling",
            ),
            "4. Build variant store": (
                "Accepted/rejected counts",
                ROOT / "scripts" / "variant_store.py",
                "rejected_count",
            ),
            "5. Query": (
                "cross-cohort",
                ROOT / "scripts" / "analytics_query.py",
                "query_cross_cohort",
            ),
            "6. Visualize": (
                "processing-status views",
                ROOT / "scripts" / "analytics_experience.py",
                "processing_status",
            ),
            "7. Govern": (
                "reprocessing audit",
                ROOT / "scripts" / "governance.py",
                "record_reprocessing",
            ),
        }
        for step, (observable, implementation, symbol) in expected_rows.items():
            with self.subTest(step=step):
                row = next(
                    line for line in runbook.splitlines()
                    if line.startswith(f"| {step} |")
                )
                self.assertIn(observable, row)
                self.assertTrue(implementation.is_file())
                self.assertIn(symbol, implementation.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
