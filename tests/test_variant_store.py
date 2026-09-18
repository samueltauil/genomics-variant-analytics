import tempfile
import unittest
from pathlib import Path

from scripts.variant_store import VARIANT_FIELDS, VariantStore


def synthetic_vcf(*rows):
    return "\n".join([
        "##fileformat=VCFv4.3",
        "##INFO=<ID=GENE,Number=1,Type=String,Description=\"Synthetic gene\">",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYN-SAMPLE-001",
        *rows,
        "",
    ])


def provenance(run_id="SYN-RUN-001", pipeline_version="release-1.0.0", source="abfss://synthetic/vcf/run.vcf"):
    return {
        "run_id": run_id,
        "sample_id": "SYN-SAMPLE-001",
        "research_subject_id": "SYN-SUBJECT-001",
        "cohort_id": "SYN-COHORT-001",
        "pipeline_version": pipeline_version,
        "reference_build": "GRCh38",
        "reference_version_or_digest": "manifest-sha256:synthetic-reference-001",
        "classification": "genomic-variant",
        "source_file_uri": source,
        "ingestion_timestamp": "2026-09-15T18:00:00-04:00",
    }


class VariantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = VariantStore(Path(self.temporary.name) / "bronze.sqlite3")
        self.addCleanup(self.store.close)

    def test_schema_is_exactly_the_twenty_spec_fields(self):
        self.assertEqual(self.store.schema_fields(), VARIANT_FIELDS)

    def test_vcf_core_info_and_format_fields_load(self):
        vcf = synthetic_vcf(
            "1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1;TRANSCRIPT=TX1;CONSEQUENCE=missense_variant;AF=0.25\tGT:DP\t0/1:20",
            "2\t202\t.\tC\tT\t.\tPASS\tGENE=GENE2\tGT\t1/1",
        )
        result = self.store.ingest_vcf_text(vcf, provenance())
        self.assertEqual((result["accepted_count"], result["rejected_count"]), (2, 0))
        rows = self.store.records()
        self.assertEqual(rows[0]["CHROM"], "1")
        self.assertEqual(rows[0]["POS"], 101)
        self.assertEqual(rows[0]["gene"], "GENE1")
        self.assertEqual(rows[0]["transcript"], "TX1")
        self.assertEqual(rows[0]["variant_consequence"], "missense_variant")
        self.assertEqual(rows[0]["genotype"], "0/1")
        self.assertEqual(rows[0]["allele_frequency"], 0.25)
        self.assertIsNone(rows[1]["ID"])

    def test_missing_mandatory_fields_are_rejected_and_counted(self):
        vcf = synthetic_vcf(
            "1\t101\tSYN-VAR-001\t\tG\t99\tPASS\t.\tGT\t0/1",
            "1\t102\tSYN-VAR-002\tA\t\t99\tPASS\t.\tGT\t0/1",
            "1\t103\tSYN-VAR-003\tA\tG\t99\tPASS\t.\tGT\t0/1",
        )
        result = self.store.ingest_vcf_text(vcf, provenance())
        self.assertEqual((result["accepted_count"], result["rejected_count"]), (1, 2))
        self.assertEqual(len(self.store.records()), 1)
        rejected = self.store.rejected_records("SYN-RUN-001")
        self.assertEqual([entry["source_line_number"] for entry in rejected], [4, 5])
        self.assertIn("Missing mandatory field: REF", rejected[0]["reason"])
        self.assertIn("Missing mandatory field: ALT", rejected[1]["reason"])

    def test_unannotated_fields_are_null_without_row_loss(self):
        result = self.store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1"),
            provenance(),
        )
        self.assertEqual(result["accepted_count"], 1)
        row = self.store.records()[0]
        for field in ("gene", "transcript", "variant_consequence", "allele_frequency"):
            self.assertIsNone(row[field])

    def test_run_provenance_has_immutable_reference_identity_and_resolves(self):
        self.store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1"),
            provenance(),
        )
        run = self.store.provenance("SYN-RUN-001")
        row = self.store.records()[0]
        self.assertEqual(row["source_file_uri"], run["source_file_uri"])
        self.assertEqual(row["reference_build"], run["reference_build"])
        self.assertEqual(run["reference_version_or_digest"], "manifest-sha256:synthetic-reference-001")
        self.assertEqual(self.store.classification_for_run("SYN-RUN-001"), "genomic-variant")

    def test_classification_is_adjacent_metadata_without_changing_variant_schema(self):
        self.store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1"),
            provenance(),
        )
        rows = self.store.records_with_classification()
        self.assertEqual(rows[0]["classification"], "genomic-variant")
        self.assertEqual(tuple(field for field in rows[0] if field != "classification"),
                         VARIANT_FIELDS)

    def test_same_artifact_and_pipeline_is_idempotent(self):
        vcf = synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1")
        first = self.store.ingest_vcf_text(vcf, provenance())
        second = self.store.ingest_vcf_text(
            vcf, {**provenance(), "run_id": "SYN-RUN-RETRY"}
        )
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(len(self.store.records()), 1)

    def test_new_pipeline_version_keeps_reprocessed_rows_separable(self):
        vcf = synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1")
        self.store.ingest_vcf_text(vcf, provenance())
        self.store.ingest_vcf_text(
            vcf,
            provenance(
                run_id="SYN-RUN-002",
                pipeline_version="release-2.0.0",
            ),
        )
        self.assertEqual(
            {row["pipeline_version"] for row in self.store.records()},
            {"release-1.0.0", "release-2.0.0"},
        )

    def test_onelake_shortcut_resolves_to_one_adls_artifact_after_tiering(self):
        adls_uri = "abfss://genomics@synthetic.dfs.core.windows.net/vcf/SYN-RUN-001.vcf"
        self.store.register_adls_artifact("SYN-ARTIFACT-001", adls_uri)
        shortcut = self.store.configure_onelake_shortcut(
            "synthetic-vcf",
            "onelake://shortcuts/synthetic-vcf",
            adls_uri,
            artifact_id="SYN-ARTIFACT-001",
        )
        self.assertEqual(shortcut.adls_uri, adls_uri)
        before = self.store.resolve_source_file_uri(shortcut.shortcut_uri)
        self.store.update_artifact_tier(adls_uri, "cool")
        after = self.store.resolve_source_file_uri(shortcut.shortcut_uri)
        self.assertEqual(before.canonical_adls_uri, after.canonical_adls_uri)
        self.assertEqual(after.artifact_id, "SYN-ARTIFACT-001")
        self.assertEqual(after.current_tier, "cool")

    def test_shortcut_source_uri_is_validated_and_kept_as_lineage_value(self):
        adls_uri = "abfss://genomics@synthetic.dfs.core.windows.net/vcf/SYN-RUN-002.vcf"
        self.store.register_adls_artifact("SYN-ARTIFACT-002", adls_uri)
        self.store.configure_onelake_shortcut(
            "synthetic-vcf-2",
            "onelake://shortcuts/synthetic-vcf-2",
            adls_uri,
            artifact_id="SYN-ARTIFACT-002",
        )
        result = self.store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t50\tPASS\t.\tGT\t0/1"),
            provenance(
                run_id="SYN-RUN-002",
                source="onelake://shortcuts/synthetic-vcf-2",
            ),
        )
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(self.store.records()[0]["source_file_uri"],
                         "onelake://shortcuts/synthetic-vcf-2")
        resolution = self.store.resolve_source_file_uri(
            self.store.records()[0]["source_file_uri"]
        )
        self.assertEqual(resolution.canonical_adls_uri, adls_uri)

    def test_layout_and_maintenance_state_are_inspectable(self):
        initial = self.store.inspect_table_layout()
        self.assertEqual(initial["strategy"], "clustered")
        self.assertEqual(initial["clustering_columns"], ("gene", "sample_id", "cohort_id"))
        self.assertEqual(initial["maintenance_state"], "not_run")
        self.store.configure_table_layout(
            clustering_columns=("gene", "cohort_id"),
            rationale="Synthetic local evidence for governed cohort queries.",
        )
        maintenance = self.store.record_maintenance(
            state="succeeded",
            operation="local-reference-optimize",
            completed_at="2026-09-15T19:00:00-04:00",
        )
        self.assertEqual(maintenance["clustering_columns"], ("gene", "cohort_id"))
        self.assertEqual(maintenance["maintenance_state"], "succeeded")
        self.assertEqual(maintenance["last_maintenance_operation"],
                         "local-reference-optimize")


if __name__ == "__main__":
    unittest.main()
