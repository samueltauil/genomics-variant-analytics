"""Rehearse the three local failure demonstrations named in the demo runbook.

Each demonstration drives a real local store used elsewhere in the
accelerator (the landing inventory, the variant store, or the governance
audit trail) through the exact trigger described in
docs/demo-runbook.md ("Phase 4 -- Rehearsed failures") and compares what
happened against the response its capability spec requires:

* Ingestion: openspec/changes/add-genomics-variant-accelerator/specs/
  ingestion/smb-landing-zone/spec.md ("Transfer failure detection and retry")
* Variant store: openspec/changes/add-genomics-variant-accelerator/specs/
  variant-store/delta-variant-store/spec.md ("Mandatory field validation" and
  "Rejected record handling")
* Governance: openspec/changes/add-genomics-variant-accelerator/specs/
  governance/access-and-lineage/spec.md ("Role-based authorization" and
  "Audit and lineage")

Every store lives directly under ``--state-root`` using the same file names
``scripts/reset_demo.py`` resets (``landing_inventory.sqlite3``,
``variant_store.sqlite3``, ``metadata_store.sqlite3``, and
``run_history.sqlite3``), plus one explicitly named synthetic landing
directory (``rehearsal-landing``) that ``reset_demo.py`` also removes. No
infrastructure, credential, or genomic payload is touched; every identifier
is synthetic.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.governance import AuthorizationError, GovernancePolicy
from scripts.scan_landing import available_for_staging, scan_once
from scripts.variant_store import VariantStore

RUN_ID = "SYN-RUN-DEMO-001"
SAMPLE_ID = "SYN-SAMPLE-DEMO-001"
SAMPLE_RELATIVE = f"{RUN_ID}/Data/Intensities/BaseCalls/{SAMPLE_ID}_S1_L001_R1_001.fastq.gz"
MANIFEST_TEMPLATE = "{run_id}/transfer-manifest.json"
FAILURE_MARKER_TEMPLATE = "{run_id}/transfer-failed.json"
DECLARED_SIZE_BYTES = 200
FAILURE_REASON = "sender-aborted"


def _record_for(report, relative):
    return next(entry for entry in report["files"] if entry["path"] == relative)


def rehearse_failed_transfer(state_root: Path) -> dict:
    """Trigger an interrupted transfer, then retry it, against a real landing inventory."""
    landing_root = state_root / "rehearsal-landing"
    sample_path = landing_root / SAMPLE_RELATIVE
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_bytes(b"s" * (DECLARED_SIZE_BYTES // 4))

    manifest_path = landing_root / MANIFEST_TEMPLATE.format(run_id=RUN_ID)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "run_id": RUN_ID,
        "files": [{"path": SAMPLE_RELATIVE, "size_bytes": DECLARED_SIZE_BYTES}],
    }))

    inventory_db = state_root / "landing_inventory.sqlite3"

    def scan():
        return scan_once(
            landing_root, inventory_db,
            transfer_manifest=MANIFEST_TEMPLATE, stall_seconds=1e-6,
            failure_marker=FAILURE_MARKER_TEMPLATE,
        )

    arriving_report = scan()
    arriving_state = _record_for(arriving_report, SAMPLE_RELATIVE)["state"]

    marker_path = landing_root / FAILURE_MARKER_TEMPLATE.format(run_id=RUN_ID)
    stat = sample_path.stat()
    marker_path.write_text(json.dumps({
        "run_id": RUN_ID,
        "status": "failed",
        "files": [{
            "path": SAMPLE_RELATIVE,
            "reason": FAILURE_REASON,
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
        }],
    }))

    failed_report = scan()
    failed_record = _record_for(failed_report, SAMPLE_RELATIVE)
    withheld_from_staging = SAMPLE_RELATIVE not in available_for_staging(failed_report)

    sample_path.write_bytes(b"s" * DECLARED_SIZE_BYTES)
    retry_arriving_record = _record_for(scan(), SAMPLE_RELATIVE)
    retry_complete_report = scan()
    retry_complete_record = _record_for(retry_complete_report, SAMPLE_RELATIVE)
    retry_available = SAMPLE_RELATIVE in available_for_staging(retry_complete_report)

    expected = {
        "before_failure_state": "arriving",
        "failed_state": "failed",
        "failure_reason": FAILURE_REASON,
        "withheld_from_staging_while_failed": True,
        "retry_returns_to_arriving": True,
        "retry_completes": True,
        "retry_available_for_staging": True,
    }
    actual = {
        "before_failure_state": arriving_state,
        "failed_state": failed_record["state"],
        "failure_reason": failed_record["failure_reason"],
        "withheld_from_staging_while_failed": withheld_from_staging,
        "retry_returns_to_arriving": retry_arriving_record["state"] == "arriving"
        and retry_arriving_record["failure_reason"] is None,
        "retry_completes": retry_complete_record["state"] == "complete",
        "retry_available_for_staging": retry_available,
    }
    return {
        "demonstration": "failed_transfer",
        "trigger": (
            f"Write {SAMPLE_RELATIVE} shorter than its transfer-manifest declared size, "
            "post an authoritative failure marker for it, scan twice, then re-send it at "
            "the declared size and scan twice more."
        ),
        "expected_response": expected,
        "actual_response": actual,
        "passed": expected == actual,
    }


def rehearse_rejected_variant(state_root: Path) -> dict:
    """Ingest a synthetic VCF row missing ALT and verify the exact rejection contract."""
    database = state_root / "variant_store.sqlite3"
    store = VariantStore(database)
    try:
        vcf = "\n".join([
            "##fileformat=VCFv4.3",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + SAMPLE_ID,
            "1\t101\tSYN-VAR-DEMO-001\tA\tG\t99\tPASS\t.\tGT\t0/1",
            "1\t102\tSYN-VAR-DEMO-002\tA\t\t99\tPASS\t.\tGT\t0/1",
            "",
        ])
        provenance = {
            "run_id": RUN_ID,
            "sample_id": SAMPLE_ID,
            "research_subject_id": "SYN-SUBJECT-DEMO-001",
            "cohort_id": "SYN-COHORT-DEMO-001",
            "pipeline_version": "release-1.0.0",
            "reference_build": "GRCh38",
            "reference_version_or_digest": "manifest-sha256:synthetic-reference-demo-001",
            "classification": "genomic-variant",
            "source_file_uri": "abfss://synthetic/vcf/demo-run.vcf",
            "ingestion_timestamp": "2026-09-19T00:00:00-04:00",
        }
        result = store.ingest_vcf_text(vcf, provenance)
        rejected = store.rejected_records(RUN_ID)
        accepted_rows = store.records()

        expected = {
            "accepted_count": 1,
            "rejected_count": 1,
            "rejected_reason_contains_alt": True,
            "rejected_row_has_source_uri_and_line": True,
            "bad_row_not_written": True,
        }
        actual = {
            "accepted_count": result["accepted_count"],
            "rejected_count": result["rejected_count"],
            "rejected_reason_contains_alt": (
                len(rejected) == 1 and "Missing mandatory field: ALT" in rejected[0]["reason"]
            ),
            "rejected_row_has_source_uri_and_line": (
                len(rejected) == 1
                and rejected[0]["source_file_uri"] == provenance["source_file_uri"]
                and rejected[0]["source_line_number"] == 4
            ),
            "bad_row_not_written": (
                len(accepted_rows) == 1 and accepted_rows[0]["ID"] == "SYN-VAR-DEMO-001"
            ),
        }
        return {
            "demonstration": "rejected_variant",
            "trigger": (
                "Ingest a synthetic two-row VCF where the second row is missing ALT."
            ),
            "expected_response": expected,
            "actual_response": actual,
            "passed": expected == actual,
        }
    finally:
        store.close()


def rehearse_denied_access(state_root: Path) -> dict:
    """Request a raw-file read without the required grant and verify the denial contract."""
    database = state_root / "metadata_store.sqlite3"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        policy = GovernancePolicy(connection)
        principal_id = "SYN-DEMO-UNGRANTED-ANALYST"
        artifact_uri = "abfss://synthetic/raw/SYN-FASTQ-DEMO-001.fastq.gz"

        before_denials = len([
            entry for entry in policy.audit.entries()
            if entry["operation"] == "deny:read_raw_file"
            and entry["principal_id"] == principal_id
        ])
        raised = None
        try:
            policy.authorize_raw_file(principal_id, artifact_uri)
        except AuthorizationError as error:
            raised = str(error)
        after_denials = [
            entry for entry in policy.audit.entries()
            if entry["operation"] == "deny:read_raw_file"
            and entry["principal_id"] == principal_id
        ]

        expected = {
            "raised_authorization_error": True,
            "denial_audit_entry_recorded": True,
            "denial_audit_entry_has_affected_data": True,
        }
        actual = {
            "raised_authorization_error": raised is not None,
            "denial_audit_entry_recorded": len(after_denials) == before_denials + 1,
            "denial_audit_entry_has_affected_data": (
                len(after_denials) == before_denials + 1
                and after_denials[-1]["affected_data"].get("artifact_uri") == artifact_uri
                and after_denials[-1]["affected_data"].get("access_tier") == "raw_genomic_files"
            ),
        }
        return {
            "demonstration": "denied_access",
            "trigger": (
                f"Call GovernancePolicy.authorize_raw_file for {principal_id!r} against "
                f"{artifact_uri!r} without granting the raw_genomic_files tier."
            ),
            "expected_response": expected,
            "actual_response": actual,
            "passed": expected == actual,
        }
    finally:
        connection.close()


def _ensure_run_history(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS demonstration_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            demonstration TEXT NOT NULL,
            trigger_summary TEXT NOT NULL,
            expected_response TEXT NOT NULL,
            actual_response TEXT NOT NULL,
            passed INTEGER NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    return connection


def _record_run_history(connection: sqlite3.Connection, outcome: dict) -> None:
    with connection:
        connection.execute(
            """INSERT INTO demonstration_runs
               (demonstration, trigger_summary, expected_response, actual_response,
                passed, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                outcome["demonstration"],
                outcome["trigger"],
                json.dumps(outcome["expected_response"], sort_keys=True),
                json.dumps(outcome["actual_response"], sort_keys=True),
                int(outcome["passed"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def rehearse_all(state_root: Path) -> dict:
    """Run all three rehearsed failure demonstrations and record each outcome in run history."""
    state_root.mkdir(parents=True, exist_ok=True)
    outcomes = [
        rehearse_failed_transfer(state_root),
        rehearse_rejected_variant(state_root),
        rehearse_denied_access(state_root),
    ]
    history = _ensure_run_history(state_root / "run_history.sqlite3")
    try:
        for outcome in outcomes:
            _record_run_history(history, outcome)
    finally:
        history.close()
    return {
        "state_root": str(state_root),
        "infrastructure_touched": False,
        "demonstrations": outcomes,
        "all_passed": all(outcome["passed"] for outcome in outcomes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    arguments = parser.parse_args()
    report = rehearse_all(arguments.state_root.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
