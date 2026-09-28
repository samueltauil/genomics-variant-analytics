import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hpc_campaign import (
    COMPATIBILITY,
    CampaignConfig,
    _worker_script,
    build_synthetic_bundle,
    run_campaign,
    validate_config,
)
from scripts.run_nextflow_secondary_pipeline import _artifact_uris, _validate_durable_uri
from scripts.secondary_pipeline import synthetic_reference_identity


REFERENCE_VERSION = "synthetic-1385e2e921c4"
REFERENCE_MANIFEST_DIGEST = synthetic_reference_identity()["reference_manifest_sha256"]


def config(**overrides):
    values = {
        "subscription_id": "<subscription-id>",
        "location": "eastus2",
        "campaign_id": "synthetic-001",
        "campaign_owner": "SYN-OWNER-001",
        "admin_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticOnly",
        "reference_build": "SYN-demo-genome",
        "reference_version": REFERENCE_VERSION,
        "reference_manifest_sha256": REFERENCE_MANIFEST_DIGEST,
        "slurm_image_id": (
            "/subscriptions/<subscription-id>/"
            "resourceGroups/rg-images/providers/Microsoft.Compute/"
            "galleries/genomics/images/slurm-synthetic/versions/2026.9.27"
        ),
        "staging_identity_resource_id": (
            "/subscriptions/<subscription-id>/"
            "resourceGroups/rg-genomics-syn/providers/Microsoft.ManagedIdentity/"
            "userAssignedIdentities/id-genomics-staging"
        ),
        "staging_identity_client_id": "11111111-1111-1111-1111-111111111111",
        "staging_identity_principal_id": "22222222-2222-2222-2222-222222222222",
        "staging_storage_account_id": (
            "/subscriptions/<subscription-id>/"
            "resourceGroups/rg-genomics-syn/providers/Microsoft.Storage/"
            "storageAccounts/stglakesynthetic"
        ),
        "staging_storage_account_name": "stglakesynthetic",
        "staging_environment": "synthetic",
    }
    values.update(overrides)
    return CampaignConfig(**values)


class HpcCampaignTests(unittest.TestCase):
    def test_local_validation_pins_compatible_reference_without_azure(self):
        report = validate_config(config())
        self.assertEqual(report["mode"], "local-static-validation")
        self.assertFalse(report["azure_resources_created"])
        self.assertEqual(
            report["resolved_references"],
            [["genome", "SYN-demo-genome", REFERENCE_VERSION]],
        )
        compatibility = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))
        self.assertEqual(
            compatibility["workflows"][0]["reference_manifest_sha256"],
            REFERENCE_MANIFEST_DIGEST,
        )

    def test_missing_or_incompatible_reference_is_rejected_before_allocation(self):
        for invalid in (
            config(reference_build="GRCh37"),
            config(reference_version="synthetic-missing"),
            config(reference_manifest_sha256="not-a-digest"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_config(invalid)

    def test_synthetic_bundle_is_generated_only_in_temporary_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = build_synthetic_bundle(directory, config())
            self.assertTrue(manifest["synthetic"])
            self.assertEqual(manifest["reference_build"], "SYN-demo-genome")
            self.assertEqual(manifest["reference_version"], REFERENCE_VERSION)
            self.assertIn("reference.fasta", manifest["files"])
            self.assertTrue((directory / "campaign-input-manifest.json").is_file())
            self.assertFalse(any("patient" in path.name.lower() for path in directory.iterdir()))

    def test_worker_uses_private_identity_copy_mount_and_integrity_gates(self):
        outputs = {
            "storageAccountName": {"value": "stghpcsynthetic"},
            "inputContainerName": {"value": "campaign-input"},
            "outputContainerName": {"value": "campaign-output"},
            "logContainerName": {"value": "campaign-logs"},
            "identityClientId": {"value": "11111111-1111-1111-1111-111111111111"},
            "amlfsMountAddress": {"value": "10.43.2.4"},
        }
        script = _worker_script(config(), outputs)
        self.assertIn("mount -t lustre", script)
        self.assertIn("AZCOPY_AUTO_LOGIN_TYPE=MSI", script)
        self.assertIn("azcopy login --identity --identity-client-id", script)
        self.assertIn("python3 java nextflow sbatch sinfo mount mount.lustre mountpoint", script)
        self.assertIn("findmnt sha256sum find sort xargs samtools sudo", script)
        self.assertIn("sha256sum -c SHA256SUMS", script)
        self.assertIn("sha256sum -c OUTPUT-SHA256SUMS", script)
        self.assertIn("--profile slurm", script)
        self.assertIn('--input-uri-base "$input_uri"', script)
        self.assertIn('--output-uri-base "$output_uri"', script)
        self.assertIn('--log-uri "$log_uri/.nextflow.log"', script)
        self.assertIn("CAMPAIGN_COPY_OUT_VERIFIED=1", script)
        lowered = script.lower()
        self.assertNotIn("accountkey=", lowered)
        self.assertNotIn("sharedaccesssignature=", lowered)
        self.assertNotIn("?sig=", lowered)

    def test_templates_keep_lustre_separate_from_private_blob_staging(self):
        root = Path(__file__).resolve().parents[1]
        campaign = (root / "infra" / "hpc-campaign.bicep").read_text()
        lustre = (root / "infra" / "modules" / "managed-lustre.bicep").read_text()
        scheduler = (root / "infra" / "modules" / "slurm-scheduler.bicep").read_text()
        slurm = (root / "workflows" / "conf" / "slurm.config").read_text()
        self.assertIn("stagingStorageAccountId", campaign)
        self.assertIn("private-link-campaign-blob", campaign)
        self.assertNotIn("Microsoft.Storage/storageAccounts@", campaign)
        self.assertNotIn("hsm:", lustre.lower())
        self.assertNotIn("dataContainerId", lustre)
        self.assertIn("@minLength(1)\nparam sourceImageId string", scheduler)
        self.assertNotIn("Canonical", scheduler)
        self.assertNotIn("empty(sourceImageId)", scheduler)
        self.assertIn("SLURM_LUSTRE_WORKDIR is required", slurm)
        self.assertNotIn("?: '/mnt/amlfs", slurm)
        self.assertIn("docker.enabled = false", slurm)
        self.assertNotIn("AZURE_BATCH_ACR_LOGIN_SERVER", slurm)

    def test_campaign_identifiers_and_owner_are_restricted(self):
        for invalid in (
            config(campaign_id="../escape"),
            config(campaign_id="UPPER"),
            config(campaign_owner="owner\nother"),
            config(repository_path="relative/path"),
            config(slurm_image_id="/subscriptions/not-an-image"),
            config(staging_storage_account_name="INVALID"),
            config(output_prefix="../escape"),
            config(output_prefix="Process/HPC/Input"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_config(invalid)

    def test_durable_provenance_uris_replace_ephemeral_work_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "SYN-SAMPLE-0001.bam").write_bytes(b"synthetic")
            (directory / "qc report.json").write_text("{}", encoding="utf-8")
            base = _validate_durable_uri(
                "https://stgsynthetic.blob.core.windows.net/healthcare/"
                "Process/HPC/Output/synthetic-001",
                "output_uri_base",
            )
            self.assertEqual(
                _artifact_uris(directory, base),
                [
                    f"{base}/qc%20report.json",
                    f"{base}/SYN-SAMPLE-0001.bam",
                ],
            )
        for invalid in (
            "file:///mnt/amlfs/results",
            "https://storage.invalid/container?sig=synthetic",
            "relative/path",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _validate_durable_uri(invalid, "output_uri_base")

    def test_manifest_is_exactly_reproducible_for_synthetic_input(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = build_synthetic_bundle(Path(first), config())
            two = build_synthetic_bundle(Path(second), config())
            self.assertEqual(one, two)
            self.assertEqual(
                json.loads((Path(first) / "campaign-input-manifest.json").read_text()),
                json.loads((Path(second) / "campaign-input-manifest.json").read_text()),
            )

    @patch("scripts.hpc_campaign._delete_owned_group")
    @patch("scripts.hpc_campaign._az")
    @patch("scripts.hpc_campaign._assert_group_owned", return_value=False)
    @patch("scripts.hpc_campaign.cloud_preflight")
    def test_failed_campaign_always_tears_down_owned_group(
        self, preflight, owned, az, delete
    ):
        az.side_effect = [
            "",
            json.dumps({
                "properties": {
                    "outputs": {
                        "storageAccountName": {"value": "stghpcsynthetic"},
                        "inputContainerName": {"value": "campaign-input"},
                        "outputContainerName": {"value": "campaign-output"},
                        "logContainerName": {"value": "campaign-logs"},
                        "identityClientId": {
                            "value": "11111111-1111-1111-1111-111111111111"
                        },
                        "amlfsMountAddress": {"value": "10.43.2.4"},
                        "slurmVmName": {"value": "vm-slurm-synthetic-001"},
                    }
                }
            }),
            RuntimeError("worker failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "worker failed"):
            run_campaign(config())

        preflight.assert_called_once()
        owned.assert_called_once()
        delete.assert_called_once()

    @patch("scripts.hpc_campaign._delete_owned_group")
    @patch("scripts.hpc_campaign._az")
    @patch("scripts.hpc_campaign._assert_group_owned", return_value=False)
    @patch("scripts.hpc_campaign.cloud_preflight")
    def test_successful_campaign_tears_down_after_verified_copy_out(
        self, preflight, owned, az, delete
    ):
        az.side_effect = [
            "",
            json.dumps({
                "properties": {
                    "outputs": {
                        "storageAccountName": {"value": "stghpcsynthetic"},
                        "inputContainerName": {"value": "campaign-input"},
                        "outputContainerName": {"value": "campaign-output"},
                        "logContainerName": {"value": "campaign-logs"},
                        "identityClientId": {
                            "value": "11111111-1111-1111-1111-111111111111"
                        },
                        "amlfsMountAddress": {"value": "10.43.2.4"},
                        "slurmVmName": {"value": "vm-slurm-synthetic-001"},
                    }
                }
            }),
            "CAMPAIGN_COPY_OUT_VERIFIED=1",
        ]

        report = run_campaign(config())

        self.assertEqual(report["terminal_state"], "succeeded")
        self.assertTrue(report["copy_out_verified"])
        preflight.assert_called_once()
        owned.assert_called_once()
        delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
