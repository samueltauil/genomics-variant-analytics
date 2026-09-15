import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = ROOT / "scripts" / "Invoke-Infrastructure.ps1"


class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.fail("PowerShell 7.2+ (pwsh) is required for infrastructure tests.")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.inventory = json.loads((ROOT / "infra" / "asset-inventory.json").read_text())

    def run_inventory(self, inventory=None):
        path = self.directory / "inventory.json"
        path.write_text(json.dumps(self.inventory if inventory is None else inventory))
        return self.run_entry("-InventoryPath", str(path))

    def run_entry(self, *arguments):
        return subprocess.run(
            [self.pwsh, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-File", str(ENTRY_POINT), *arguments],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
            env=dict(os.environ, NO_COLOR="1", TERM="dumb"),
        )

    def assert_rejected(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_default_validation_works_outside_repository(self):
        result = self.run_entry()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local-only", result.stdout)
        self.assertIn("not-evaluated", result.stdout)
        self.assertRegex(result.stdout, r"TemplatesBuilt\s*:\s*False")
        self.assertRegex(result.stdout, r"DeploymentSupported\s*:\s*False")

    def test_dependency_order_does_not_depend_on_input_order(self):
        self.inventory["assets"].reverse()
        result = self.run_inventory()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cloud_actions_are_rejected_before_inventory_is_read(self):
        missing = str(self.directory / "does-not-exist.json")
        for action in ("Deploy", "Apply", "Teardown", "Preflight", "WhatIf", "Login"):
            with self.subTest(action=action):
                result = self.run_entry("-Action", action, "-InventoryPath", missing)
                self.assert_rejected(result, "ValidateSet")
                self.assertNotIn("Get-Content", result.stderr)

    def test_unknown_flags_cannot_enable_cloud_access(self):
        result = self.run_entry("-AllowAzure")
        self.assert_rejected(result, "AllowAzure")

    def test_schema_rejects_policy_changes_and_extra_properties(self):
        for field, value in (("mode", "deploy"), ("status", "approved"),
                             ("subscriptionId", "synthetic"), ("assets", [])):
            with self.subTest(field=field):
                inventory = dict(self.inventory, **{field: value})
                self.assert_rejected(self.run_inventory(inventory), "Test-Json")

    def test_duplicate_asset_is_rejected(self):
        self.inventory["assets"].append(self.inventory["assets"][0])
        self.assert_rejected(self.run_inventory(), "Duplicate asset id")

    def test_unknown_task_is_rejected(self):
        self.inventory["assets"][0]["tasks"] = ["999.1"]
        self.assert_rejected(self.run_inventory(), "Unknown OpenSpec task")

    def test_unknown_dependency_is_rejected(self):
        self.inventory["assets"][0]["dependsOn"] = ["missing-asset"]
        self.assert_rejected(self.run_inventory(), "Unknown dependency")

    def test_dependency_cycle_is_rejected(self):
        self.inventory["assets"][0]["dependsOn"] = ["delivery"]
        self.assert_rejected(self.run_inventory(), "Dependency cycle")

    def test_missing_and_malformed_inventory_are_rejected(self):
        path = self.directory / "invalid.json"
        self.assertNotEqual(self.run_entry("-InventoryPath", str(path)).returncode, 0)
        path.write_text("{ invalid json")
        self.assert_rejected(self.run_entry("-InventoryPath", str(path)), "Test-Json")


class LandingWriteTests(unittest.TestCase):
    def setUp(self):
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.fail("PowerShell 7.2+ (pwsh) is required for infrastructure tests.")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = ROOT / "scripts" / "Test-LandingWrite.ps1"

    def run_write(self, *arguments):
        return subprocess.run(
            [self.pwsh, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-File", str(self.script), *arguments],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
            env=dict(os.environ, NO_COLOR="1", TERM="dumb"),
        )

    def test_odd_sized_write_verifies_integrity_and_cleans_up(self):
        sentinel = self.directory / "keep.txt"
        sentinel.write_text("synthetic sibling")
        result = self.run_write("-Directory", str(self.directory), "-ByteCount", "1048593")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["Mode"], "local-smoke")
        self.assertEqual(report["ByteCount"], 1048593)
        self.assertGreater(report["DurationSeconds"], 0)
        self.assertAlmostEqual(
            report["ThroughputMiBPerSecond"],
            (1048593 / 1048576) / report["DurationSeconds"],
        )
        self.assertRegex(report["ExpectedSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(report["ExpectedSha256"], report["ActualSha256"])
        self.assertTrue(report["IntegrityVerified"])
        self.assertTrue(report["ScratchFileRemoved"])
        self.assertFalse(report["SmbAcceptancePassed"])
        self.assertFalse(report["IopsCeilingVerified"])
        self.assertEqual(report["AzureReadiness"], "not-evaluated")
        self.assertEqual(set(self.directory.iterdir()), {sentinel})
        self.assertEqual(sentinel.read_text(), "synthetic sibling")

    def test_repeated_minimal_writes_leave_no_artifacts(self):
        for _iteration in range(2):
            result = self.run_write("-Directory", str(self.directory), "-ByteCount", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["ByteCount"], 1)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_write_sizes_are_rejected(self):
        for size in ("0", "-1", "1073741825"):
            with self.subTest(size=size):
                result = self.run_write("-Directory", str(self.directory), "-ByteCount", size)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Cannot validate argument on parameter 'ByteCount'", result.stderr)
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_remote_device_and_relative_paths_are_rejected(self):
        for path in (r"\\synthetic.invalid\share", "//synthetic.invalid/share",
                     r"\\?\C:\synthetic", "relative-folder"):
            with self.subTest(path=path):
                result = self.run_write("-Directory", path, "-ByteCount", "1")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("absolute local filesystem", result.stderr)
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_directory_and_file_target_are_rejected(self):
        file_path = self.directory / "keep.txt"
        file_path.write_text("synthetic sibling")
        for path in (self.directory / "missing", file_path):
            with self.subTest(path=path):
                result = self.run_write("-Directory", str(path), "-ByteCount", "1")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(set(self.directory.iterdir()), {file_path})
                self.assertEqual(file_path.read_text(), "synthetic sibling")

    def test_redirected_ancestor_is_rejected(self):
        target = self.directory / "target"
        target.mkdir()
        child = target / "child"
        child.mkdir()
        link = self.directory / "redirect"
        if os.name == "nt":
            result = subprocess.run(
                [self.pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 "New-Item -ItemType Junction -Path $env:TEST_LINK "
                 "-Target $env:TEST_TARGET -ErrorAction Stop | Out-Null"],
                capture_output=True, text=True, timeout=30,
                env=dict(os.environ, TEST_LINK=str(link), TEST_TARGET=str(target)),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(link.rmdir)
        else:
            link.symlink_to(target, target_is_directory=True)
            self.addCleanup(link.unlink)
        result = self.run_write("-Directory", str(link / "child"), "-ByteCount", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Reparse points", result.stderr)
        self.assertEqual(list(child.iterdir()), [])

    def test_dot_segments_are_rejected_before_normalization(self):
        path = str(self.directory) + os.sep + "missing" + os.sep + ".."
        result = self.run_write("-Directory", path, "-ByteCount", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Dot path segments", result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_network_override_is_not_available(self):
        result = self.run_write("-Directory", str(self.directory), "-AllowNetwork")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AllowNetwork", result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()