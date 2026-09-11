import hashlib
import io
import json
import unittest

from scripts.publish_reference import (
    ReferenceExistsError, ReferenceZone, manifest_document, parse_inventory, reference_path,
    validate_entry,
)

GRCH38 = {"type": "genome", "name": "GRCh38", "version": "2026-09-11"}
HG19 = {"type": "genome", "name": "hg19", "version": "2026-09-11"}


class RecordingTransport:
    """In-memory stand-in for the reference container."""

    def __init__(self):
        self.objects = {}
        self.immutable = set()

    def exists(self, path):
        return path in self.objects

    def put(self, path, chunks):
        self._guard(path)
        self.objects[path] = b"".join(chunks)

    def put_bytes(self, path, payload):
        self._guard(path)
        self.objects[path] = payload

    def get(self, path):
        return self.objects[path]

    def list(self, prefix):
        return [path for path in self.objects if path.startswith(prefix)]

    def _guard(self, path):
        # Mirrors container-level WORM: creating a new path is allowed, overwriting is not.
        if path in self.immutable:
            raise PermissionError(f"{path} is immutable")
        self.immutable.add(path)


def artifact(filename, payload, source=None):
    return {"filename": filename, "open": lambda: io.BytesIO(payload), "source": source}


class ReferencePublicationTests(unittest.TestCase):
    def setUp(self):
        self.transport = RecordingTransport()
        self.zone = ReferenceZone(self.transport)

    def test_published_version_records_a_checksum_for_every_artifact(self):
        payload = b"synthetic reference bytes"
        document = self.zone.publish(
            GRCH38, [artifact("reference.fa.gz", payload, "https://example.invalid/ref")],
            "2026-09-11T00:00:00Z",
        )

        self.assertEqual(document["type"], "genome")
        self.assertEqual(document["name"], "GRCh38")
        self.assertEqual(document["version"], "2026-09-11")
        self.assertEqual(len(document["artifacts"]), 1)
        recorded = document["artifacts"][0]
        self.assertEqual(recorded["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(recorded["size_bytes"], len(payload))
        self.assertEqual(recorded["source"], "https://example.invalid/ref")

    def test_inventory_returns_type_name_and_version_for_each_entry(self):
        self.zone.publish(GRCH38, [artifact("a.fa.gz", b"a")], "2026-09-11T00:00:00Z")
        self.zone.publish(HG19, [artifact("b.fa.gz", b"b")], "2026-09-11T00:00:00Z")
        self.zone.publish(
            {"type": "gene-annotation", "name": "GRCh38-genes", "version": "115"},
            [artifact("genes.gtf.gz", b"c")], "2026-09-11T00:00:00Z",
        )

        inventory = self.zone.inventory()
        self.assertEqual(len(inventory), 3)
        for entry in inventory:
            for field in ("type", "name", "version"):
                self.assertTrue(entry[field], f"{field} must be reported")
        self.assertEqual(
            [(e["type"], e["name"], e["version"]) for e in inventory],
            [("gene-annotation", "GRCh38-genes", "115"),
             ("genome", "GRCh38", "2026-09-11"),
             ("genome", "hg19", "2026-09-11")],
        )

    def test_publishing_over_an_existing_version_is_refused(self):
        self.zone.publish(GRCH38, [artifact("a.fa.gz", b"original")], "2026-09-11T00:00:00Z")

        with self.assertRaises(ReferenceExistsError):
            self.zone.publish(GRCH38, [artifact("a.fa.gz", b"replacement")],
                              "2026-09-11T01:00:00Z")

        stored = json.loads(self.transport.get(reference_path(GRCH38)))
        self.assertEqual(stored["published_at"], "2026-09-11T00:00:00Z")
        self.assertEqual(self.transport.get(reference_path(GRCH38, "a.fa.gz")), b"original")

    def test_a_new_version_publishes_and_leaves_the_prior_version_retrievable(self):
        self.zone.publish(GRCH38, [artifact("a.fa.gz", b"original")], "2026-09-11T00:00:00Z")
        successor = {**GRCH38, "version": "2026-09-12"}

        self.zone.publish(successor, [artifact("a.fa.gz", b"corrected")], "2026-09-12T00:00:00Z")

        self.assertIsNotNone(self.zone.get_manifest(GRCH38))
        self.assertIsNotNone(self.zone.get_manifest(successor))
        self.assertEqual(self.transport.get(reference_path(GRCH38, "a.fa.gz")), b"original")
        self.assertEqual(self.transport.get(reference_path(successor, "a.fa.gz")), b"corrected")
        self.assertEqual(
            [e["version"] for e in self.zone.inventory()], ["2026-09-11", "2026-09-12"]
        )

    def test_multiple_builds_coexist_and_stay_distinguishable(self):
        self.zone.publish(GRCH38, [artifact("a.fa.gz", b"38")], "2026-09-11T00:00:00Z")
        self.zone.publish(HG19, [artifact("a.fa.gz", b"19")], "2026-09-11T00:00:00Z")

        self.assertEqual(self.transport.get(reference_path(GRCH38, "a.fa.gz")), b"38")
        self.assertEqual(self.transport.get(reference_path(HG19, "a.fa.gz")), b"19")

    def test_paths_are_laid_out_as_type_name_version(self):
        self.assertEqual(reference_path(GRCH38, "a.fa.gz"), "genome/GRCh38/2026-09-11/a.fa.gz")
        self.assertEqual(reference_path(GRCH38), "genome/GRCh38/2026-09-11/manifest.json")

    def test_invalid_entries_and_filenames_are_rejected(self):
        rejected = [
            ({"type": "unknown", "name": "GRCh38", "version": "1"}, "unknown type"),
            ({"type": "genome", "name": "../escape", "version": "1"}, "traversal in name"),
            ({"type": "genome", "name": "GRCh38", "version": "a/b"}, "separator in version"),
            ({"type": "genome", "name": "", "version": "1"}, "empty name"),
            ({"type": "genome", "name": "GRCh38"}, "missing version"),
        ]
        for entry, reason in rejected:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    validate_entry(entry)

        with self.assertRaises(ValueError):
            reference_path(GRCH38, "../escape.fa")

    def test_a_version_must_contain_at_least_one_artifact(self):
        with self.assertRaises(ValueError):
            self.zone.publish(GRCH38, [], "2026-09-11T00:00:00Z")
        with self.assertRaises(ValueError):
            manifest_document(GRCH38, [], "2026-09-11T00:00:00Z")
        self.assertEqual(self.zone.inventory(), [])

    def test_inventory_is_empty_before_anything_is_published(self):
        self.assertEqual(parse_inventory([]), [])
        self.assertEqual(self.zone.inventory(), [])
        self.assertIsNone(self.zone.get_manifest(GRCH38))


if __name__ == "__main__":
    unittest.main()
