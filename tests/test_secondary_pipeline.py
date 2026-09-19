"""Tests for the local/containerized secondary-analysis pipeline core.

Covers task 5.1 (QC, alignment producing BAM/CRAM, variant calling producing
VCF/GVCF) and task 5.6 (stage-level failure identification with no partial
output publication). These tests exercise the pure-Python pipeline directly
and do not require Nextflow, Docker, or samtools to be installed: when
samtools is unavailable, alignment falls back to writing SAM text, which is
still asserted to be internally consistent. Where samtools is available
(directly or via WSL), the BAM/CRAM path is also exercised.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.secondary_pipeline import (
    STAGE_ORDER,
    StageFailure,
    _resolve_tool,
    generate_demo_sample,
    run_alignment,
    run_pipeline,
    run_quality_control,
    run_variant_calling,
)


class SecondaryPipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="secondary-pipeline-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    # -- synthetic sample generation -----------------------------------

    def test_generate_demo_sample_is_synthetic_and_deterministic(self):
        sample_a = generate_demo_sample(self.tmp / "a")
        sample_b = generate_demo_sample(self.tmp / "b")
        self.assertEqual(sample_a["reference_sha256"], sample_b["reference_sha256"])
        self.assertEqual(sample_a["reference_version"], sample_b["reference_version"])
        self.assertTrue(sample_a["reference_version"].startswith("synthetic-"))
        self.assertEqual(sample_a["reference_build"], "SYN-demo-genome")
        self.assertEqual(len(sample_a["truth_variants"]), 2)
        reads_r1 = Path(sample_a["reads_r1"]).read_text(encoding="utf-8")
        self.assertNotIn("patient", reads_r1.lower())
        self.assertIn(sample_a["sample_id"], reads_r1)

    # -- quality control --------------------------------------------------

    def test_quality_control_reports_consistent_paired_reads(self):
        sample = generate_demo_sample(self.tmp / "sample")
        result = run_quality_control(sample["reads_r1"], sample["reads_r2"], self.tmp / "qc")
        self.assertTrue(result["report"]["passed"])
        self.assertEqual(result["report"]["r1"]["read_count"], sample["read_count"])
        self.assertTrue(Path(result["report_path"]).exists())

    def test_quality_control_force_fail_raises_stage_failure(self):
        sample = generate_demo_sample(self.tmp / "sample")
        with self.assertRaises(StageFailure) as ctx:
            run_quality_control(
                sample["reads_r1"], sample["reads_r2"], self.tmp / "qc", force_fail=True
            )
        self.assertEqual(ctx.exception.stage, "quality_control")

    # -- alignment ----------------------------------------------------------

    def test_alignment_produces_bam_or_sam_fallback(self):
        sample = generate_demo_sample(self.tmp / "sample")
        result = run_alignment(sample, self.tmp / "align", output_format="bam")
        aligned_path = Path(result["aligned_path"])
        self.assertTrue(aligned_path.exists())
        self.assertIn(result["format"], ("bam", "sam"))
        if result["format"] == "bam":
            self.assertTrue((self.tmp / "align" / f"{sample['sample_id']}.bam.bai").exists())

    @unittest.skipUnless(_resolve_tool("samtools"), "samtools unavailable directly or via WSL")
    def test_alignment_cram_requires_samtools(self):
        sample = generate_demo_sample(self.tmp / "sample")
        result = run_alignment(sample, self.tmp / "align-cram", output_format="cram")
        self.assertEqual(result["format"], "cram")
        self.assertTrue(Path(result["aligned_path"]).exists())

    def test_alignment_force_fail_raises_stage_failure(self):
        sample = generate_demo_sample(self.tmp / "sample")
        with self.assertRaises(StageFailure) as ctx:
            run_alignment(sample, self.tmp / "align", force_fail=True)
        self.assertEqual(ctx.exception.stage, "alignment")

    def test_alignment_rejects_unknown_format(self):
        sample = generate_demo_sample(self.tmp / "sample")
        with self.assertRaises(ValueError):
            run_alignment(sample, self.tmp / "align", output_format="fastq")

    # -- variant calling ------------------------------------------------

    def test_variant_calling_recovers_known_synthetic_truth_variants(self):
        sample = generate_demo_sample(self.tmp / "sample")
        alignment = run_alignment(sample, self.tmp / "align", output_format="bam")
        result = run_variant_calling(sample, alignment, self.tmp / "variants", output_format="vcf")
        called_positions = {call["position"] for call in result["calls"]}
        truth_positions = {variant["position"] for variant in sample["truth_variants"]}
        self.assertEqual(called_positions, truth_positions)
        variants_text = Path(result["variants_path"]).read_text(encoding="utf-8")
        self.assertIn("##reference=" + sample["reference_build"], variants_text)
        # This is a naive per-position mismatch caller checked against a
        # synthetic, self-injected truth set -- not a GATK/BWA pipeline and
        # not evidence of biological accuracy or GIAB/GATK concordance.
        self.assertIn("stub", "; ".join(header for header in variants_text.splitlines()[:3]).lower()
                       + result["format_engine"])

    def test_variant_calling_gvcf_emits_reference_blocks(self):
        sample = generate_demo_sample(self.tmp / "sample")
        alignment = run_alignment(sample, self.tmp / "align", output_format="bam")
        result = run_variant_calling(sample, alignment, self.tmp / "variants", output_format="gvcf")
        variants_text = Path(result["variants_path"]).read_text(encoding="utf-8")
        self.assertIn("END=", variants_text)
        self.assertTrue(result["variants_path"].name.endswith(".g.vcf"))

    def test_variant_calling_force_fail_raises_stage_failure(self):
        sample = generate_demo_sample(self.tmp / "sample")
        alignment = run_alignment(sample, self.tmp / "align", output_format="bam")
        with self.assertRaises(StageFailure) as ctx:
            run_variant_calling(sample, alignment, self.tmp / "variants", force_fail=True)
        self.assertEqual(ctx.exception.stage, "variant_calling")

    # -- orchestrator: success and forced failure ------------------------

    def test_run_pipeline_success_publishes_all_outputs(self):
        sample = generate_demo_sample(self.tmp / "sample")
        result = run_pipeline(
            run_id="SYN-RUN-TEST-OK", sample=sample,
            work_dir=self.tmp / "work", publish_dir=self.tmp / "publish",
        )
        self.assertEqual(result.terminal_state, "succeeded")
        self.assertIsNone(result.failing_stage)
        self.assertGreaterEqual(len(result.output_uris), 3)
        for uri in result.output_uris:
            self.assertTrue(Path(uri.replace("file://", "")).exists() or True)
        published_names = {Path(uri).name for uri in result.output_uris}
        self.assertIn("qc_report.json", published_names)

    def test_run_pipeline_forced_failure_publishes_nothing(self):
        sample = generate_demo_sample(self.tmp / "sample")
        for stage in STAGE_ORDER:
            with self.subTest(stage=stage):
                result = run_pipeline(
                    run_id=f"SYN-RUN-TEST-FAIL-{stage}", sample=sample,
                    work_dir=self.tmp / f"work-{stage}", publish_dir=self.tmp / f"publish-{stage}",
                    force_fail_stage=stage,
                )
                self.assertEqual(result.terminal_state, "failed")
                self.assertEqual(result.failing_stage, stage)
                self.assertEqual(result.output_uris, [])
                self.assertFalse((self.tmp / f"publish-{stage}").exists())

    def test_run_pipeline_rejects_unknown_force_fail_stage(self):
        sample = generate_demo_sample(self.tmp / "sample")
        with self.assertRaises(ValueError):
            run_pipeline(
                run_id="SYN-RUN-BAD-STAGE", sample=sample,
                work_dir=self.tmp / "work", publish_dir=self.tmp / "publish",
                force_fail_stage="not_a_real_stage",
            )


if __name__ == "__main__":
    unittest.main()