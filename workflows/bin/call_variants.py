#!/usr/bin/env python3
"""Nextflow bin: variant-calling stage. Naive per-position mismatch caller
producing VCF or GVCF. Not GATK-equivalent; no biological validation claimed.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.secondary_pipeline import StageFailure, run_variant_calling  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-format", choices=("vcf", "gvcf"), default="vcf")
    parser.add_argument("--force-fail", action="store_true")
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    sample = {
        "sample_id": manifest["sample_id"],
        "contig": manifest["contig"],
        "contig_length": manifest["contig_length"],
        "reference_fasta": Path(manifest["reference_fasta"]),
        "reads_r1": Path(manifest["reads_r1"]),
        "reference_build": manifest["reference_build"],
        "reference_version": manifest["reference_version"],
    }
    try:
        result = run_variant_calling(
            sample, {}, Path("."), output_format=arguments.output_format,
            force_fail=arguments.force_fail,
        )
    except StageFailure as failure:
        print(str(failure), file=sys.stderr)
        return 1

    print(json.dumps({
        "format": result["format"], "variants_path": str(result["variants_path"]),
        "variant_count": result["variant_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())