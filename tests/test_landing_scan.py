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

from scripts.scan_landing import poll_inventory, scan_once


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
        self.assertFalse(report["completeness_evaluated"])

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


if __name__ == "__main__":
    unittest.main()