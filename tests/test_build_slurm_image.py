import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_slurm_image import (
    ImageBuildConfig,
    _delete_owned_image_version,
    _image_version_count,
    _verify_repository_commit,
    _validation_script,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]


def config(**overrides):
    values = {
        "subscription_id": "<subscription-id>",
        "location": "eastus2",
        "environment": "20260927",
        "build_id": "syn-20260927",
        "gallery_resource_group": "rg-genomics-images-20260927",
        "gallery_name": "galgenomics20260927",
        "image_definition_name": "slurm-ubuntu2404-amlfs",
        "image_version": "2026.9.27",
        "source_image_version": "24.04.202609040",
        "source_kernel": "6.17.0-1022-azure",
        "amlfs_version": "2.17.0-24-gf517bc4",
        "amlfs_package_version": "6.17.0-1022-azure",
        "nextflow_version": "26.04.6",
        "nextflow_sha256": "61a755edbed743cfbb568f3a6c67af68481a2f6a4d6dffcc4295e51318968281",
        "nextflow_url": "https://github.com/nextflow-io/nextflow/releases/download/v26.04.6/nextflow",
        "azcopy_version": "10.32.8",
        "azcopy_sha256": "b143b9946293a11d428181d244ee5f5801786a38801a00430f0b67c844c9a2bd",
        "azcopy_url": "https://github.com/Azure/azure-storage-azcopy/releases/download/v10.32.8/azcopy-10.32.8.x86_64.deb",
        "repository_url": "https://github.com/samueltauil/genomics-variant-analytics.git",
        "repository_commit": "844d2f732fe41dccdf420646f3dad0402a6a797c",
    }
    values.update(overrides)
    return ImageBuildConfig(**values)


class PrivateSlurmImageTests(unittest.TestCase):
    def test_static_contract_is_pinned_and_trusted_launch_compatible(self):
        report = validate_config(config())
        self.assertEqual(
            report["source_image_urn"],
            "Canonical:ubuntu-24_04-lts:server:24.04.202609040",
        )
        self.assertEqual(report["amlfs_install_method"], "prebuilt-kmod")
        self.assertTrue(report["secure_boot_required"])
        self.assertTrue(report["vtpm_required"])
        self.assertIn("/versions/2026.9.27", report["image_version_id"])

    def test_unpinned_or_incompatible_inputs_fail_closed(self):
        invalid = (
            config(image_version="latest"),
            config(source_image_version="latest"),
            config(source_kernel="6.17.0-1022-generic"),
            config(amlfs_package_version="6.17.0-1021-azure"),
            config(nextflow_version="23.09.9"),
            config(nextflow_sha256="not-a-digest"),
            config(repository_commit="main"),
            config(repository_path="relative/path"),
            config(repository_path="/opt/repository;touch-bad"),
            config(repository_url="ssh://git@example.invalid/repository"),
            config(nextflow_url="https://github.com/nextflow-io/nextflow?token=bad"),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_config(value)

    def test_build_assets_preserve_secure_boot_and_exclude_dkms(self):
        builder = (ROOT / "infra" / "slurm-image-builder.bicep").read_text()
        gallery = (ROOT / "infra" / "slurm-image-gallery.bicep").read_text()
        configure = (
            ROOT / "infra" / "scripts" / "configure-slurm-image.sh"
        ).read_text()
        self.assertNotIn("containerInstanceSubnetId", builder)
        self.assertIn("defaultOutboundAccess: true", builder)
        self.assertNotIn("mokutil --sb-state", builder)
        self.assertIn("TrustedLaunchSupported", gallery)
        self.assertIn("amlfs_install_method", configure)
        self.assertIn("prebuilt-kmod", configure)
        self.assertIn("modinfo -F signer lustre", configure)
        self.assertIn("BC528686B50D79E339D3721CEB3E94ADBE1229CF", configure)
        self.assertNotIn("secureBootEnabled: false", builder)
        self.assertNotIn("lustre-client-dkms", builder)
        self.assertNotIn("apt-get install -y lustre-client-dkms", configure)
        self.assertIn("! command -v docker", configure)

    def test_validation_checks_complete_campaign_image_interface(self):
        script = _validation_script(config())
        for expected in (
            "SecureBoot enabled",
            "modinfo -F signer lustre",
            "kmod-lustre-client-6.17.0-1022-azure-2.17.0-24-gf517bc4",
            "sudo -n modprobe lustre",
            'nextflow -version | grep -F "26.04.6"',
            "mount.lustre",
            "azcopy login --help",
            "systemctl is-active --quiet walinuxagent",
            "systemctl is-active --quiet munge",
            "systemctl is-active --quiet slurmctld",
            "systemctl is-active --quiet slurmd",
            "sinfo -h -p",
            "sudo -n true",
            "/opt/genomics-variant-analytics",
            "! command -v docker",
        ):
            self.assertIn(expected, script)
        configure = (
            ROOT / "infra" / "scripts" / "configure-slurm-image.sh"
        ).read_text()
        self.assertIn("azureuser ALL=(ALL) NOPASSWD: ALL", configure)

    @patch("scripts.build_slurm_image._az", return_value="0\n")
    def test_image_version_count_is_explicit_and_numeric(self, az):
        self.assertEqual(_image_version_count(config()), 0)
        self.assertTrue(
            any(
                isinstance(argument, str) and "length(@)" in argument
                for argument in az.call_args.args
            )
        )

    @patch("scripts.build_slurm_image._az")
    def test_failed_image_cleanup_refuses_foreign_version(self, az):
        az.side_effect = [
            "1\n",
            '{"tags":{"project":"genomics-variant-accelerator",'
            '"component":"private-slurm-image","environment":"20260927",'
            '"buildId":"other-build"}}',
        ]
        with self.assertRaisesRegex(RuntimeError, "ownership tags"):
            _delete_owned_image_version(config())

    @patch("scripts.build_slurm_image._run")
    def test_repository_commit_must_be_fetchable_and_exact(self, run):
        run.side_effect = [
            "",
            "",
            config().repository_commit + "\n",
            (
                "throw new IllegalStateException("
                "'SLURM_LUSTRE_WORKDIR is required')\n"
                "docker.enabled = false\n"
            ),
            (
                '"--reference-manifest-sha256"\n"--input-uri-base"\n'
                '"--output-uri-base"\n"--log-uri"\n"--profile"\n'
            ),
        ]
        _verify_repository_commit(config())
        fetch = run.call_args_list[1].args[0]
        self.assertIn(config().repository_commit, fetch)
        self.assertIn(config().repository_url, fetch)

        run.reset_mock()
        run.side_effect = ["", "", "0" * 40 + "\n"]
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            _verify_repository_commit(config())

        run.reset_mock()
        run.side_effect = [
            "",
            "",
            config().repository_commit + "\n",
            "docker.enabled = true\nAZURE_BATCH_ACR_LOGIN_SERVER\n",
            '"--profile"\n',
        ]
        with self.assertRaisesRegex(RuntimeError, "audited Slurm interface"):
            _verify_repository_commit(config())

    def test_campaign_requires_gallery_version_and_secure_boot(self):
        campaign = (ROOT / "scripts" / "hpc_campaign.py").read_text()
        scheduler = (ROOT / "infra" / "modules" / "slurm-scheduler.bicep").read_text()
        self.assertNotIn("|galleries/", campaign)
        self.assertIn("galleries/", campaign)
        self.assertIn("secureBootEnabled: true", scheduler)


if __name__ == "__main__":
    unittest.main()
