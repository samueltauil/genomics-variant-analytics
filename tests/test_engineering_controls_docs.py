from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EngineeringControlsDocumentationTests(unittest.TestCase):
    def test_every_tier_gated_feature_has_dependency_substitute_and_gap(self):
        text = (ROOT / "docs" / "engineering-controls.md").read_text(encoding="utf-8")
        rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| Feature") and not line.startswith("|---")
        ]
        expected = (
            "Push rulesets",
            "Required deployment reviewers",
            "Organization-wide branch or tag policy",
            "Copilot content exclusion",
            "Copilot code review",
            "GitHub-hosted Actions",
            "Secret scanning and push protection",
            "Immutable releases and artifact attestations",
            "Release assets for reference data",
        )
        self.assertEqual(len(rows), len(expected))
        for feature in expected:
            row = next((item for item in rows if feature in item), None)
            self.assertIsNotNone(row, feature)
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            self.assertEqual(len(cells), 4, feature)
            self.assertTrue(all(cells), feature)

    def test_live_triage_evidence_preserves_schedule_boundary(self):
        text = (ROOT / "docs" / "engineering-controls.md").read_text(encoding="utf-8")
        self.assertIn("disposable issue #26", text)
        self.assertIn("Recurrence count: 2", text)
        self.assertIn("exactly one issue", text)
        self.assertIn("A manually invoked synthetic acceptance run", text)
        self.assertIn("rather than waiting for the next scheduled trigger", text)


if __name__ == "__main__":
    unittest.main()
