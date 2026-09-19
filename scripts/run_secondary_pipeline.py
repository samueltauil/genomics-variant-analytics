"""Command-line entry point that runs the secondary-analysis pipeline once and
persists run provenance for both success and failure, per the local/
containerized scope of the secondary-analysis spec.

Never invokes real Azure Batch or Slurm. `execution_target`/`compute_pool`
describe the *configured* local execution context; Batch/Slurm remain
configuration preparation validated separately (see workflows/conf).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.pipeline_provenance import record_run
    from scripts.secondary_pipeline import generate_demo_sample, run_pipeline
except ModuleNotFoundError:
    from pipeline_provenance import record_run
    from secondary_pipeline import generate_demo_sample, run_pipeline


WORKFLOW_ID = "genomics-secondary-analysis"
WORKFLOW_VERSION = "v0.1.0"


def execute(*, run_id: str, work_dir: Path, publish_dir: Path, provenance_db: Path,
            execution_target: str = "local", compute_pool: str = "local-dev",
            aligned_format: str = "bam", variant_format: str = "vcf",
            force_fail_stage: str | None = None, sample_seed_dir: Path | None = None) -> dict:
    sample_seed_dir = Path(sample_seed_dir) if sample_seed_dir else Path(work_dir) / "sample"
    sample = generate_demo_sample(sample_seed_dir)

    result = run_pipeline(
        run_id=run_id, sample=sample, work_dir=Path(work_dir), publish_dir=Path(publish_dir),
        aligned_format=aligned_format, variant_format=variant_format,
        force_fail_stage=force_fail_stage,
    )

    record = {
        "run_id": result.run_id,
        "workflow_id": WORKFLOW_ID,
        "workflow_version": WORKFLOW_VERSION,
        "reference_build": sample["reference_build"],
        "reference_version": sample["reference_version"],
        "execution_target": execution_target,
        "compute_pool": compute_pool,
        "input_uris": result.input_uris,
        "output_uris": result.output_uris,
        "start_time": result.start_time,
        "end_time": result.end_time,
        "terminal_state": result.terminal_state,
        "log_location": result.log_location,
        "failing_stage": result.failing_stage,
    }

    connection = sqlite3.connect(provenance_db)
    connection.row_factory = sqlite3.Row
    try:
        persisted = record_run(connection, record)
    finally:
        connection.close()

    return {
        "run_id": result.run_id,
        "terminal_state": result.terminal_state,
        "failing_stage": result.failing_stage,
        "provenance": persisted,
        "reference_build": sample["reference_build"],
        "reference_version": sample["reference_version"],
        "truth_variants": sample["truth_variants"],
        "variant_calls": result.stage_reports.get("variant_calling", {}).get("calls"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    parser.add_argument("--provenance-db", type=Path, required=True)
    parser.add_argument("--execution-target", default="local")
    parser.add_argument("--compute-pool", default="local-dev")
    parser.add_argument("--aligned-format", choices=("bam", "cram"), default="bam")
    parser.add_argument("--variant-format", choices=("vcf", "gvcf"), default="vcf")
    parser.add_argument("--force-fail-stage",
                         choices=("quality_control", "alignment", "variant_calling"))
    arguments = parser.parse_args(argv)
    try:
        report = execute(
            run_id=arguments.run_id, work_dir=arguments.work_dir,
            publish_dir=arguments.publish_dir, provenance_db=arguments.provenance_db,
            execution_target=arguments.execution_target, compute_pool=arguments.compute_pool,
            aligned_format=arguments.aligned_format, variant_format=arguments.variant_format,
            force_fail_stage=arguments.force_fail_stage,
        )
    except (OSError, ValueError) as error:
        print(f"Secondary pipeline run could not complete: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["terminal_state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())