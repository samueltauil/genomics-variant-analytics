import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts.publish_reference import ReferenceZone, reference_path
from scripts.validate_submission import unique_object, validate_request_compatibility
from scripts.workflow_submission import submit_workflow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY_PATH = REPOSITORY_ROOT / "workflows" / "reference-compatibility.json"


class MemoryTransport:
    def __init__(self):
        self.objects = {}

    def exists(self, path):
        return path in self.objects

    def put(self, path, chunks):
        self.objects[path] = b"".join(chunks)

    def put_bytes(self, path, payload):
        self.objects[path] = payload

    def get(self, path):
        return self.objects[path]

    def list(self, prefix):
        return [path for path in self.objects if path.startswith(prefix)]

    def uri(self, path):
        return "https://reference.invalid/" + path


def artifact(filename):
    return {
        "filename": filename,
        "open": lambda: io.BytesIO(b"synthetic reference placeholder"),
        "source": "https://source.invalid/synthetic-reference",
    }


class WorkflowSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.genome = {"type": "genome", "name": "SYN-build", "version": "v1"}
        self.annotation = {
            "type": "gene-annotation", "name": "SYN-genes", "version": "v1",
        }
        self.references = [self.genome, self.annotation]
        self.request = {
            "run_id": "SYN-RUN-001",
            "workflow_id": "synthetic-workflow",
            "workflow_version": "v1",
            "reference_build": "SYN-build",
            "reference_version": "v1",
            "references": copy.deepcopy(self.references),
        }
        self.compatibility = {
            "schema_version": 1,
            "workflows": [{
                "workflow_id": "synthetic-workflow",
                "workflow_version": "v1",
                "reference_sets": [copy.deepcopy(self.references)],
            }],
        }
        self.transport = MemoryTransport()
        self.zone = ReferenceZone(self.transport, None, None)
        self.zone.publish(self.genome, [artifact("reference.fa.gz")], "2026-09-15T00:00:00Z")
        self.zone.publish(self.annotation, [artifact("genes.gtf.gz")], "2026-09-15T00:00:00Z")
        self.allocate = Mock(return_value="SYN-ALLOCATION-001")

    def submit(self):
        return submit_workflow(
            self.request, self.compatibility, self.zone, self.allocate,
        )

    def assert_rejected_without_allocation(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.submit()
        self.allocate.assert_not_called()

    def test_accepted_submission_pins_exact_published_manifests_before_allocation(self):
        self.assertEqual(self.submit(), "SYN-ALLOCATION-001")

        self.allocate.assert_called_once()
        prepared = self.allocate.call_args.args[0]
        self.assertEqual(prepared["reference_build"], "SYN-build")
        self.assertEqual(prepared["reference_version"], "v1")
        self.assertEqual(len(prepared["references"]), 2)
        for resolved in prepared["references"]:
            entry = {field: resolved[field] for field in ("type", "name", "version")}
            payload = self.transport.get(reference_path(entry))
            self.assertEqual(resolved["manifest_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(resolved["manifest_uri"], self.transport.uri(reference_path(entry)))
            self.assertTrue(resolved["artifacts"])
            for pinned in resolved["artifacts"]:
                self.assertEqual(
                    pinned["uri"], self.transport.uri(reference_path(entry, pinned["filename"]))
                )

    def test_incompatible_workflow_reference_pair_never_allocates(self):
        self.request["references"][0]["name"] = "SYN-other-build"
        self.assert_rejected_without_allocation("Incompatible")

    def test_unavailable_exact_version_never_allocates_or_uses_available_successor(self):
        successor = {**self.genome, "version": "v2"}
        self.zone.publish(successor, [artifact("reference.fa.gz")], "2026-09-15T01:00:00Z")
        self.request["references"][0]["version"] = "missing-v1"
        self.request["reference_version"] = "missing-v1"
        self.compatibility["workflows"][0]["reference_sets"] = [
            copy.deepcopy(self.request["references"])
        ]

        self.assert_rejected_without_allocation("unavailable.*no fallback")

    def test_missing_reference_version_never_allocates(self):
        del self.request["reference_version"]
        self.assert_rejected_without_allocation("exactly")

    def test_mismatched_explicit_reference_build_never_allocates(self):
        self.request["reference_build"] = "SYN-other-build"
        self.assert_rejected_without_allocation("reference_build/reference_version")

    def test_invalid_or_mismatched_published_manifest_never_allocates(self):
        manifest_path = reference_path(self.genome)
        original = self.transport.objects[manifest_path]
        cases = [
            b"not-json",
            original.replace(b'"name": "SYN-build"', b'"name": "SYN-other"'),
            original.replace(b'"sha256": "', b'"sha256": "not-a-digest'),
        ]
        for payload in cases:
            with self.subTest(payload=payload[:20]):
                self.allocate.reset_mock()
                self.transport.objects[manifest_path] = payload
                self.assert_rejected_without_allocation("valid JSON|does not match|sha256")
        self.transport.objects[manifest_path] = original

    def test_repository_compatibility_manifest_declares_an_explicit_versioned_set(self):
        with COMPATIBILITY_PATH.open(encoding="utf-8") as source:
            compatibility = json.load(source, object_pairs_hook=unique_object)
        workflow = compatibility["workflows"][0]
        request = {
            "run_id": "SYN-MANIFEST-CHECK",
            "workflow_id": workflow["workflow_id"],
            "workflow_version": workflow["workflow_version"],
            "reference_build": next(
                reference["name"] for reference in workflow["reference_sets"][0]
                if reference["type"] == "genome"
            ),
            "reference_version": next(
                reference["version"] for reference in workflow["reference_sets"][0]
                if reference["type"] == "genome"
            ),
            "references": copy.deepcopy(workflow["reference_sets"][0]),
        }

        resolved = validate_request_compatibility(request, compatibility)

        self.assertEqual(len(resolved), 3)
        self.assertTrue(all(key[2] == "ensembl-116" for key in resolved))


if __name__ == "__main__":
    unittest.main()
