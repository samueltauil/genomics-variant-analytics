"""Launcher that runs the Nextflow secondary-analysis pipeline
(workflows/main.nf) as a subprocess and persists run provenance for both a
successful and a deliberately failed run.

This is the "portable workflow engine" execution path (task 5.1): it invokes
the real `nextflow` binary rather than reimplementing pipeline logic. Stage
outputs and stage-level correctness are produced entirely by
workflows/main.nf and workflows/bin/*.py; this launcher only starts Nextflow,
observes its outcome, and records provenance (task 5.5) with the failing
stage on failure (task 5.6). It never publishes partial outputs itself --
`workflows/main.nf`'s own `PUBLISH_RESULTS` process already only ever runs
when every stage succeeded.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.pipeline_provenance import record_run
    from scripts.secondary_pipeline import (
        validate_synthetic_reference_bundle,
        validate_synthetic_reference_submission,
    )
except ModuleNotFoundError:
    from pipeline_provenance import record_run
    from secondary_pipeline import (
        validate_synthetic_reference_bundle,
        validate_synthetic_reference_submission,
    )


WORKFLOW_ID = "genomics-secondary-analysis"
WORKFLOW_VERSION = "v0.1.0"
STAGE_ORDER = ("quality_control", "alignment", "variant_calling")
PROCESS_TO_STAGE = {
    "QUALITY_CONTROL": "quality_control",
    "ALIGN_READS": "alignment",
    "CALL_VARIANTS": "variant_calling",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_nextflow():
    """Return the argv prefix used to invoke `nextflow`.

    Prefers `nextflow` directly on PATH; falls back to invoking it through
    WSL on a Windows sandbox where Nextflow (which requires a POSIX
    environment) is installed under WSL rather than natively on Windows.
    """
    direct = shutil.which("nextflow")
    if direct:
        return ("direct", direct)
    if shutil.which("wsl"):
        probe = subprocess.run(
            ["wsl", "-e", "bash", "-lc", "command -v ~/nf-bin/nextflow || command -v nextflow"],
            capture_output=True, text=True, check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return ("wsl", probe.stdout.strip())
    raise RuntimeError("nextflow is not available directly or through WSL.")


def _failing_stage_from_log(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Error executing process > '?(\w+)", text)
    if match:
        return PROCESS_TO_STAGE.get(match.group(1))
    return None


def _validate_durable_uri(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        not normalized
        or parsed.scheme not in {"https", "az", "abfs", "abfss"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{label} must be an absolute durable storage URI without query or fragment."
        )
    return normalized.rstrip("/")


def _artifact_uris(directory: Path, durable_base_uri: str | None) -> list[str]:
    paths = sorted(path for path in directory.glob("*") if path.is_file())
    if durable_base_uri:
        return [f"{durable_base_uri}/{quote(path.name)}" for path in paths]
    return [path.resolve().as_uri() for path in paths]


def run(*, run_id: str, work_dir: Path, provenance_db: Path,
        reference_build: str, reference_version: str, reference_manifest_sha256: str,
        profile: str = "standard", input_bundle_dir: Path | None = None,
        execution_target: str = "local", compute_pool: str = "local-dev",
        aligned_format: str = "bam", variant_format: str = "vcf",
        force_fail_stage: str | None = None, input_uri_base: str | None = None,
        output_uri_base: str | None = None, log_uri: str | None = None) -> dict:
    validate_synthetic_reference_submission(
        WORKFLOW_ID,
        WORKFLOW_VERSION,
        reference_build,
        reference_version,
        reference_manifest_sha256,
    )
    if input_bundle_dir:
        validate_synthetic_reference_bundle(
            input_bundle_dir,
            reference_build,
            reference_version,
            reference_manifest_sha256,
        )
    input_uri_base = _validate_durable_uri(input_uri_base, "input_uri_base")
    output_uri_base = _validate_durable_uri(output_uri_base, "output_uri_base")
    log_uri = _validate_durable_uri(log_uri, "log_uri")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    outdir = work_dir / "results"
    project_dir = Path(__file__).resolve().parents[1] / "workflows"

    start_time = _utc_now()
    mode, nextflow_bin = _resolve_nextflow()
    args = [
        "run", str(project_dir / "main.nf"), "-profile", profile,
        "--run_id", run_id, "--reference_build", reference_build,
        "--reference_version", reference_version,
        "--reference_manifest_sha256", reference_manifest_sha256,
        "--aligned_format", aligned_format, "--variant_format", variant_format,
        "--outdir", str(outdir),
    ]
    if input_bundle_dir:
        args += ["--input_bundle_dir", str(Path(input_bundle_dir).resolve())]
    if force_fail_stage:
        args += ["--force_fail_stage", force_fail_stage]

    if mode == "wsl":
        # WSL fallback: translate the run into a single bash -lc invocation.
        def _wsl_path(path: Path) -> str:
            path = Path(path).resolve()
            drive = path.drive.rstrip(":").lower()
            rest = str(path)[len(path.drive):].replace("\\", "/").lstrip("/")
            return f"/mnt/{drive}/{rest}"

        posix_workdir = _wsl_path(work_dir)
        posix_main_nf = _wsl_path(project_dir / "main.nf")
        posix_outdir = _wsl_path(outdir)
        posix_args = " ".join(
            f"'{posix_main_nf}'" if arg == str(project_dir / "main.nf") else
            f"'{posix_outdir}'" if arg == str(outdir) else
            f"'{arg}'" if (" " in arg or arg == "") else arg
            for arg in args
        )
        command = ["wsl", "-e", "bash", "-lc",
                   f"cd '{posix_workdir}' && '{nextflow_bin}' {posix_args}"]
    else:
        command = [nextflow_bin, *args]

    completed = subprocess.run(command, cwd=work_dir, capture_output=True, text=True)
    end_time = _utc_now()

    log_path = work_dir / ".nextflow.log"
    succeeded = completed.returncode == 0 and outdir.exists() and (outdir / "qc_report.json").exists()
    failing_stage = None if succeeded else (_failing_stage_from_log(log_path) or STAGE_ORDER[-1])

    inputs_dir = outdir / "inputs"
    input_uris = _artifact_uris(inputs_dir, input_uri_base) if inputs_dir.exists() else []
    output_uris = (
        _artifact_uris(outdir, output_uri_base)
        if succeeded else []
    )

    record = {
        "run_id": run_id,
        "workflow_id": WORKFLOW_ID,
        "workflow_version": WORKFLOW_VERSION,
        "reference_build": reference_build,
        "reference_version": reference_version,
        "reference_manifest_sha256": reference_manifest_sha256,
        "execution_target": execution_target,
        "compute_pool": compute_pool,
        "input_uris": input_uris,
        "output_uris": output_uris,
        "start_time": start_time,
        "end_time": end_time,
        "terminal_state": "succeeded" if succeeded else "failed",
        "log_location": log_uri or (
            log_path.resolve().as_uri() if log_path.exists() else work_dir.resolve().as_uri()
        ),
        "failing_stage": failing_stage,
    }

    connection = sqlite3.connect(provenance_db)
    connection.row_factory = sqlite3.Row
    try:
        persisted = record_run(connection, record)
    finally:
        connection.close()

    return {
        "terminal_state": record["terminal_state"],
        "failing_stage": failing_stage,
        "nextflow_returncode": completed.returncode,
        "nextflow_stdout_tail": completed.stdout[-2000:],
        "nextflow_stderr_tail": completed.stderr[-2000:],
        "provenance": persisted,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--provenance-db", type=Path, required=True)
    parser.add_argument("--reference-build", required=True)
    parser.add_argument("--reference-version", required=True)
    parser.add_argument("--reference-manifest-sha256", required=True)
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--input-bundle-dir", type=Path)
    parser.add_argument("--execution-target", default="local")
    parser.add_argument("--compute-pool", default="local-dev")
    parser.add_argument("--aligned-format", choices=("bam", "cram"), default="bam")
    parser.add_argument("--variant-format", choices=("vcf", "gvcf"), default="vcf")
    parser.add_argument("--force-fail-stage",
                         choices=("quality_control", "alignment", "variant_calling"))
    parser.add_argument("--input-uri-base")
    parser.add_argument("--output-uri-base")
    parser.add_argument("--log-uri")
    arguments = parser.parse_args(argv)
    try:
        report = run(
            run_id=arguments.run_id, work_dir=arguments.work_dir,
            provenance_db=arguments.provenance_db, reference_build=arguments.reference_build,
            reference_version=arguments.reference_version,
            reference_manifest_sha256=arguments.reference_manifest_sha256,
            profile=arguments.profile, input_bundle_dir=arguments.input_bundle_dir,
            execution_target=arguments.execution_target, compute_pool=arguments.compute_pool,
            aligned_format=arguments.aligned_format, variant_format=arguments.variant_format,
            force_fail_stage=arguments.force_fail_stage,
            input_uri_base=arguments.input_uri_base,
            output_uri_base=arguments.output_uri_base,
            log_uri=arguments.log_uri,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Nextflow secondary pipeline run could not complete: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["terminal_state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())