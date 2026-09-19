#!/usr/bin/env python3
"""Nextflow bin: synthesize the tiny runtime-only demo sample.

Not a pipeline stage. Writes a synthetic reference FASTA and paired FASTQ
reads plus a manifest into the current (task) working directory, and fails
closed if the caller-declared reference build/version does not match the
generated reference's own content-derived identity -- there is no fallback
to a different or default reference.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.secondary_pipeline import generate_demo_sample  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-build", required=True)
    parser.add_argument("--reference-version", required=True)
    parser.add_argument("--sample-id", default="SYN-SAMPLE-0001")
    parser.add_argument("--read-count", type=int, default=12)
    arguments = parser.parse_args()

    sample = generate_demo_sample(Path("."), sample_id=arguments.sample_id,
                                   read_count=arguments.read_count)

    if sample["reference_build"] != arguments.reference_build:
        print(
            f"Declared reference_build {arguments.reference_build!r} does not match the "
            f"generated demo reference {sample['reference_build']!r}; no substitution permitted.",
            file=sys.stderr,
        )
        return 1
    if sample["reference_version"] != arguments.reference_version:
        print(
            f"Declared reference_version {arguments.reference_version!r} is unavailable for the "
            f"generated demo reference (actual {sample['reference_version']!r}); "
            "no fallback permitted.",
            file=sys.stderr,
        )
        return 1

    manifest = {
        "sample_id": sample["sample_id"],
        "reference_build": sample["reference_build"],
        "reference_version": sample["reference_version"],
        "reference_sha256": sample["reference_sha256"],
        "contig": sample["contig"],
        "contig_length": sample["contig_length"],
        "reference_fasta": sample["reference_fasta"].name,
        "reads_r1": sample["reads_r1"].name,
        "reads_r2": sample["reads_r2"].name,
        "read_count": sample["read_count"],
        "truth_variants": sample["truth_variants"],
    }
    Path("sample_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())