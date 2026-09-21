import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.compare_executor_concordance import _set_metrics, _truth_variants, _write_truth_vcf, _read_vcf
from scripts.secondary_pipeline import generate_demo_sample, run_alignment, run_variant_calling


class CompareExecutorConcordanceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="executor-concordance-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_truth_vcf_matches_manifest_truth_variants(self):
        sample = generate_demo_sample(self.tmp / "sample")
        manifest = {
            "reference_build": sample["reference_build"],
            "reference_version": sample["reference_version"],
            "truth_variants": sample["truth_variants"],
        }
        truth_vcf = _write_truth_vcf(manifest, self.tmp / "truth.vcf")

        expected = set(_truth_variants(manifest))
        observed = set(_read_vcf(truth_vcf))
        self.assertEqual(expected, observed)
        self.assertEqual(sample["reference_version"], manifest["reference_version"])

    def test_metrics_distinguish_matching_and_missing_calls(self):
        sample = generate_demo_sample(self.tmp / "sample")
        alignment = run_alignment(sample, self.tmp / "align", output_format="bam")
        variants = run_variant_calling(sample, alignment, self.tmp / "variants", output_format="vcf")
        manifest = {
            "reference_build": sample["reference_build"],
            "reference_version": sample["reference_version"],
            "truth_variants": sample["truth_variants"],
        }

        truth = set(_truth_variants(manifest))
        called = set(_read_vcf(variants["variants_path"]))
        self.assertEqual(
            _set_metrics(truth, called),
            {
                "true_positives": 2,
                "false_positives": 0,
                "false_negatives": 0,
                "precision": 1.0,
                "sensitivity": 1.0,
            },
        )

        missing_one = set(sorted(called, key=lambda item: item.pos)[1:])
        self.assertEqual(_set_metrics(truth, missing_one)["false_negatives"], 1)


if __name__ == "__main__":
    unittest.main()
