"""Run provenance for the secondary-analysis pipeline.

Persists the fields required by the secondary-analysis provenance requirement
for both a successful run and a deliberately failed run: workflow id and
version, reference build and version, execution target and compute pool,
input artifact URIs, output artifact URIs, start and end timestamps, the
terminal state, and the log location. A failed run also records the failing
stage so a stage-level failure can be identified without inventing a
successful-run-only field.

This module is a local SQLite-backed model of the provenance store described
in the secondary-analysis spec. It is evidence for local/containerized
behavior only; an Azure-hosted provenance store still requires deployment
validation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1

TERMINAL_STATES = ("succeeded", "failed")

# The provenance content fields named by the secondary-analysis spec's run
# provenance requirement (workflow id and version, reference build and
# version, execution target and pool, input URIs, output URIs, start and end
# time, terminal state, log location). `run_id` is the record's key, not one
# of these content fields.
PROVENANCE_FIELDS = (
    "workflow_id",
    "workflow_version",
    "reference_build",
    "reference_version",
    "execution_target",
    "compute_pool",
    "input_uris",
    "output_uris",
    "start_time",
    "end_time",
    "terminal_state",
    "log_location",
)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty string without surrounding whitespace.")
    return value


def _uri_list(value: Any, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, (list, tuple)) or (not allow_empty and not value):
        kind = "a nonempty list" if not allow_empty else "a list"
        raise ValueError(f"{field} must be {kind} of URI strings.")
    return [_text(item, f"{field} entry") for item in value]


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_run_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one provenance record, failing closed on any missing field.

    `terminal_state` must be "succeeded" or "failed". `failing_stage` must be
    null on success and a nonempty stage name on failure; outputs may be an
    empty list on failure because a failed run must not publish outputs as
    complete.
    """
    required = {"run_id", "failing_stage", *PROVENANCE_FIELDS}
    if not isinstance(record, Mapping) or set(record) != required:
        missing = sorted(required - set(record))
        extra = sorted(set(record) - required) if isinstance(record, Mapping) else []
        raise ValueError(
            "Provenance record must supply exactly the required fields; "
            f"missing={missing} extra={extra}."
        )

    run_id = _text(record["run_id"], "run_id")
    workflow_id = _text(record["workflow_id"], "workflow_id")
    workflow_version = _text(record["workflow_version"], "workflow_version")
    reference_build = _text(record["reference_build"], "reference_build")
    reference_version = _text(record["reference_version"], "reference_version")
    execution_target = _text(record["execution_target"], "execution_target")
    compute_pool = _text(record["compute_pool"], "compute_pool")
    log_location = _text(record["log_location"], "log_location")

    terminal_state = record["terminal_state"]
    if terminal_state not in TERMINAL_STATES:
        raise ValueError(f"terminal_state must be one of {TERMINAL_STATES}.")

    input_uris = _uri_list(record["input_uris"], "input_uris", allow_empty=False)
    output_uris = _uri_list(
        record["output_uris"], "output_uris", allow_empty=(terminal_state == "failed")
    )
    if terminal_state == "succeeded" and not output_uris:
        raise ValueError("A succeeded run must record at least one output URI.")

    start_time = _timestamp(record["start_time"], "start_time")
    end_time = _timestamp(record["end_time"], "end_time")
    if end_time < start_time:
        raise ValueError("end_time must not precede start_time.")

    failing_stage = record["failing_stage"]
    if terminal_state == "failed":
        failing_stage = _text(failing_stage, "failing_stage")
        if output_uris:
            raise ValueError("A failed run must not record published output URIs.")
    elif failing_stage is not None:
        raise ValueError("failing_stage must be null for a succeeded run.")

    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "reference_build": reference_build,
        "reference_version": reference_version,
        "execution_target": execution_target,
        "compute_pool": compute_pool,
        "input_uris": input_uris,
        "output_uris": output_uris,
        "start_time": start_time,
        "end_time": end_time,
        "terminal_state": terminal_state,
        "log_location": log_location,
        "failing_stage": failing_stage,
    }


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            workflow_version TEXT NOT NULL,
            reference_build TEXT NOT NULL,
            reference_version TEXT NOT NULL,
            execution_target TEXT NOT NULL,
            compute_pool TEXT NOT NULL,
            input_uris TEXT NOT NULL,
            output_uris TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            terminal_state TEXT NOT NULL,
            log_location TEXT NOT NULL,
            failing_stage TEXT
        )
        """
    )
    connection.commit()


def record_run(connection: sqlite3.Connection, record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and persist one run's provenance. Runs are append-only; a
    repeated run_id is rejected rather than silently overwritten."""
    validated = validate_run_record(record)
    ensure_schema(connection)
    existing = connection.execute(
        "SELECT 1 FROM pipeline_runs WHERE run_id = ?", (validated["run_id"],)
    ).fetchone()
    if existing is not None:
        raise ValueError(f"Provenance for run_id {validated['run_id']!r} already recorded.")
    connection.execute(
        """
        INSERT INTO pipeline_runs (
            run_id, workflow_id, workflow_version, reference_build, reference_version,
            execution_target, compute_pool, input_uris, output_uris, start_time, end_time,
            terminal_state, log_location, failing_stage
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            validated["run_id"],
            validated["workflow_id"],
            validated["workflow_version"],
            validated["reference_build"],
            validated["reference_version"],
            validated["execution_target"],
            validated["compute_pool"],
            json.dumps(validated["input_uris"]),
            json.dumps(validated["output_uris"]),
            validated["start_time"],
            validated["end_time"],
            validated["terminal_state"],
            validated["log_location"],
            validated["failing_stage"],
        ),
    )
    connection.commit()
    return validated


def get_run(connection: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    ensure_schema(connection)
    row = connection.execute(
        "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["input_uris"] = json.loads(record["input_uris"])
    record["output_uris"] = json.loads(record["output_uris"])
    return record


def present_fields(record: Mapping[str, Any]) -> Sequence[str]:
    """Return which of the spec-named provenance fields are present in the record.

    A field counts as present when its key exists with a non-null value.
    `output_uris` counts as present even when it is an empty list, because a
    failed run legitimately records zero published outputs.
    """
    present = []
    for field in PROVENANCE_FIELDS:
        if field not in record:
            continue
        value = record[field]
        if value is None:
            continue
        present.append(field)
    return present