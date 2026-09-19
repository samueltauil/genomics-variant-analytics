import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.review_engineering_changes import review_repository


SPEC_PATH = (
    "openspec/changes/add-genomics-variant-accelerator/specs/"
    "variant-store/delta-variant-store/spec.md"
)


class EngineeringReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.write("workflows/reference-compatibility.json", self.manifest("v0.1.0", "GRCh38"))
        self.write("scripts/variant_store.py", "VARIANT_FIELDS = " + repr(self.columns()) + "\n")
        core = ", ".join(f"`{name}`" for name in self.columns()[:8])
        context = ", ".join(f"`{name}`" for name in self.columns()[8:])
        self.write(SPEC_PATH, (
            "Every variant record SHALL carry the core VCF fields: " + core + ".\n\n"
            "Every variant record SHALL additionally carry " + context + ".\n\n"
        ))
        self.base = self.commit()

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Synthetic review fixture")
        return self.git("rev-parse", "HEAD")

    @staticmethod
    def columns():
        return (
            "CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO",
            "sample_id", "research_subject_id", "cohort_id", "gene", "transcript",
            "variant_consequence", "genotype", "allele_frequency", "reference_build",
            "pipeline_version", "source_file_uri", "ingestion_timestamp",
        )

    @staticmethod
    def manifest(version, build):
        return json.dumps({"workflows": [{
            "workflow_id": "secondary",
            "workflow_version": version,
            "reference_sets": [[{"type": "genome", "name": build, "version": "v1"}]],
        }]})

    def test_reference_change_without_version_bump_is_flagged(self):
        self.write("workflows/reference-compatibility.json", self.manifest("v0.1.0", "GRCh37"))
        head = self.commit()
        reviewed, findings = review_repository(self.repo, self.base, head)
        self.assertIn("workflows/reference-compatibility.json", reviewed)
        self.assertTrue(any("without a workflow_version bump" in item.message for item in findings))

    def test_reference_change_with_version_bump_passes(self):
        self.write("workflows/reference-compatibility.json", self.manifest("v0.2.0", "GRCh37"))
        head = self.commit()
        self.assertEqual(review_repository(self.repo, self.base, head)[1], [])

    def test_column_absent_from_exact_spec_is_flagged_and_names_spec(self):
        self.write(
            "scripts/variant_store.py",
            "VARIANT_FIELDS = " + repr((*self.columns(), "reference_version")) + "\n",
        )
        head = self.commit()
        findings = review_repository(self.repo, self.base, head)[1]
        self.assertEqual(len(findings), 1)
        self.assertIn("'reference_version'", findings[0].message)
        self.assertIn(SPEC_PATH, findings[0].message)

    def test_exact_schema_passes(self):
        self.write("scripts/variant_store.py", "VARIANT_FIELDS = " + repr(self.columns()) + "\n# changed\n")
        head = self.commit()
        self.assertEqual(review_repository(self.repo, self.base, head)[1], [])


if __name__ == "__main__":
    unittest.main()
