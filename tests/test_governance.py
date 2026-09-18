import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.governance import AuthorizationError, GovernancePolicy
from scripts.metadata_store import MetadataStore


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.policy = GovernancePolicy(self.connection)
        self.addCleanup(self.connection.close)

    def test_access_tiers_are_independent_and_denials_are_explicit(self):
        self.policy.grant_tier("SYN-COHORT-ANALYST", "cohort_analytics")
        self.policy.grant_tier("SYN-VARIANT-ANALYST", "variant_store")

        self.assertEqual(
            self.policy.read_cohort_aggregates(
                "SYN-COHORT-ANALYST", {"cohort_id": "SYN-COHORT-001", "count": 2}
            )["count"],
            2,
        )
        with self.assertRaises(AuthorizationError):
            self.policy.authorize_raw_file(
                "SYN-COHORT-ANALYST", "abfss://synthetic/raw/SYN-FASTQ-001.fastq.gz"
            )
        with self.assertRaises(AuthorizationError):
            self.policy.authorize_raw_file(
                "SYN-VARIANT-ANALYST", "abfss://synthetic/raw/SYN-BAM-001.bam"
            )
        self.policy.authorize_variant_store("SYN-VARIANT-ANALYST")

        denied = [entry for entry in self.policy.audit.entries()
                  if entry["operation"] == "deny:read_raw_file"]
        self.assertEqual(len(denied), 2)

    def test_projection_withholds_subject_linkage_but_keeps_sample_and_cohort(self):
        self.policy.grant_tier("SYN-DEIDENTIFIED", "variant_store")
        projected = self.policy.project_variant("SYN-DEIDENTIFIED", {
            "CHROM": "1",
            "POS": 101,
            "sample_id": "SYN-SAMPLE-001",
            "research_subject_id": "SYN-SUBJECT-001",
            "cohort_id": "SYN-COHORT-001",
        })
        self.assertEqual(projected["sample_id"], "SYN-SAMPLE-001")
        self.assertEqual(projected["cohort_id"], "SYN-COHORT-001")
        self.assertNotIn("research_subject_id", projected)

    def test_workspace_transfer_requires_approval_and_audit_chain_is_immutable(self):
        self.policy.grant_workspace("SYN-TRANSFER-OPERATOR", "research")
        self.policy.grant_workspace("SYN-TRANSFER-OPERATOR", "clinical")
        with self.assertRaises(AuthorizationError):
            self.policy.transfer_workspace(
                "SYN-TRANSFER-OPERATOR", "clinical", "research", "SYN-DATASET-001"
            )
        approved = self.policy.transfer_workspace(
            "SYN-TRANSFER-OPERATOR", "clinical", "research",
            "SYN-DATASET-001", "SYN-APPROVAL-001",
        )
        self.assertEqual(approved["affected_data"]["approval_id"], "SYN-APPROVAL-001")
        self.assertTrue(self.policy.audit.verify())
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE governance_audit SET operation = 'tampered' WHERE event_id = 1"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM governance_audit WHERE event_id = 1")
        self.assertTrue(self.policy.audit.verify())

    def test_reprocessing_and_patient_linked_metadata_queries_are_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "metadata.sqlite3"
            with MetadataStore(database) as store:
                store.add_entity("SYN-SUBJECT-001", "subject")
                store.add_entity("SYN-SAMPLE-001", "sample", ["SYN-SUBJECT-001"])
                store.set_clinical_metadata(
                    "SYN-SAMPLE-001", {"clinical_status": "synthetic-observed"}
                )
                store.grant_access("SYN-CLINICAL-READER", "clinical_metadata")
                store.add_pipeline_run(
                    "SYN-PIPELINE-001", "synthetic-workflow", "1.0"
                )
                store.record_reprocessing(
                    "SYN-PIPELINE-OPERATOR", "SYN-SAMPLE-001", "1.0", "2.0"
                )
                store.read_clinical_metadata(
                    "SYN-CLINICAL-READER", "SYN-SAMPLE-001"
                )
                types = [entry["event_type"] for entry in store.audit_entries()]
                self.assertIn("pipeline_execution", types)
                self.assertIn("reprocessing", types)
                self.assertTrue(any(
                    entry["operation"] == "read_clinical_metadata"
                    and entry["affected_data"]["subject_linked"]
                    for entry in store.audit_entries()
                ))
                self.assertTrue(store.verify_audit())


if __name__ == "__main__":
    unittest.main()
