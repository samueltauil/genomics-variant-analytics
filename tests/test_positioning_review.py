import json
from pathlib import Path
import tempfile
import unittest

from scripts.review_positioning import (
    ASSUMPTION_REGISTER,
    CLAIM_REGISTER,
    COVERAGE,
    PROPOSAL,
    TASKS,
    build_report,
    discover_presenter_material,
    proposal_assumptions,
    review_material,
    validate_assumptions,
)


ROOT = Path(__file__).resolve().parents[1]


class PositioningReviewTests(unittest.TestCase):
    def test_repository_review_passes_and_covers_all_public_markdown(self):
        report, findings = build_report(ROOT, "2026-09-19")
        self.assertEqual(findings, [])
        self.assertEqual(report["result"], "pass")
        reviewed = set(report["reviewed_files"])
        expected = {
            path.relative_to(ROOT).as_posix()
            for path in discover_presenter_material(ROOT)
        }
        self.assertEqual(reviewed, expected)
        self.assertIn("README.md", reviewed)
        self.assertIn("docs/demo-runbook.md", reviewed)
        self.assertIn("docs/wiki/Home.md", reviewed)

    def test_each_claim_boundary_rejects_an_assertion(self):
        examples = {
            "released.md": "This is a Microsoft blueprint.",
            "compliance.md": "This makes your genomic data compliant.",
            "customer.md": "Customers use this accelerator in production.",
            "clinical.md": "AI-assisted output is a clinical determination.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            for name, text in examples.items():
                (root / "docs" / name).write_text(text, encoding="utf-8")
            _, _, findings = review_material(root)
        self.assertEqual(
            {finding.rule for finding in findings},
            {
                "released-offering",
                "automatic-compliance",
                "customer-attribution",
                "clinical-output",
            },
        )

    def test_generated_presenter_material_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "presentations" / "customer-deck.html"
            generated.parent.mkdir(parents=True)
            generated.write_text("<p>Reference architecture.</p>", encoding="utf-8")
            self.assertEqual(discover_presenter_material(root), [generated])

    def test_explicit_limitations_are_not_false_positives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "README.md").write_text(
                "This is not a released Microsoft blueprint. "
                "AI-assisted output is not a clinical determination. "
                "It does not make genomic data compliant.",
                encoding="utf-8",
            )
            _, matches, findings = review_material(root)
        self.assertGreaterEqual(len(matches), 3)
        self.assertEqual(findings, [])
        self.assertTrue(all(item["disposition"] == "explicitly negated or prohibited"
                            for item in matches))

    def test_register_exactly_covers_every_proposal_assumption(self):
        assumptions = proposal_assumptions((ROOT / PROPOSAL).read_text(encoding="utf-8"))
        register = json.loads((ROOT / ASSUMPTION_REGISTER).read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["proposal_text"] for entry in register["assumptions"]],
            assumptions,
        )
        results = validate_assumptions(ROOT)
        self.assertEqual(len(results), 9)
        self.assertTrue(all(result["status"] == "assumption" for result in results))
        self.assertTrue(all(result["task_evidence"] for result in results))

    def test_confirmation_requires_explicit_review_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in (PROPOSAL, TASKS, COVERAGE, ASSUMPTION_REGISTER):
                target = root / source
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((ROOT / source).read_text(encoding="utf-8"), encoding="utf-8")
            document = json.loads((root / ASSUMPTION_REGISTER).read_text(encoding="utf-8"))
            document["assumptions"][0]["status"] = "confirmed"
            (root / ASSUMPTION_REGISTER).write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires reviewed evidence"):
                validate_assumptions(root)

    def test_claim_register_carries_all_four_boundaries(self):
        text = (ROOT / CLAIM_REGISTER).read_text(encoding="utf-8")
        for number in range(1, 5):
            self.assertIn(f"Boundary {number}", text)


if __name__ == "__main__":
    unittest.main()
