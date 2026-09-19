"""Core stage logic for the local/containerized secondary-analysis pipeline.

Implements quality control, alignment, and variant calling as pure-Python
processing over a tiny, runtime-generated synthetic demo sample, plus the
orchestrator that runs the stages in order, applies stage-level failure
handling, and assembles the run provenance record.

Nothing here reads or writes real sequencing data: `generate_demo_sample`
fabricates a small synthetic reference and synthetic paired reads with known,
deterministically injected variants, entirely in memory / in a caller-supplied
scratch directory. Callers must never commit generated files.

Alignment and variant calling here are intentionally simple stand-ins, not a
validated bioinformatics pipeline: there is no real short-read aligner (no
BWA) and no GATK-equivalent caller. Container/BAM realism is provided by
`samtools` when it is available (directly, or through WSL on a Windows
sandbox); when it is not available, a syntactically valid SAM text file is
produced instead and the aligned output is honestly reported as SAM, never
mislabeled as BAM/CRAM. This module does not claim biological validation,
alignment accuracy, or GATK concordance.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE_ORDER = ("quality_control", "alignment", "variant_calling")

DEMO_REFERENCE_BUILD = "SYN-demo-genome"
DEMO_CONTIG = "SYN-chr1"


class StageFailure(RuntimeError):
    """Raised by a stage to signal a deliberate or genuine stage failure."""

    def __init__(self, stage: str, message: str):
        if stage not in STAGE_ORDER:
            raise ValueError(f"Unknown stage: {stage}.")
        super().__init__(f"{stage} failed: {message}")
        self.stage = stage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Synthetic demo sample generation (runtime only; never committed)
# --------------------------------------------------------------------------

def _synthetic_sequence(seed: int, length: int) -> str:
    bases = "ACGT"
    state = seed & 0xFFFFFFFF
    out = []
    for _ in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        out.append(bases[(state >> 16) % 4])
    return "".join(out)


def generate_demo_sample(scratch_dir: Path, sample_id: str = "SYN-SAMPLE-0001",
                          read_count: int = 12, seed: int = 20260919) -> dict[str, Any]:
    """Write a tiny synthetic reference + paired FASTQ reads under `scratch_dir`.

    Returns a manifest describing the generated files, the explicit reference
    build/version (an immutable digest of the generated reference content),
    and the truth variant positions/alleles used to inject synthetic SNPs, so
    tests can check the caller against a known answer without claiming any
    real biological truth set.
    """
    scratch_dir = Path(scratch_dir)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    reference_sequence = _synthetic_sequence(seed, 120)
    reference_digest = _sha256_text(reference_sequence)
    reference_version = f"synthetic-{reference_digest[:12]}"

    reference_fasta = scratch_dir / "reference.fasta"
    reference_fasta.write_text(
        f">{DEMO_CONTIG} synthetic demo reference, not a real genome\n"
        + "\n".join(reference_sequence[i:i + 60] for i in range(0, len(reference_sequence), 60))
        + "\n",
        encoding="utf-8",
    )

    # Deterministic, known variant truth: substitute the base at each position
    # with a different, fixed base so the caller under test has a documented
    # answer to check against. This is a synthetic truth set for pipeline
    # portability testing only -- not a GIAB/GATK truth set.
    truth_variants = []
    for position in (30, 75):
        reference_base = reference_sequence[position - 1]
        alt_base = next(base for base in "ACGT" if base != reference_base)
        truth_variants.append({
            "contig": DEMO_CONTIG, "position": position,
            "reference_base": reference_base, "alt_base": alt_base,
        })

    mutated = list(reference_sequence)
    for variant in truth_variants:
        mutated[variant["position"] - 1] = variant["alt_base"]
    mutated_sequence = "".join(mutated)

    # Alternate between the variant-carrying and reference-matching copy so
    # the caller sees a mixed-genotype-like signal at both truth positions.
    reads = [
        mutated_sequence if index % 2 == 0 else reference_sequence
        for index in range(read_count)
    ]
    read_ids = [f"{sample_id}:read{index + 1:04d}" for index in range(read_count)]

    def _write_fastq(path: Path, mate: int) -> None:
        lines = []
        for read_id, sequence in zip(read_ids, reads):
            lines.append(f"@{read_id}/{mate}")
            lines.append(sequence)
            lines.append("+")
            lines.append("I" * len(sequence))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reads_r1 = scratch_dir / f"{sample_id}_R1.fastq"
    reads_r2 = scratch_dir / f"{sample_id}_R2.fastq"
    _write_fastq(reads_r1, 1)
    _write_fastq(reads_r2, 2)

    return {
        "sample_id": sample_id,
        "reference_fasta": reference_fasta,
        "reference_build": DEMO_REFERENCE_BUILD,
        "reference_version": reference_version,
        "reference_sha256": reference_digest,
        "contig": DEMO_CONTIG,
        "contig_length": len(reference_sequence),
        "reads_r1": reads_r1,
        "reads_r2": reads_r2,
        "read_count": read_count,
        "truth_variants": truth_variants,
    }


# --------------------------------------------------------------------------
# External tool execution (direct PATH, or through WSL on a Windows sandbox)
# --------------------------------------------------------------------------

def _wsl_path(path: Path) -> str:
    path = Path(path).resolve()
    drive = path.drive.rstrip(":").lower()
    rest = str(path)[len(path.drive):].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive}/{rest}"


def _resolve_tool(name: str):
    """Return a callable(args, cwd) that runs `name`, or None if unavailable.

    Prefers the tool directly on PATH (the portable, Linux/container case).
    Falls back to invoking it through WSL only when running on Windows and
    the tool is not directly on PATH -- a development convenience for this
    sandbox, not a substitute for a Linux/container execution target.
    """
    direct = shutil.which(name)
    if direct:
        def _run_direct(args, cwd):
            return subprocess.run(
                [direct, *args], cwd=cwd, capture_output=True, text=True, check=False
            )
        return _run_direct

    if platform.system() == "Windows" and shutil.which("wsl"):
        def _run_via_wsl(args, cwd):
            posix_cwd = _wsl_path(cwd)
            posix_args = [_wsl_path(Path(cwd) / arg) if _looks_like_path(cwd, arg) else arg
                           for arg in args]
            command = " ".join([name, *posix_args])
            return subprocess.run(
                ["wsl", "-e", "bash", "-lc", f"cd '{posix_cwd}' && {command}"],
                capture_output=True, text=True, check=False,
            )
        # Confirm the tool actually resolves inside WSL before offering it.
        probe = subprocess.run(
            ["wsl", "-e", "bash", "-lc", f"command -v {name}"],
            capture_output=True, text=True, check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return _run_via_wsl
    return None


def _looks_like_path(cwd: Path, token: str) -> bool:
    return (Path(cwd) / token).exists()


# --------------------------------------------------------------------------
# Stage 1: quality control (pure Python; no external tool required)
# --------------------------------------------------------------------------

def run_quality_control(reads_r1: Path, reads_r2: Path, outdir: Path, *,
                         force_fail: bool = False) -> dict[str, Any]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if force_fail:
        raise StageFailure("quality_control", "forced failure requested for testing")

    def _read_stats(path: Path) -> dict[str, Any]:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        sequences = lines[1::4]
        if not sequences:
            raise StageFailure("quality_control", f"{path} contains zero reads.")
        lengths = {len(sequence) for sequence in sequences}
        gc = sum(base in "GC" for sequence in sequences for base in sequence)
        total_bases = sum(len(sequence) for sequence in sequences)
        return {
            "read_count": len(sequences),
            "read_lengths": sorted(lengths),
            "gc_fraction": round(gc / total_bases, 4) if total_bases else 0.0,
        }

    r1_stats = _read_stats(reads_r1)
    r2_stats = _read_stats(reads_r2)
    passed = (
        r1_stats["read_count"] == r2_stats["read_count"]
        and len(r1_stats["read_lengths"]) == 1
        and len(r2_stats["read_lengths"]) == 1
    )
    if not passed:
        raise StageFailure("quality_control", "paired read counts/lengths are inconsistent.")

    report = {
        "stage": "quality_control", "passed": True,
        "r1": r1_stats, "r2": r2_stats,
    }
    report_path = outdir / "qc_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"report": report, "report_path": report_path}


# --------------------------------------------------------------------------
# Stage 2: alignment (naive full-length stub aligner + samtools formatting)
# --------------------------------------------------------------------------

def run_alignment(sample: dict[str, Any], outdir: Path, *,
                   output_format: str = "bam", force_fail: bool = False) -> dict[str, Any]:
    if output_format not in ("bam", "cram"):
        raise ValueError("output_format must be 'bam' or 'cram'.")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if force_fail:
        raise StageFailure("alignment", "forced failure requested for testing")

    sample_id = sample["sample_id"]
    contig = sample["contig"]
    contig_length = sample["contig_length"]
    r1_sequences = Path(sample["reads_r1"]).read_text(encoding="utf-8").splitlines()[1::4]
    read_ids = [
        line[1:].rsplit("/", 1)[0]
        for line in Path(sample["reads_r1"]).read_text(encoding="utf-8").splitlines()[0::4]
    ]

    # Naive "aligner": every synthetic read is a full-length copy of the
    # reference starting at position 1, so mapping is a fixed, known
    # placement rather than a real seed-and-extend alignment.
    sam_lines = [
        "@HD\tVN:1.6\tSO:coordinate",
        f"@SQ\tSN:{contig}\tLN:{contig_length}",
        f"@RG\tID:{sample_id}\tSM:{sample_id}",
        f"@CO\tstub-aligner: full-length synthetic placement, not a validated alignment",
    ]
    for read_id, sequence in zip(read_ids, r1_sequences):
        sam_lines.append("\t".join([
            read_id, "0", contig, "1", "60", f"{len(sequence)}M", "*", "0", "0",
            sequence, "I" * len(sequence), f"RG:Z:{sample_id}",
        ]))
    sam_path = outdir / f"{sample_id}.sam"
    sam_path.write_text("\n".join(sam_lines) + "\n", encoding="utf-8")

    samtools = _resolve_tool("samtools")
    if samtools is None:
        return {
            "format": "sam", "format_engine": "stub-no-samtools",
            "aligned_path": sam_path,
            "note": "samtools unavailable; wrote SAM text instead of BAM/CRAM.",
        }

    bam_path = outdir / f"{sample_id}.bam"
    sort_result = samtools(["sort", "-O", "bam", "-o", bam_path.name, sam_path.name], outdir)
    if sort_result.returncode != 0:
        raise StageFailure("alignment", f"samtools sort failed: {sort_result.stderr.strip()}")
    index_result = samtools(["index", bam_path.name], outdir)
    if index_result.returncode != 0:
        raise StageFailure("alignment", f"samtools index failed: {index_result.stderr.strip()}")

    if output_format == "bam":
        return {"format": "bam", "format_engine": "samtools", "aligned_path": bam_path,
                "index_path": outdir / f"{bam_path.name}.bai"}

    shutil.copy(sample["reference_fasta"], outdir / sample["reference_fasta"].name)
    cram_path = outdir / f"{sample_id}.cram"
    cram_result = samtools([
        "view", "-C", "-T", sample["reference_fasta"].name, "-o", cram_path.name, bam_path.name,
    ], outdir)
    if cram_result.returncode != 0:
        raise StageFailure("alignment", f"samtools CRAM conversion failed: {cram_result.stderr.strip()}")
    return {"format": "cram", "format_engine": "samtools", "aligned_path": cram_path}


# --------------------------------------------------------------------------
# Stage 3: variant calling (naive per-position mismatch caller -> VCF/GVCF)
# --------------------------------------------------------------------------

def run_variant_calling(sample: dict[str, Any], alignment: dict[str, Any], outdir: Path, *,
                         output_format: str = "vcf", force_fail: bool = False,
                         min_alt_fraction: float = 0.3) -> dict[str, Any]:
    if output_format not in ("vcf", "gvcf"):
        raise ValueError("output_format must be 'vcf' or 'gvcf'.")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if force_fail:
        raise StageFailure("variant_calling", "forced failure requested for testing")

    sample_id = sample["sample_id"]
    contig = sample["contig"]
    contig_length = sample["contig_length"]
    reference_sequence = Path(sample["reference_fasta"]).read_text(encoding="utf-8")
    reference_sequence = "".join(reference_sequence.splitlines()[1:])
    r1_sequences = Path(sample["reads_r1"]).read_text(encoding="utf-8").splitlines()[1::4]
    if not r1_sequences:
        raise StageFailure("variant_calling", "no aligned reads available for calling.")

    calls = []
    for position in range(1, contig_length + 1):
        reference_base = reference_sequence[position - 1]
        bases_here = [sequence[position - 1] for sequence in r1_sequences]
        counts: dict[str, int] = {}
        for base in bases_here:
            counts[base] = counts.get(base, 0) + 1
        depth = len(bases_here)
        alt_base, alt_count = max(
            ((base, count) for base, count in counts.items() if base != reference_base),
            key=lambda item: item[1], default=(None, 0),
        )
        alt_fraction = alt_count / depth if depth else 0.0
        if alt_base is not None and alt_fraction >= min_alt_fraction:
            genotype = "1/1" if alt_fraction >= 0.9 else "0/1"
            calls.append({
                "position": position, "reference_base": reference_base, "alt_base": alt_base,
                "depth": depth, "alt_count": alt_count, "genotype": genotype,
            })
        elif output_format == "gvcf":
            calls.append({
                "position": position, "reference_base": reference_base, "alt_base": None,
                "depth": depth, "alt_count": 0, "genotype": "0/0",
            })

    header = [
        "##fileformat=VCFv4.2",
        "##source=genomics-variant-accelerator-secondary-pipeline-stub",
        "##reference=" + sample["reference_build"] + "/" + sample["reference_version"],
        f"##contig=<ID={contig},length={contig_length}>",
        '##INFO=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
    ]
    if output_format == "gvcf":
        header.append(
            '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of reference block">'
        )
    header.append("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + sample_id)

    body = []
    for call in calls:
        if call["alt_base"] is None:
            body.append("\t".join([
                contig, str(call["position"]), ".", call["reference_base"], ".", ".", "PASS",
                f"END={call['position']};DP={call['depth']}", "GT:DP", f"0/0:{call['depth']}",
            ]))
        else:
            body.append("\t".join([
                contig, str(call["position"]), ".", call["reference_base"], call["alt_base"],
                "30", "PASS", f"DP={call['depth']}", "GT:DP",
                f"{call['genotype']}:{call['depth']}",
            ]))

    extension = "vcf" if output_format == "vcf" else "g.vcf"
    variants_path = outdir / f"{sample_id}.{extension}"
    variants_path.write_text("\n".join(header + body) + "\n", encoding="utf-8")

    variant_calls = [call for call in calls if call["alt_base"] is not None]
    return {
        "format": output_format, "format_engine": "stub-mismatch-caller",
        "variants_path": variants_path, "variant_count": len(variant_calls),
        "calls": variant_calls,
    }


# --------------------------------------------------------------------------
# Orchestrator: run stages in order, handle stage failure, assemble provenance
# --------------------------------------------------------------------------

@dataclass
class PipelineRunResult:
    run_id: str
    terminal_state: str
    failing_stage: str | None
    start_time: str
    end_time: str
    input_uris: list[str]
    output_uris: list[str]
    log_location: str
    stage_reports: dict[str, Any]


def run_pipeline(*, run_id: str, sample: dict[str, Any], work_dir: Path, publish_dir: Path,
                  aligned_format: str = "bam", variant_format: str = "vcf",
                  force_fail_stage: str | None = None) -> PipelineRunResult:
    """Run QC, alignment, and variant calling in order over `sample`.

    On any stage failure, the run is marked failed with the failing stage
    identified, and nothing is copied into `publish_dir`: outputs from
    completed earlier stages remain only in `work_dir` and are never treated
    as a complete published pipeline result.
    """
    if force_fail_stage is not None and force_fail_stage not in STAGE_ORDER:
        raise ValueError(f"force_fail_stage must be one of {STAGE_ORDER} or None.")

    work_dir = Path(work_dir)
    publish_dir = Path(publish_dir)
    log_path = work_dir / "run.log"
    work_dir.mkdir(parents=True, exist_ok=True)
    start_time = _utc_now()
    stage_reports: dict[str, Any] = {}
    input_uris = [sample["reads_r1"].as_uri(), sample["reads_r2"].as_uri(),
                  sample["reference_fasta"].as_uri()]

    def _log(line: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{_utc_now()} {line}\n")

    _log(f"run {run_id} started")
    try:
        _log("stage quality_control started")
        stage_reports["quality_control"] = run_quality_control(
            sample["reads_r1"], sample["reads_r2"], work_dir / "qc",
            force_fail=(force_fail_stage == "quality_control"),
        )
        _log("stage quality_control completed")

        _log("stage alignment started")
        stage_reports["alignment"] = run_alignment(
            sample, work_dir / "alignment", output_format=aligned_format,
            force_fail=(force_fail_stage == "alignment"),
        )
        _log("stage alignment completed")

        _log("stage variant_calling started")
        stage_reports["variant_calling"] = run_variant_calling(
            sample, stage_reports["alignment"], work_dir / "variants",
            output_format=variant_format, force_fail=(force_fail_stage == "variant_calling"),
        )
        _log("stage variant_calling completed")
    except StageFailure as failure:
        _log(f"stage {failure.stage} FAILED: {failure}")
        end_time = _utc_now()
        return PipelineRunResult(
            run_id=run_id, terminal_state="failed", failing_stage=failure.stage,
            start_time=start_time, end_time=end_time, input_uris=input_uris,
            output_uris=[], log_location=log_path.as_uri(), stage_reports=stage_reports,
        )

    # All stages succeeded: publish outputs atomically as a complete result.
    publish_dir.mkdir(parents=True, exist_ok=True)
    output_uris = []
    for stage_name in ("alignment", "variant_calling"):
        for key in ("aligned_path", "variants_path"):
            path = stage_reports[stage_name].get(key)
            if path is not None:
                destination = publish_dir / Path(path).name
                shutil.copy(path, destination)
                output_uris.append(destination.as_uri())
    qc_destination = publish_dir / "qc_report.json"
    shutil.copy(stage_reports["quality_control"]["report_path"], qc_destination)
    output_uris.append(qc_destination.as_uri())
    _log(f"run {run_id} completed successfully")
    end_time = _utc_now()
    return PipelineRunResult(
        run_id=run_id, terminal_state="succeeded", failing_stage=None,
        start_time=start_time, end_time=end_time, input_uris=input_uris,
        output_uris=output_uris, log_location=log_path.as_uri(), stage_reports=stage_reports,
    )