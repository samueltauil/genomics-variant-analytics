import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "Test-DemoPreflight.ps1"
RESET = ROOT / "scripts" / "reset_demo.py"
IDENTIFIER_SCAN = ROOT / "scripts" / "check_environment_identifiers.py"


def run_pwsh(*arguments):
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
         str(PREFLIGHT), *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )


class DemoPreflightTests(unittest.TestCase):
    def _snapshot(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        json.dump(payload, handle)
        handle.close()
        return handle.name

    def test_unprepared_snapshot_reports_each_failed_prerequisite_with_found_and_required(self):
        snapshot = self._snapshot({
            "subscription": {"type": "Trial", "state": "Disabled"},
            "roles": ["Reader"],
            "quotas": {
                "compute_vcpus": {"current": 4, "limit": 4},
                "storage_gib": {"current": 120, "limit": 128},
            },
            "regionalAvailability": {"eastus2": ["Azure Files SMB"]},
            "tooling": {"azureCli": "2.40", "bicep": "0.10"},
        })
        result = run_pwsh("-SnapshotPath", snapshot, "-RequireAzureChecks")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        failed = {check["Name"]: check for check in report["Checks"]
                  if check["Status"] == "FAIL"}
        for name in ("subscription-type", "deployer-roles", "compute-quota",
                     "storage-quota", "regional-availability:ADLS Gen2",
                     "tool:azure-cli", "tool:bicep"):
            self.assertIn(name, failed)
            self.assertTrue(failed[name]["Found"])
            self.assertTrue(failed[name]["Required"])

    def test_prepared_snapshot_is_ready_without_contacting_azure(self):
        snapshot = self._snapshot({
            "subscription": {"type": "MicrosoftCustomerAgreement", "state": "Enabled"},
            "roles": ["Contributor", "User Access Administrator"],
            "quotas": {
                "compute_vcpus": {"current": 0, "limit": 16},
                "storage_gib": {"current": 0, "limit": 512},
            },
            "regionalAvailability": {
                "eastus2": [
                    "Azure Files SMB", "ADLS Gen2", "Data Factory Copy",
                    "managed identities", "private endpoints",
                    "Azure Batch or HPC", "Delta-capable analytics engine",
                ],
            },
            "tooling": {"azureCli": "2.60", "bicep": "0.30"},
        })
        result = run_pwsh("-SnapshotPath", snapshot, "-RequireAzureChecks")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["Ready"])
        self.assertEqual(report["Mode"], "snapshot-preflight")
        self.assertTrue(all(check["Status"] == "PASS" for check in report["Checks"]))

    def test_deploy_runs_preflight_before_azure_resource_lookup(self):
        deploy = (ROOT / "scripts" / "Deploy-Accelerator.ps1").read_text()
        self.assertLess(
            deploy.index("$preflightPath ="),
            deploy.index("$preflight = & pwsh"),
        )
        self.assertLess(
            deploy.index("$preflight = & pwsh"),
            deploy.index("$account = Invoke-Az"),
        )

    def test_deploy_rejects_unmet_snapshot_before_resource_creation(self):
        snapshot = self._snapshot({
            "subscription": {"type": "Trial", "state": "Disabled"},
            "roles": ["Reader"],
            "quotas": {
                "compute_vcpus": {"current": 4, "limit": 4},
                "storage_gib": {"current": 128, "limit": 128},
            },
            "regionalAvailability": {"eastus2": []},
            "tooling": {"azureCli": "2.40", "bicep": "0.10"},
        })
        result = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts" / "Deploy-Accelerator.ps1"),
             "-PreflightSnapshotPath", snapshot],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Preflight failed; provisioning was not started.", result.stderr)
        self.assertNotIn("deployment sub create", result.stdout + result.stderr)

    def test_reset_removes_only_delivery_state_and_reports_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("variant_store.sqlite3", "metadata_store.sqlite3", "run_history.sqlite3"):
                connection = sqlite3.connect(root / name)
                try:
                    connection.execute("CREATE TABLE records (value TEXT)")
                    connection.execute("INSERT INTO records VALUES ('prior delivery')")
                    connection.commit()
                finally:
                    connection.close()
            (root / "unrelated.txt").write_text("keep", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(RESET), "--state-root", str(root)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["clean"])
            self.assertFalse(report["infrastructure_touched"])
            self.assertTrue((root / "unrelated.txt").exists())
            diagnosis = subprocess.run(
                [sys.executable, str(RESET), "--state-root", str(root), "--diagnose"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(diagnosis.returncode, 0, diagnosis.stderr)
            self.assertTrue(json.loads(diagnosis.stdout)["clean"])

    def test_talk_track_separates_evidence_and_preserves_claim_boundaries(self):
        runbook = (ROOT / "docs" / "demo-runbook.md").read_text(encoding="utf-8")
        claims = (ROOT / "docs" / "claim-register.md").read_text(encoding="utf-8")
        self.assertIn("Demonstrated here", runbook)
        self.assertIn("Production consideration or specified only", runbook)
        for phrase in (
            "Microsoft blueprint",
            "compliance outcome",
            "confirmed customer deployment",
            "clinical decision",
        ):
            self.assertIn(phrase, runbook)
        for phrase in (
            "Microsoft blueprint",
            "makes your genomic data compliant",
            "Customers use this accelerator in production",
            "clinical decision-making",
        ):
            self.assertIn(phrase, claims)
        self.assertIn("AI-assisted analysis is", runbook)
        self.assertIn("exploratory", runbook)

    def test_tracked_repository_has_no_live_subscription_or_tenant_identifier(self):
        result = subprocess.run(
            [sys.executable, str(IDENTIFIER_SCAN)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No tracked Azure subscription or tenant identifiers found.", result.stdout)

    def test_deploy_deallocates_only_a_client_it_started(self):
        deploy = (ROOT / "scripts" / "Deploy-Accelerator.ps1").read_text()
        self.assertIn("$startedVerificationClient = $true", deploy)
        self.assertIn("if ($startedVerificationClient)", deploy)
        self.assertIn("'vm', 'deallocate'", deploy)


if __name__ == "__main__":
    unittest.main()
