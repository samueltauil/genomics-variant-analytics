import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.demo_dataset_manifest import (
    COHORT_ID_PATTERN,
    SAMPLE_ID_PATTERN,
    SUBJECT_ID_PATTERN,
    build_manifest,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "demo" / "dataset-manifest.json"
VALIDATOR = ROOT / "scripts" / "demo_dataset_manifest.py"


class DemoDatasetManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = build_manifest()

    def test_committed_manifest_is_deterministically_generated_and_valid(self):
        committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(committed, self.manifest)
        report = validate_manifest(committed)
        self.assertEqual(report["identity_count"], 17)
        self.assertEqual(report["patient_identifying_fields"], 0)
        self.assertEqual(report["patient_identifying_values"], 0)
        self.assertTrue(report["all_subject_ids_synthetic"])
        self.assertFalse(report["genomic_payloads_embedded"])
        self.assertEqual(report["reference_build"], "GRCh38")
        self.assertEqual(report["reference_version"], "2017-1.0/hg38")
        self.assertEqual(report["compatibility_status"], "validation-required-before-compute")

    def test_every_identity_matches_documented_patterns_and_is_unique(self):
        patterns = self.manifest["synthetic_identity_policy"]
        self.assertEqual(patterns["subject_id_pattern"], f"^{SUBJECT_ID_PATTERN}$")
        self.assertEqual(patterns["sample_id_pattern"], f"^{SAMPLE_ID_PATTERN}$")
        self.assertEqual(patterns["cohort_id_pattern"], f"^{COHORT_ID_PATTERN}$")
        identities = self.manifest["identities"]
        self.assertEqual(len({item["subject_id"] for item in identities}), len(identities))
        self.assertEqual(len({item["sample_id"] for item in identities}), len(identities))
        validate_manifest(self.manifest)

    def test_patient_identifying_fields_are_rejected_anywhere(self):
        for field in ("patient_name", "mrn", "date_of_birth", "postal_address", "email"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest["identities"][0][field] = "forbidden"
                with self.assertRaisesRegex(ValueError, "Patient-identifying field"):
                    validate_manifest(manifest)

    def test_patient_identifying_values_and_public_donor_ids_are_rejected(self):
        values = (
            "person@example.invalid",
            "123-45-6789",
            "202-555-0199",
            "NA12878",
            "HG00123",
        )
        for value in values:
            with self.subTest(value=value):
                manifest = copy.deepcopy(self.manifest)
                manifest["identities"][0]["subject_id"] = value
                with self.assertRaisesRegex(ValueError, "Patient-identifying value|must match"):
                    validate_manifest(manifest)

    def test_unknown_non_identity_field_is_rejected_by_exact_schema(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["identities"][0]["full_name"] = "Example Person"
        with self.assertRaisesRegex(ValueError, "must contain exactly"):
            validate_manifest(manifest)

    def test_non_synthetic_or_duplicate_identity_is_rejected(self):
        malformed = copy.deepcopy(self.manifest)
        malformed["identities"][0]["subject_id"] = "SUBJECT-0001"
        duplicate_subject = copy.deepcopy(self.manifest)
        duplicate_subject["identities"][1]["subject_id"] = duplicate_subject["identities"][0]["subject_id"]
        duplicate_sample = copy.deepcopy(self.manifest)
        duplicate_sample["identities"][1]["sample_id"] = duplicate_sample["identities"][0]["sample_id"]
        for manifest in (malformed, duplicate_subject, duplicate_sample):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                validate_manifest(manifest)

    def test_source_and_reference_contract_cannot_be_weakened(self):
        changes = (
            ("source_dataset", "provider", "Other"),
            ("source_dataset", "collection_uri", "https://example.invalid/data?sig=value"),
            ("reference", "build", ""),
            ("reference", "immutable_source_version", ""),
            ("reference", "compatibility_status", "compatible"),
        )
        for section, field, value in changes:
            with self.subTest(section=section, field=field, value=value):
                manifest = copy.deepcopy(self.manifest)
                manifest[section][field] = value
                with self.assertRaises(ValueError):
                    validate_manifest(manifest)

    def test_generator_rejects_invalid_sizes(self):
        for identity_count, cohort_count in (
            (0, 1),
            (10000, 1),
            (True, 1),
            (1, 0),
            (1, 100),
        ):
            with self.subTest(identity_count=identity_count, cohort_count=cohort_count):
                with self.assertRaises(ValueError):
                    build_manifest(identity_count, cohort_count)

    def test_cli_validates_and_writes_metadata_only_manifest(self):
        result = subprocess.run(
            [sys.executable, "-I", str(VALIDATOR), "--manifest", str(MANIFEST)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["identity_count"], 17)

        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(VALIDATOR),
                    "--manifest",
                    str(generated),
                    "--write",
                    "--identity-count",
                    "3",
                    "--cohort-count",
                    "2",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(generated.read_text(encoding="utf-8"))
            self.assertEqual(len(document["identities"]), 3)
            serialized = json.dumps(document).lower()
            for suffix in (".vcf", ".gvcf", ".bam", ".cram", ".fastq"):
                self.assertNotIn(suffix, serialized)

    def test_cli_rejects_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", str(VALIDATOR), "--manifest", str(manifest)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Duplicate JSON field", result.stderr)


if __name__ == "__main__":
    unittest.main()
