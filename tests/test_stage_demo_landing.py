import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.demo_dataset_manifest import build_manifest
from scripts.stage_demo_landing import (
    DEFAULT_RUN_ID,
    expected_layout,
    stage_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "demo" / "dataset-manifest.json"
STAGER = ROOT / "scripts" / "stage_demo_landing.py"


class DemoLandingStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "landing"
        self.inventory = self.directory / "inventory.sqlite3"

    def test_expected_layout_uses_manifest_identities_and_instrument_convention(self):
        layout = expected_layout(build_manifest())

        self.assertEqual(len(layout), 34)
        self.assertEqual(
            layout[0]["relative_path"],
            "SYN-RUN-001/Data/Intensities/BaseCalls/"
            "SYN-PG-SAMPLE-0001_S1_L001_R1_001.fastq.gz",
        )
        self.assertEqual(
            layout[-1]["relative_path"],
            "SYN-RUN-001/Data/Intensities/BaseCalls/"
            "SYN-PG-SAMPLE-0017_S17_L001_R2_001.fastq.gz",
        )
        self.assertEqual({entry["sample_id"] for entry in layout},
                         {identity["sample_id"] for identity in build_manifest()["identities"]})

    def test_stage_generates_placeholders_and_verifies_exact_paths_without_rewriting(self):
        report = stage_manifest(MANIFEST, self.root, self.inventory)

        self.assertTrue(report["verified"])
        self.assertTrue(report["paths_preserved"])
        self.assertEqual(report["file_count"], 34)
        self.assertEqual(report["first_scan_file_count"], 34)
        self.assertTrue(all(record["state"] == "complete" for record in report["files"]))
        self.assertEqual(
            [record["path"] for record in report["files"]],
            sorted(entry["relative_path"] for entry in expected_layout(build_manifest())),
        )
        for record in report["files"]:
            self.assertEqual(
                (self.root / Path(*record["path"].split("/"))).read_bytes(),
                b"synthetic metadata-only landing placeholder\n",
            )

    def test_stage_is_idempotent_and_rejects_modified_generated_files(self):
        first = stage_manifest(MANIFEST, self.root, self.inventory)
        second = stage_manifest(MANIFEST, self.root, self.inventory)
        self.assertEqual(
            [(record["path"], record["size_bytes"], record["state"])
             for record in first["files"]],
            [(record["path"], record["size_bytes"], record["state"])
             for record in second["files"]],
        )

        changed = self.root / Path(*first["files"][0]["path"].split("/"))
        changed.write_bytes(b"not the generated placeholder")
        with self.assertRaisesRegex(ValueError, "not the generated placeholder"):
            stage_manifest(MANIFEST, self.root, self.inventory)

    def test_cli_emits_verified_report(self):
        result = subprocess.run(
            [sys.executable, "-I", str(STAGER), "--manifest", str(MANIFEST),
             "--root", str(self.root), "--inventory", str(self.inventory)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["manifest_id"], "SYN-PG-MANIFEST-001")
        self.assertEqual(report["run_id"], DEFAULT_RUN_ID)
        self.assertTrue(report["verified"])


if __name__ == "__main__":
    unittest.main()
