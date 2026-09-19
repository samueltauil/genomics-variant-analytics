from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.scan_landing import (
    MANIFEST_MAX_BYTES, available_for_staging, poll_inventory, scan_once,
)


SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "scan_landing.py"


class LandingScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "landing"
        self.root.mkdir()
        self.inventory = self.directory / "inventory.sqlite3"
        self.relative = "SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R1_001.fastq.gz"
        self.file = self.root / self.relative
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"synthetic test bytes only")

    def scan(self):
        return scan_once(self.root, self.inventory)

    def test_seeded_run_has_required_metadata_without_reading_content(self):
        with patch.object(Path, "open", side_effect=AssertionError("No payload reads")):
            report = self.scan()
        record = report["files"][0]
        self.assertEqual(report["file_count"], 1)
        self.assertEqual(record["path"], self.relative)
        self.assertEqual(record["run_id"], "SYN-RUN-001")
        self.assertEqual(record["sample_id"], "SYN-SAMPLE-001")
        self.assertEqual(record["size_bytes"], self.file.stat().st_size)
        self.assertEqual(record["modified_ns"], self.file.stat().st_mtime_ns)
        self.assertIsNotNone(datetime.fromisoformat(record["arrival_timestamp"]).tzinfo)
        self.assertEqual(record["state"], "arriving")
        self.assertTrue(record["present"])
        self.assertIsNone(record["metadata_error"])
        self.assertTrue(report["completeness_evaluated"])

    def test_slow_copy_is_arriving_until_two_unchanged_observations(self):
        waits = 0

        def write_chunk(_interval):
            nonlocal waits
            waits += 1
            if waits < 3:
                with self.file.open("ab") as output:
                    output.write(b"synthetic chunk")

        with patch("scripts.scan_landing.time.sleep", side_effect=write_chunk):
            reports = list(poll_inventory(self.root, self.inventory, polls=4, interval_seconds=5))
        self.assertEqual([report["files"][0]["state"] for report in reports],
                         ["arriving", "arriving", "arriving", "complete"])
        self.assertEqual(len({report["files"][0]["arrival_timestamp"] for report in reports}), 1)

    def test_mtime_change_alone_revokes_completeness(self):
        self.scan()
        self.assertEqual(self.scan()["files"][0]["state"], "complete")
        metadata = self.file.stat()
        os.utime(self.file, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 10_000_000_000))
        self.assertEqual(self.scan()["files"][0]["state"], "arriving")
        self.assertEqual(self.scan()["files"][0]["state"], "complete")

    def test_missing_and_returning_file_requires_new_stability_pair(self):
        self.scan()
        self.assertEqual(self.scan()["files"][0]["state"], "complete")
        metadata = self.file.stat()
        content = self.file.read_bytes()
        self.file.unlink()
        self.assertEqual(self.scan()["files"][0]["state"], "arriving")
        self.file.write_bytes(content)
        os.utime(self.file, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        self.assertEqual(self.scan()["files"][0]["state"], "arriving")
        self.assertEqual(self.scan()["files"][0]["state"], "complete")

    def test_unmatched_file_never_becomes_complete(self):
        (self.root / "unknown.txt").write_text("synthetic")
        self.scan()
        record = next(entry for entry in self.scan()["files"] if entry["path"] == "unknown.txt")
        self.assertEqual(record["state"], "arriving")

    def test_fresh_vendor_marker_completes_only_its_run(self):
        marker = self.root / "SYN-RUN-001" / "RTAComplete.txt"
        marker.write_text("synthetic marker")
        modified = self.file.stat().st_mtime_ns
        os.utime(marker, ns=(modified, modified))
        other = self.root / "SYN-RUN-002" / self.file.name
        other.parent.mkdir()
        other.write_bytes(b"synthetic")
        report = scan_once(self.root, self.inventory, completion_marker="{run_id}/RTAComplete.txt")
        records = {record["path"]: record for record in report["files"]}
        self.assertEqual(records[self.relative]["state"], "complete")
        self.assertEqual(records[other.relative_to(self.root).as_posix()]["state"], "arriving")
        self.assertEqual(records["SYN-RUN-001/RTAComplete.txt"]["state"], "arriving")

    def test_stale_marker_does_not_complete_a_new_or_changed_file(self):
        marker = self.root / "SYN-RUN-001" / "RTAComplete.txt"
        marker.write_text("synthetic marker")
        modified = self.file.stat().st_mtime_ns
        os.utime(marker, ns=(modified - 10_000_000_000, modified - 10_000_000_000))
        report = scan_once(self.root, self.inventory, completion_marker="{run_id}/RTAComplete.txt")
        record = next(entry for entry in report["files"] if entry["path"] == self.relative)
        self.assertEqual(record["state"], "arriving")

    def test_invalid_marker_templates_are_rejected_before_inventory_creation(self):
        for template in ("../outside", "/outside", "C:/outside", r"run\marker", "{unknown}",
                         "{run_id.upper}", "{run_id!r}", "{run_id:>20}", "", "{path}"):
            with self.subTest(template=template):
                with self.assertRaises(ValueError):
                    scan_once(self.root, self.directory / "invalid.sqlite3", completion_marker=template)

    def test_marker_policy_is_bound_to_inventory(self):
        self.scan()
        with self.assertRaisesRegex(ValueError, "already bound"):
            scan_once(self.root, self.inventory, completion_marker="{run_id}/RTAComplete.txt")

    def test_cli_forwards_completion_marker(self):
        marker = self.root / "SYN-RUN-001" / "RTAComplete.txt"
        marker.write_text("synthetic")
        modified = self.file.stat().st_mtime_ns
        os.utime(marker, ns=(modified, modified))
        result = subprocess.run(
            [sys.executable, "-I", str(SCANNER), "--root", str(self.root),
             "--inventory", str(self.inventory), "--completion-marker", "{run_id}/RTAComplete.txt"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = next(entry for entry in json.loads(result.stdout)["files"] if entry["path"] == self.relative)
        self.assertEqual(record["state"], "complete")

    def test_repeated_poll_and_restart_preserve_arrival_and_update_size(self):
        first = self.scan()["files"][0]
        self.file.write_bytes(b"synthetic changed bytes with a different size")
        second = self.scan()["files"][0]
        self.assertEqual(second["arrival_timestamp"], first["arrival_timestamp"])
        self.assertEqual(second["size_bytes"], self.file.stat().st_size)
        self.assertEqual(second["state"], "arriving")
        self.assertEqual(len(self.scan()["files"]), 1)

    def test_poll_schedule_discovers_new_files_and_sleeps_only_between_polls(self):
        def arrival(_interval):
            (self.file.parent / "SYN-SAMPLE-002_S2_L001_R1_001.fastq").write_bytes(b"synthetic")

        with patch("scripts.scan_landing.time.sleep", side_effect=arrival) as wait:
            reports = list(poll_inventory(self.root, self.inventory, polls=2, interval_seconds=5))
        wait.assert_called_once_with(5)
        self.assertEqual([report["file_count"] for report in reports], [1, 2])
        self.assertEqual({entry["sample_id"] for entry in reports[-1]["files"]},
                         {"SYN-SAMPLE-001", "SYN-SAMPLE-002"})

    def test_unmatched_name_is_visible_without_fabricated_identifiers(self):
        (self.root / "RunInfo.xml").write_text("synthetic")
        record = next(entry for entry in self.scan()["files"] if entry["path"] == "RunInfo.xml")
        self.assertIsNone(record["run_id"])
        self.assertIsNone(record["sample_id"])
        self.assertEqual(record["metadata_error"], "unrecognized-path")

    def test_disappeared_file_retains_history_without_claiming_failure(self):
        first = self.scan()["files"][0]
        self.file.unlink()
        report = self.scan()
        self.assertEqual(report["file_count"], 0)
        self.assertFalse(report["files"][0]["present"])
        self.assertEqual(report["files"][0]["arrival_timestamp"], first["arrival_timestamp"])
        self.assertEqual(report["files"][0]["state"], "arriving")

    def test_custom_pattern_does_not_rewrite_source_paths(self):
        pattern = r"(?P<run_id>[^/]+)/Data/Intensities/BaseCalls/(?P<sample_id>.+)\.fastq\.gz"
        report = scan_once(self.root, self.inventory, pattern)
        self.assertEqual(report["files"][0]["path"], self.relative)
        self.assertEqual(report["files"][0]["sample_id"], "SYN-SAMPLE-001_S1_L001_R1_001")
        self.assertTrue(self.file.is_file())

    def test_inventory_root_and_pattern_binding_cannot_change(self):
        self.scan()
        other = self.directory / "other"
        other.mkdir()
        for root, pattern in ((other, r"(?P<run_id>.+)/(?P<sample_id>.+)"),
                              (self.root, r"(?P<run_id>.+)/(?P<sample_id>.+)")):
            with self.subTest(root=root):
                with self.assertRaisesRegex(ValueError, "already bound"):
                    scan_once(root, self.inventory, pattern)
        self.assertTrue(self.scan()["files"][0]["present"])

    def test_invalid_paths_and_patterns_do_not_create_inventory(self):
        for root in (r"\\synthetic.invalid\share", "//synthetic.invalid/share", "relative",
                     self.directory / "missing", self.file):
            with self.subTest(root=root):
                with self.assertRaises((ValueError, OSError)):
                    scan_once(root, self.inventory)
                self.assertFalse(self.inventory.exists())
        with self.assertRaisesRegex(ValueError, "outside"):
            scan_once(self.root, self.root / "inventory.sqlite3")
        with self.assertRaisesRegex(ValueError, "named"):
            scan_once(self.root, self.inventory, r".*")
        self.assertFalse(self.inventory.exists())

    def test_poll_validation_precedes_any_scan(self):
        for values in ({"polls": 0}, {"polls": -1}, {"interval_seconds": 0},
                       {"interval_seconds": float("nan")}, {"interval_seconds": float("inf")}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    list(poll_inventory(self.root, self.inventory, **values))
                self.assertFalse(self.inventory.exists())

    def test_failed_walk_leaves_previous_snapshot_unchanged(self):
        self.scan()
        with patch("scripts.scan_landing.os.walk", side_effect=PermissionError("synthetic failure")):
            with self.assertRaises(PermissionError):
                self.scan()
        with closing(sqlite3.connect(self.inventory)) as connection:
            self.assertEqual(connection.execute("SELECT present FROM files").fetchone(), (1,))

    def test_redirected_entries_are_rejected(self):
        link = self.root / "redirect"
        target = self.directory / "outside"
        target.mkdir()
        if os.name == "nt":
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                 "New-Item -ItemType Junction -Path $env:TEST_LINK -Target $env:TEST_TARGET "
                 "-ErrorAction Stop | Out-Null"],
                env=dict(os.environ, TEST_LINK=str(link), TEST_TARGET=str(target)),
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(link.rmdir)
        else:
            link.symlink_to(target, target_is_directory=True)
            self.addCleanup(link.unlink)
        with self.assertRaisesRegex(ValueError, "reparse"):
            self.scan()
        self.assertFalse(self.inventory.exists())

    def test_cli_runs_from_outside_repository_and_emits_json(self):
        result = subprocess.run(
            [sys.executable, "-I", str(SCANNER), "--root", str(self.root),
             "--inventory", str(self.inventory)],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["file_count"], 1)
        self.assertEqual(self.file.read_bytes(), b"synthetic test bytes only")


class TransferFailureTests(unittest.TestCase):
    """Task 2.3: failures require an authoritative, generation-bound signal."""

    MANIFEST = "{run_id}/transfer-manifest.json"
    FAILURE_MARKER = "{run_id}/transfer-failed.json"
    REACHED = 1e-6
    UNREACHED = 3600

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "landing"
        self.base = self.root / "SYN-RUN-001" / "Data" / "Intensities" / "BaseCalls"
        self.base.mkdir(parents=True)
        self.inventory = self.directory / "inventory.sqlite3"
        self.first = "SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R1_001.fastq.gz"
        self.second = "SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R2_001.fastq.gz"

    def write(self, relative, size):
        path = self.root / relative
        path.write_bytes(b"s" * size)
        return path

    def declare(self, sizes, run_id="SYN-RUN-001", relative=None):
        document = {"run_id": run_id, "files": [
            {"path": path, "size_bytes": size} for path, size in sizes.items()
        ]}
        path = self.root / (relative or self.MANIFEST.format(run_id=run_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document))
        return path

    def write_failure_marker(self, paths, run_id="SYN-RUN-001"):
        entries = []
        for path, reason in paths.items():
            candidate = self.root / path
            if candidate.exists():
                metadata = candidate.stat()
                size_bytes, modified_ns = metadata.st_size, metadata.st_mtime_ns
            else:
                size_bytes, modified_ns = None, None
            entries.append({
                "path": path, "reason": reason,
                "size_bytes": size_bytes, "modified_ns": modified_ns,
            })
        marker = self.root / self.FAILURE_MARKER.format(run_id=run_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({
            "run_id": run_id, "status": "failed", "files": entries,
        }))
        newest = max(
            [self.root.joinpath(*path.split("/")).stat().st_mtime_ns
             for path in paths if self.root.joinpath(*path.split("/")).exists()]
            or [marker.stat().st_mtime_ns]
        )
        os.utime(marker, ns=(newest + 1_000_000, newest + 1_000_000))
        return marker

    def scan(self, stall_seconds=REACHED):
        return scan_once(self.root, self.inventory, transfer_manifest=self.MANIFEST,
                         stall_seconds=stall_seconds, failure_marker=self.FAILURE_MARKER)

    def record(self, report, relative):
        return next(entry for entry in report["files"] if entry["path"] == relative)

    def test_interrupted_transfer_is_failed_and_withheld_from_staging(self):
        self.declare({self.first: 200})
        self.write(self.first, 50)
        self.assertEqual(self.record(self.scan(), self.first)["state"], "arriving")
        self.write_failure_marker({self.first: "sender-aborted"})
        report = self.scan()
        record = self.record(report, self.first)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["failure_reason"], "sender-aborted")
        self.assertEqual(record["declared_size_bytes"], 200)
        self.assertEqual(record["run_id"], "SYN-RUN-001")
        self.assertEqual(record["sample_id"], "SYN-SAMPLE-001")
        self.assertEqual(report["failed_count"], 1)
        self.assertNotIn(self.first, available_for_staging(report))

    def test_stable_short_file_never_completes_before_the_deadline(self):
        self.declare({self.first: 200})
        self.write(self.first, 50)
        states = [self.record(self.scan(self.UNREACHED), self.first)["state"] for _ in range(3)]
        self.assertEqual(states, ["arriving", "arriving", "arriving"])

    def test_resend_replaces_the_failed_entry_without_affecting_siblings(self):
        self.declare({self.first: 200, self.second: 120})
        self.write(self.first, 50)
        self.write(self.second, 120)
        first_report = self.scan()
        self.write_failure_marker({self.first: "sender-aborted"})
        failed = self.record(self.scan(), self.first)
        self.assertEqual((failed["state"], failed["failure_reason"]), ("failed", "sender-aborted"))
        self.assertEqual(self.record(self.scan(), self.second)["state"], "complete")

        self.write(self.first, 200)
        retried = self.record(self.scan(), self.first)
        self.assertEqual(retried["state"], "arriving")
        self.assertIsNone(retried["failure_reason"])
        self.assertEqual(retried["arrival_timestamp"],
                         self.record(first_report, self.first)["arrival_timestamp"])

        report = self.scan()
        self.assertEqual(self.record(report, self.first)["state"], "complete")
        self.assertEqual(self.record(report, self.second)["state"], "complete")
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(len([entry for entry in report["files"] if entry["path"] == self.first]), 1)
        self.assertCountEqual(available_for_staging(report), [self.first, self.second])

    def test_declared_file_that_never_arrives_is_failed_with_its_identifiers(self):
        self.declare({self.first: 200})
        self.write_failure_marker({self.first: "transfer-session-aborted"})
        record = self.record(self.scan(), self.first)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["failure_reason"], "transfer-session-aborted")
        self.assertEqual(record["run_id"], "SYN-RUN-001")
        self.assertEqual(record["sample_id"], "SYN-SAMPLE-001")
        self.assertFalse(record["present"])
        self.assertEqual(record["declared_size_bytes"], 200)

    def test_file_larger_than_declared_fails_on_first_observation(self):
        self.declare({self.first: 10})
        self.write(self.first, 40)
        record = self.record(self.scan(self.UNREACHED), self.first)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["failure_reason"], "size-exceeds-declared")

    def test_run_without_a_usable_manifest_is_held_arriving(self):
        self.write(self.first, 50)
        for payload in (None, "{not json", json.dumps({"run_id": "SYN-RUN-001"}),
                        json.dumps({"run_id": "SYN-RUN-002", "files": [
                            {"path": self.first, "size_bytes": 50}]}),
                        json.dumps({"run_id": "SYN-RUN-001", "files": [
                            {"path": "SYN-RUN-002/other.fastq", "size_bytes": 1}]}),
                        json.dumps({"run_id": "SYN-RUN-001", "files": [
                            {"path": self.first, "size_bytes": True}]}),
                        json.dumps({"run_id": "SYN-RUN-001", "files": [
                            {"path": "../escape", "size_bytes": 1}]}),
                        json.dumps({"run_id": "SYN-RUN-001", "files": [
                            {"path": "SYN-RUN-001/transfer-manifest.json", "size_bytes": 1}]}),
                        json.dumps({"run_id": "SYN-RUN-001", "files": [
                            {"path": self.first, "size_bytes": 1},
                            {"path": self.first, "size_bytes": 2}]})):
            with self.subTest(payload=payload):
                inventory = self.directory / ("case-%d.sqlite3" % abs(hash(payload)))
                manifest = self.root / "SYN-RUN-001" / "transfer-manifest.json"
                manifest.unlink(missing_ok=True)
                if payload is not None:
                    manifest.write_text(payload)
                report = scan_once(self.root, inventory, transfer_manifest=self.MANIFEST,
                                   stall_seconds=self.REACHED)
                report = scan_once(self.root, inventory, transfer_manifest=self.MANIFEST,
                                   stall_seconds=self.REACHED)
                record = self.record(report, self.first)
                self.assertEqual(record["state"], "arriving")
                self.assertEqual(record["metadata_error"], "manifest-unavailable")
                self.assertIn("SYN-RUN-001", report["manifest_errors"])
                self.assertEqual(available_for_staging(report), [])

    def test_oversized_manifest_is_rejected_without_being_read(self):
        self.write(self.first, 50)
        manifest = self.declare({self.first: 50})
        manifest.write_bytes(b" " * (MANIFEST_MAX_BYTES + 1))
        report = self.scan()
        self.assertIn("exceeds", report["manifest_errors"]["SYN-RUN-001"])

    def test_manifest_requires_a_run_template_but_not_a_failure_deadline(self):
        self.declare({self.first: 200})
        report = scan_once(self.root, self.inventory, transfer_manifest=self.MANIFEST)
        self.assertEqual(report["failure_detection"], "not-evaluated")
        for template in ("manifest.json", "{sample_id}/manifest.json", "{run_id}/{run_id}.json",
                         "{path}/manifest.json", "../{run_id}.json", "/{run_id}.json"):
            with self.subTest(template=template):
                with self.assertRaises(ValueError):
                    scan_once(self.root, self.inventory, transfer_manifest=template, stall_seconds=5)
        for stall in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(stall=stall):
                with self.assertRaisesRegex(ValueError, "Stall deadline"):
                    scan_once(self.root, self.inventory, transfer_manifest=self.MANIFEST,
                              stall_seconds=stall)
        self.assertTrue(self.inventory.exists())

    def test_failure_policy_is_bound_to_the_inventory(self):
        self.declare({self.first: 200})
        self.scan()
        with self.assertRaisesRegex(ValueError, "already bound"):
            scan_once(self.root, self.inventory)
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.scan(stall_seconds=99)

    def test_unmanifested_scan_reports_no_failure_detection(self):
        self.write(self.first, 50)
        report = scan_once(self.root, self.inventory)
        self.assertEqual(report["failure_detection"], "not-evaluated")
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["manifest_errors"], {})

    def test_cli_forwards_transfer_manifest_and_stall_deadline(self):
        self.declare({self.first: 200})
        self.write(self.first, 50)
        self.scan()
        self.write_failure_marker({self.first: "terminal-failure"})
        command = [sys.executable, "-I", str(SCANNER), "--root", str(self.root),
                   "--inventory", str(self.inventory), "--transfer-manifest", self.MANIFEST,
                   "--stall-seconds", "0.000001", "--failure-marker", self.FAILURE_MARKER]
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(self.record(report, self.first)["failure_reason"], "terminal-failure")

    def test_stable_short_file_is_not_failed_without_authoritative_signal(self):
        self.declare({self.first: 200})
        self.write(self.first, 50)
        states = [self.record(self.scan(), self.first)["state"] for _ in range(3)]
        self.assertEqual(states, ["arriving", "arriving", "arriving"])

    def test_failure_persists_after_restart_and_retry_is_generation_bound(self):
        self.declare({self.first: 200})
        self.write(self.first, 50)
        self.scan()
        self.write_failure_marker({self.first: "network-reset"})
        failed = self.record(self.scan(), self.first)
        restarted = self.record(
            scan_once(self.root, self.inventory, transfer_manifest=self.MANIFEST,
                      stall_seconds=self.REACHED, failure_marker=self.FAILURE_MARKER),
            self.first,
        )
        self.assertEqual(restarted["state"], "failed")
        self.assertEqual(restarted["failure_reason"], failed["failure_reason"])

        self.write(self.first, 200)
        retried = self.record(self.scan(), self.first)
        self.assertEqual(retried["state"], "arriving")
        self.assertIsNone(retried["failure_reason"])

    def test_invalid_failure_marker_holds_run_without_claiming_failure(self):
        self.declare({self.first: 50})
        self.write(self.first, 50)
        marker = self.root / "SYN-RUN-001" / "transfer-failed.json"
        marker.write_text("{not json")
        report = self.scan()
        record = self.record(report, self.first)
        self.assertEqual(record["state"], "arriving")
        self.assertEqual(record["metadata_error"], "failure-marker-unavailable")
        self.assertEqual(report["failed_count"], 0)
        self.assertIn("SYN-RUN-001", report["failure_marker_errors"])

    def test_stale_failure_marker_does_not_fail_retried_generation(self):
        self.declare({self.first: 60})
        self.write(self.first, 50)
        self.scan()
        self.write_failure_marker({self.first: "old-generation-failure"})
        self.write(self.first, 60)
        report = self.scan()
        record = self.record(report, self.first)
        self.assertEqual(record["state"], "arriving")
        self.assertIsNone(record["failure_reason"])


if __name__ == "__main__":
    unittest.main()