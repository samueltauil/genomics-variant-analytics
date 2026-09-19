import hashlib
import io
import json
import sqlite3
import unittest
from datetime import datetime

from scripts.governance import AuthorizationError, GovernancePolicy, reference_subject
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
        self.zone = ReferenceZone(self.transport, None, None)

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


class ReferenceAuditTests(unittest.TestCase):
    """Task 4.4: every reference publish and read is audited, including the denials."""

    PUBLISHER = "SYN-REFERENCE-PUBLISHER"
    READER = "SYN-REFERENCE-READER"

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)
        self.policy = GovernancePolicy(self.connection)
        self.policy.grant_reference_role(self.PUBLISHER, "reference_publisher")
        self.policy.grant_reference_role(self.READER, "reference_reader")
        self.transport = RecordingTransport()

    def zone(self, principal_id):
        return ReferenceZone(self.transport, self.policy, principal_id)

    def publish(self, principal_id, entry=GRCH38):
        return self.zone(principal_id).publish(
            entry, [artifact("reference.fa.gz", b"synthetic reference bytes")],
            "2026-09-11T00:00:00Z",
        )

    def test_authorized_and_denied_publish_both_produce_a_complete_audit_entry(self):
        self.publish(self.PUBLISHER)
        with self.assertRaises(AuthorizationError):
            self.publish(self.READER, HG19)

        allowed, denied = self.policy.reference_audit_entries()
        for audit_entry, principal, outcome in (
            (allowed, self.PUBLISHER, "authorized"),
            (denied, self.READER, "denied"),
        ):
            with self.subTest(outcome=outcome):
                self.assertEqual(audit_entry["principal_id"], principal)
                self.assertEqual(audit_entry["operation"], "publish_reference")
                self.assertEqual(audit_entry["affected_data"]["outcome"], outcome)
                self.assertEqual(audit_entry["affected_data"]["entry_type"], "genome")
                self.assertEqual(audit_entry["affected_data"]["reference_role"],
                                 "reference_publisher")
                self.assertTrue(audit_entry["recorded_at"].endswith("Z"))
                self.assertIsNotNone(
                    datetime.fromisoformat(
                        audit_entry["recorded_at"].replace("Z", "+00:00")
                    ).tzinfo
                )
        self.assertEqual(allowed["affected_data"]["entry"], "genome/GRCh38/2026-09-11")
        self.assertEqual(allowed["affected_data"]["entry_name"], "GRCh38")
        self.assertEqual(allowed["affected_data"]["version"], "2026-09-11")
        self.assertEqual(denied["affected_data"]["entry"], "genome/hg19/2026-09-11")
        self.assertEqual(denied["affected_data"]["entry_name"], "hg19")
        self.assertEqual(denied["affected_data"]["version"], "2026-09-11")
        self.assertTrue(self.policy.audit.verify())

    def test_denied_publish_writes_nothing_to_the_zone(self):
        with self.assertRaises(AuthorizationError):
            self.publish(self.READER)
        self.assertEqual(self.transport.objects, {})
        self.assertFalse(self.zone(self.PUBLISHER).is_published(GRCH38))

    def test_reads_are_audited_against_the_reader_role(self):
        self.publish(self.PUBLISHER)
        reader = self.zone(self.READER)
        self.assertIsNotNone(reader.get_manifest(GRCH38))
        self.assertEqual(len(reader.inventory()), 1)

        operations = [entry["operation"] for entry in self.policy.reference_audit_entries()]
        self.assertEqual(operations, [
            "publish_reference", "read_reference_manifest", "list_reference_manifests",
        ])
        reads = self.policy.reference_audit_entries()[1:]
        self.assertTrue(all(
            entry["affected_data"]["outcome"] == "authorized" for entry in reads
        ))
        self.assertEqual(reads[0]["affected_data"]["entry_type"], "genome")
        self.assertEqual(reads[0]["affected_data"]["entry_name"], "GRCh38")
        self.assertEqual(reads[0]["affected_data"]["version"], "2026-09-11")

    def test_a_publisher_grant_does_not_carry_read_access(self):
        self.publish(self.PUBLISHER)
        with self.assertRaises(AuthorizationError):
            self.zone(self.PUBLISHER).get_manifest(GRCH38)
        with self.assertRaises(AuthorizationError):
            self.zone(self.READER).publish(
                HG19, [artifact("reference.fa.gz", b"synthetic")], "2026-09-11T00:00:00Z",
            )
        denials = [entry for entry in self.policy.reference_audit_entries()
                   if entry["affected_data"]["outcome"] == "denied"]
        self.assertEqual([entry["affected_data"]["reference_role"] for entry in denials],
                         ["reference_reader", "reference_publisher"])

    def test_an_absent_version_is_audited_as_a_read_attempt(self):
        self.assertIsNone(self.zone(self.READER).get_manifest(GRCH38))
        entry = self.policy.reference_audit_entries()[-1]
        self.assertEqual(entry["operation"], "read_reference_manifest")
        self.assertEqual(entry["affected_data"]["outcome"], "authorized")
        self.assertEqual(entry["affected_data"]["entry"], "genome/GRCh38/2026-09-11")

    def test_reference_audit_entries_are_append_only_and_hash_chained(self):
        self.publish(self.PUBLISHER)
        self.zone(self.READER).get_manifest(GRCH38)

        self.assertTrue(self.policy.audit.verify())
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE governance_audit SET operation = 'tampered' WHERE event_id = 1"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM governance_audit WHERE event_id = 1"
            )
        self.assertTrue(self.policy.audit.verify())

    def test_a_governor_and_principal_must_be_supplied_together(self):
        for governor, principal in ((self.policy, None), (None, self.PUBLISHER)):
            with self.subTest(principal=principal):
                with self.assertRaisesRegex(ValueError, "together"):
                    ReferenceZone(self.transport, governor, principal)

    def test_audit_subjects_are_validated_rather_than_invented(self):
        for entry in ({"type": "genome", "name": "GRCh38"},
                      {"type": "genome", "name": "GRCh38", "version": "", "extra": 1},
                      {"type": "genome", "name": "GRCh38", "version": None}):
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    reference_subject(entry)
        self.assertEqual(reference_subject(None),
                         {"entry": None, "entry_type": None, "entry_name": None, "version": None})
        with self.assertRaises(ValueError):
            self.policy.authorize_reference(self.PUBLISHER, "reference_owner", "publish_reference")


if __name__ == "__main__":
    unittest.main()
