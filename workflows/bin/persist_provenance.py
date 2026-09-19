#!/usr/bin/env python3
"""Nextflow bin: persist run provenance once the workflow reaches a terminal
state. Invoked from `workflow.onComplete` in main.nf for both a successful
and a deliberately failed run. The failing stage and output URIs are decided
in Groovy (from Nextflow's own success flag and error report) and passed in
explicitly here; this script only validates and persists the record.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pipeline_provenance import record_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--workflow-version", required=True)
    parser.add_argument("--reference-build", required=True)
    parser.add_argument("--reference-version", required=True)
    parser.add_argument("--execution-target", required=True)
    parser.add_argument("--compute-pool", required=True)
    parser.add_argument("--input-uris", required=True, help="JSON array of input URIs")
    parser.add_argument("--output-uris", required=True, help="JSON array of output URIs")
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--end-time", required=True)
    parser.add_argument("--log-location", required=True)
    parser.add_argument("--terminal-state", required=True, choices=("succeeded", "failed"))
    parser.add_argument("--failing-stage", default="")
    parser.add_argument("--provenance-db", required=True, type=Path)
    arguments = parser.parse_args()

    record = {
        "run_id": arguments.run_id,
        "workflow_id": arguments.workflow_id,
        "workflow_version": arguments.workflow_version,
        "reference_build": arguments.reference_build,
        "reference_version": arguments.reference_version,
        "execution_target": arguments.execution_target,
        "compute_pool": arguments.compute_pool,
        "input_uris": json.loads(arguments.input_uris),
        "output_uris": json.loads(arguments.output_uris),
        "start_time": arguments.start_time,
        "end_time": arguments.end_time,
        "terminal_state": arguments.terminal_state,
        "log_location": arguments.log_location,
        "failing_stage": arguments.failing_stage or None,
    }

    connection = sqlite3.connect(arguments.provenance_db)
    connection.row_factory = sqlite3.Row
    try:
        persisted = record_run(connection, record)
    finally:
        connection.close()
    print(json.dumps(persisted, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())