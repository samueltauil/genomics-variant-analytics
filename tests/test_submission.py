import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from scripts.validate_submission import digest, submit_run, validate_submission


VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_submission.py"


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.references = [
            {"type": "genome", "name": "GRCh38", "version": "synthetic-v1"},
            {"type": "gene-annotation", "name": "synthetic-genes", "version": "v1"},
        ]
        self.request = {"run_id": "SYN-RUN-001", "workflow_id": "synthetic-workflow",
                        "workflow_version": "v1", "references": copy.deepcopy(self.references)}
        self.compatibility = {"schema_version": 1, "workflows": [{
            "workflow_id": "synthetic-workflow", "workflow_version": "v1",
            "reference_sets": [copy.deepcopy(self.references)],
        }]}
        self.inventory = {"schema_version": 1, "references": [
            dict(reference, uri=f"file:///synthetic/{reference['name']}/v1/reference", sha256="a" * 64)
            for reference in self.references
        ]}
        self.allocate = Mock(return_value="synthetic-allocation")

    def submit(self):
        return submit_run(self.request, self.compatibility, self.inventory, self.allocate)

    def assert_rejected(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.submit()
        self.allocate.assert_not_called()

    def test_exact_compatible_versions_reach_allocator_with_manifest_digests(self):
        self.assertEqual(self.submit(), "synthetic-allocation")
        self.allocate.assert_called_once()
        validated = self.allocate.call_args.args[0]
        self.assertEqual(validated["run_id"], "SYN-RUN-001")
        self.assertEqual(validated["compatibility_manifest_sha256"], digest(self.compatibility))
        self.assertEqual(validated["reference_manifest_sha256"], digest(self.inventory))
        self.assertEqual({reference["name"] for reference in validated["references"]},
                         {"GRCh38", "synthetic-genes"})
        validated["references"][0]["version"] = "mutated"
        self.assertNotIn("mutated", [reference["version"] for reference in self.inventory["references"]])

    def test_incompatible_build_never_allocates_compute(self):
        self.request["references"][0]["name"] = "hg19"
        self.assert_rejected("Incompatible")

    def test_incompatible_annotation_never_allocates_compute(self):
        self.request["references"][1]["version"] = "v2"
        self.assert_rejected("Incompatible")

    def test_missing_declared_reference_fails_without_default_build(self):
        self.inventory["references"][0]["name"] = "hg19"
        self.assert_rejected("unavailable.*no fallback")

    def test_unknown_workflow_version_has_no_fallback(self):
        self.request["workflow_version"] = "v2"
        self.assert_rejected("Undeclared workflow")

    def test_missing_or_multiple_builds_are_rejected(self):
        original = copy.deepcopy(self.request)
        for references in ([], [self.references[1]], self.references + [dict(self.references[0], name="hg19")]):
            with self.subTest(references=references):
                self.request = dict(original, references=references)
                self.assert_rejected("reference set")

    def test_missing_extra_or_duplicate_annotation_is_rejected(self):
        for references in ([self.references[0]], self.references + [self.references[1]],
                           self.references + [{"type": "transcript-annotation", "name": "extra", "version": "v1"}]):
            with self.subTest(references=references):
                self.request["references"] = references
                self.assert_rejected("Incompatible|duplicate")

    def test_duplicate_workflow_or_reference_definitions_fail_closed(self):
        self.compatibility["workflows"] *= 2
        self.assert_rejected("Duplicate workflow")
        self.compatibility["workflows"] = self.compatibility["workflows"][:1]
        self.inventory["references"] *= 2
        self.assert_rejected("Duplicate reference")

    def test_invalid_checksum_and_credential_bearing_uri_are_rejected(self):
        artifact = copy.deepcopy(self.inventory["references"][0])
        for change in ({"sha256": "not-a-hash"}, {"uri": "https://example.invalid/ref?sig=synthetic"},
                       {"uri": "https://synthetic:password@example.invalid/ref"},
                       {"uri": "relative/path"}, {"uri": "ftp://example.invalid/ref"}):
            with self.subTest(change=change):
                self.inventory["references"][0] = dict(artifact, **change)
                self.assert_rejected("sha256|URI")

    def test_unknown_fields_and_schema_versions_are_rejected(self):
        self.request["default_reference"] = "hg19"
        self.assert_rejected("exactly")
        del self.request["default_reference"]
        for version in (True, 2, "1"):
            self.compatibility["schema_version"] = version
            self.assert_rejected("schema_version")

    def test_reference_order_does_not_change_compatibility(self):
        self.request["references"].reverse()
        self.assertEqual(self.submit(), "synthetic-allocation")

    def test_cli_validates_only_and_rejects_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = [sys.executable, "-I", str(VALIDATOR)]
            paths = {}
            for name, value in (("request", self.request), ("compatibility", self.compatibility),
                                ("inventory", self.inventory)):
                paths[name] = Path(directory) / f"{name}.json"
                paths[name].write_text(json.dumps(value), encoding="utf-8")
                arguments.extend([f"--{name}", str(paths[name])])
            result = subprocess.run(arguments, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["compute_allocated"])
            paths["request"].write_text('{"run_id":"first","run_id":"second"}', encoding="utf-8")
            result = subprocess.run(arguments, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("Duplicate JSON field", result.stderr)


if __name__ == "__main__":
    unittest.main()