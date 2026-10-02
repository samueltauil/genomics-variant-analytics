"""Compare executor outputs against a synthetic truth set and each other.

This script keeps the comparison logic repository-local and deterministic for
task 5.4. It can emit a minimal truth VCF derived from the synthetic sample
manifest and optionally invoke GATK Concordance when a `gatk` executable is
available on PATH or is supplied explicitly.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Variant:
    chrom: str
    pos: int
    ref: str
    alt: str


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _truth_variants(manifest: dict) -> list[Variant]:
    return [
        Variant(
            chrom=str(item.get("chromosome") or item.get("contig")),
            pos=int(item["position"]),
            ref=str(item.get("reference") or item.get("reference_base")),
            alt=str(item.get("alternate") or item.get("alt_base")),
        )
        for item in manifest["truth_variants"]
    ]


def _write_truth_vcf(manifest: dict, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "##fileformat=VCFv4.2",
        f"##reference={manifest['reference_build']}/{manifest['reference_version']}",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
    ]
    for variant in _truth_variants(manifest):
        lines.append(f"{variant.chrom}\t{variant.pos}\t.\t{variant.ref}\t{variant.alt}\t.\tPASS\t.")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _read_vcf(path: Path) -> list[Variant]:
    variants: list[Variant] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        variants.append(Variant(fields[0], int(fields[1]), fields[3], fields[4]))
    return variants


def _set_metrics(truth: set[Variant], observed: set[Variant]) -> dict[str, float | int]:
    tp = len(truth & observed)
    fp = len(observed - truth)
    fn = len(truth - observed)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    sensitivity = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "sensitivity": sensitivity,
    }


def _gatk_executable(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return shutil.which("gatk")


def _run_gatk_concordance(gatk: str, reference: Path, truth_vcf: Path, eval_vcf: Path, summary_path: Path) -> list[dict[str, str]]:
    subprocess.run(
        [
            gatk,
            "Concordance",
            "-R",
            str(reference),
            "-truth",
            str(truth_vcf),
            "-eval",
            str(eval_vcf),
            "-S",
            str(summary_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with summary_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--reference-fasta", type=Path, required=True)
    parser.add_argument("--batch-vcf", type=Path, required=True)
    parser.add_argument("--slurm-vcf", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--gatk")
    args = parser.parse_args(argv)

    manifest = _load_manifest(args.sample_manifest)
    truth_vcf = _write_truth_vcf(manifest, args.work_dir / "truth.vcf")

    truth = set(_truth_variants(manifest))
    batch = set(_read_vcf(args.batch_vcf))
    slurm = set(_read_vcf(args.slurm_vcf))

    report: dict[str, object] = {
        "reference_build": manifest["reference_build"],
        "reference_version": manifest["reference_version"],
        "truth_variant_count": len(truth),
        "batch_metrics": _set_metrics(truth, batch),
        "slurm_metrics": _set_metrics(truth, slurm),
        "matching_variant_count": len(batch & slurm),
        "batch_only": [
            {"chrom": v.chrom, "pos": v.pos, "ref": v.ref, "alt": v.alt}
            for v in sorted(batch - slurm, key=lambda item: (item.chrom, item.pos, item.ref, item.alt))
        ],
        "slurm_only": [
            {"chrom": v.chrom, "pos": v.pos, "ref": v.ref, "alt": v.alt}
            for v in sorted(slurm - batch, key=lambda item: (item.chrom, item.pos, item.ref, item.alt))
        ],
        "gatk": None,
    }

    gatk = _gatk_executable(args.gatk)
    if gatk:
        report["gatk"] = {
            "batch_vs_truth": _run_gatk_concordance(
                gatk, args.reference_fasta, truth_vcf, args.batch_vcf, args.work_dir / "batch-concordance.tsv"
            ),
            "slurm_vs_truth": _run_gatk_concordance(
                gatk, args.reference_fasta, truth_vcf, args.slurm_vcf, args.work_dir / "slurm-concordance.tsv"
            ),
        }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
