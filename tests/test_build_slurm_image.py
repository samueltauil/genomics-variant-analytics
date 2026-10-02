import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_slurm_image import (
    ImageBuildConfig,
    _delete_owned_image_version,
    _image_version_count,
    _verify_repository_commit,
    _validation_script,
    _run,
    run_build,
    validate_config,
)


class TransientRetryTests(unittest.TestCase):
    @patch("scripts.build_slurm_image.time.sleep")
    @patch("scripts.build_slurm_image.shutil.which", return_value="/usr/bin/az")
    @patch("scripts.build_slurm_image.subprocess.run")
    def test_retries_only_connection_failures(self, run, _which, sleep):
        from subprocess import CompletedProcess

        dns = CompletedProcess([], 1, "", "Failed to resolve 'management.azure.com'")
        run.side_effect = [dns, CompletedProcess([], 0, "ok", "")]
        self.assertEqual(_run(["az", "group", "list"], error="x"), "ok")
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once()

        run.reset_mock()
        run.side_effect = [CompletedProcess([], 1, "", "AuthorizationFailed")]
        with self.assertRaisesRegex(RuntimeError, "AuthorizationFailed"):
            _run(["az", "group", "list"], error="x")
        self.assertEqual(run.call_count, 1)

        run.reset_mock()
        run.side_effect = [CompletedProcess([], 1, "", "Connection aborted")]
        with self.assertRaisesRegex(RuntimeError, "Connection aborted"):
            _run(["az", "sig", "image-version", "create"], error="x")
        self.assertEqual(run.call_count, 1)

        run.reset_mock()
        run.side_effect = [dns, dns, dns]
        with self.assertRaisesRegex(RuntimeError, "Failed to resolve"):
            _run(["az", "group", "list"], error="x")
        self.assertEqual(run.call_count, 3)

    @patch("scripts.build_slurm_image.shutil.which", return_value="/usr/bin/az")
    @patch("scripts.build_slurm_image.subprocess.run")
    def test_multiline_scripts_are_passed_as_files(self, run, _which):
        from subprocess import CompletedProcess

        seen = {}

        def capture(command, **_kwargs):
            argument = command[command.index("--scripts") + 1]
            seen["argument"] = argument
            seen["body"] = Path(argument[1:]).read_text(encoding="utf-8")
            return CompletedProcess([], 0, "{}", "")

        run.side_effect = capture
        _run(["az", "vm", "run-command", "invoke", "--scripts", "set -e\necho ok\n"], error="x")
        self.assertTrue(seen["argument"].startswith("@"))
        self.assertEqual(seen["body"], "set -e\necho ok\n")


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


SECURITY_PROFILE = json.dumps(
    {
        "securityType": "TrustedLaunch",
        "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True},
    }
)


def run_command_output(message):
    return json.dumps({"value": [{"message": message}]})


def builder_outputs():
    return json.dumps(
        {
            "properties": {
                "outputs": {
                    "buildVmId": {"value": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-build-syn-20260927"},
                    "buildVmName": {"value": "vm-build-syn-20260927"},
                    "buildSubnetId": {"value": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/snet-build"},
                }
            }
        }
    )


def version_show():
    return json.dumps(
        {
            "tags": {
                "project": "genomics-variant-accelerator",
                "component": "private-slurm-image",
                "environment": "20260927",
                "buildId": "syn-20260927",
                "amlfsInstall": "prebuilt-kmod",
                "secureBoot": "required",
                "vtpm": "required",
                "buildMethod": "trusted-launch-vm-capture",
                "buildStorageAccountCreated": "false",
            }
        }
    )


class PrivateSlurmImageTests(unittest.TestCase):
    def test_static_contract_is_pinned_and_trusted_launch_compatible(self):
        report = validate_config(config())
        self.assertEqual(
            report["source_image_urn"],
            "Canonical:ubuntu-24_04-lts:server:24.04.202609040",
        )
        self.assertEqual(report["build_method"], "trusted-launch-vm-capture")
        self.assertEqual(report["amlfs_install_method"], "prebuilt-kmod")
        self.assertFalse(report["build_storage_account_created"])
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
            config(repository_path="/opt"),
            config(repository_path="/opt/../etc"),
            config(repository_path="/etc/genomics-variant-analytics"),
            config(repository_path="/opt/repository;touch-bad"),
            config(repository_url="ssh://git@example.invalid/repository"),
            config(nextflow_url="https://github.com/nextflow-io/nextflow?token=bad"),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_config(value)

    def test_build_assets_capture_trusted_launch_vm_without_public_or_aib_resources(self):
        builder = (ROOT / "infra" / "slurm-image-builder.bicep").read_text()
        gallery = (ROOT / "infra" / "slurm-image-gallery.bicep").read_text()
        configure = (
            ROOT / "infra" / "scripts" / "configure-slurm-image.sh"
        ).read_text()
        self.assertIn("defaultOutboundAccess: true", builder)
        self.assertIn("securityType: 'TrustedLaunch'", builder)
        self.assertIn("secureBootEnabled: true", builder)
        self.assertIn("vTpmEnabled: true", builder)
        self.assertIn("disablePasswordAuthentication: true", builder)
        self.assertNotIn("publicIPAddresses", builder)
        self.assertNotIn("Microsoft.Network/publicIPAddresses", builder)
        self.assertNotIn("Microsoft.Storage/storageAccounts", builder)
        self.assertNotIn("Microsoft.VirtualMachineImages/imageTemplates", builder)
        self.assertNotIn("userAssignedIdentities", builder)
        self.assertIn("TrustedLaunchSupported", gallery)
        self.assertIn("amlfs_install_method", configure)
        self.assertIn("prebuilt-kmod", configure)
        self.assertIn("modinfo -F signer lustre", configure)
        self.assertIn("BC528686B50D79E339D3721CEB3E94ADBE1229CF", configure)
        self.assertIn("PRIVATE_SLURM_IMAGE_CONFIGURE_SUCCEEDED", configure)
        runtime_config = configure.split(
            "cat >/usr/local/sbin/configure-local-slurm <<EOF\n", 1
        )[1].split("\nEOF\n", 1)[0]
        self.assertIn("if [[ ! -s /etc/munge/munge.key ]]", runtime_config)
        self.assertIn(r"NodeName=\$host CPUs=\$(nproc)", runtime_config)
        self.assertNotIn(
            "dd if=/dev/urandom",
            configure.split(
                "cat >/usr/local/sbin/configure-local-slurm <<EOF", 1
            )[0],
        )
        munge_dropin = configure.split(
            "cat > /etc/systemd/system/munge.service.d/genomics.conf <<'EOF'\n",
            1,
        )[1].split("\nEOF\n", 1)[0]
        self.assertEqual(
            munge_dropin,
            "[Unit]\nRequires=genomics-slurm-config.service\n"
            "After=genomics-slurm-config.service",
        )
        self.assertIn(
            "After=genomics-slurm-config.service munge.service",
            configure,
        )
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
            "awk -F'|' '$1 == \"up\" && $2 > 0",
            "! command -v docker",
        ):
            self.assertIn(expected, script)
        configure = (
            ROOT / "infra" / "scripts" / "configure-slurm-image.sh"
        ).read_text()
        self.assertIn("azureuser ALL=(ALL) NOPASSWD: ALL", configure)
        self.assertIn("for tool in mount.lustre", script)
        self.assertIn("xargs awk;", script)

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

    def test_run_build_sequence_captures_then_cleans_before_validation(self):
        operations = []
        cleanups = []

        def fake_run(command, *, error):
            operations.append("run:" + command[0])
            if command[0] == "ssh-keygen":
                Path(command[-1] + ".pub").write_text(
                    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticOnly\n",
                    encoding="utf-8",
                )
            return ""

        def fake_az(_cfg, *args, error):
            command = " ".join(args)
            operations.append(command)
            if args[:3] == ("deployment", "group", "create") and any(
                "builder-" in arg for arg in args
            ):
                return builder_outputs()
            if args[:2] == ("vm", "show"):
                return SECURITY_PROFILE
            if args[:3] == ("vm", "run-command", "invoke") and "Build VM configuration" in error:
                return run_command_output("PRIVATE_SLURM_IMAGE_CONFIGURE_SUCCEEDED")
            if args[:3] == ("vm", "run-command", "invoke") and "pre-capture" in error:
                return run_command_output('{"build_vm_pre_capture": true, "kernel": "6.17.0-1022-azure", "secure_boot": "enabled"}')
            if args[:3] == ("vm", "run-command", "invoke") and "deprovision" in error:
                return run_command_output("PRIVATE_SLURM_IMAGE_DEPROVISION_SUCCEEDED")
            if args[:3] == ("sig", "image-version", "show"):
                return version_show()
            if args[:3] == ("vm", "run-command", "invoke") and "Image interface" in error:
                return run_command_output(
                    '{"interface": "private-slurm-image", "secure_boot": "enabled", '
                    '"vtpm": "enabled", "kernel": "6.17.0-1022-azure", '
                    '"amlfs_client": "2.17.0-24-gf517bc4", '
                    '"amlfs_install_method": "prebuilt-kmod", '
                    '"repository_commit": "844d2f732fe41dccdf420646f3dad0402a6a797c"}'
                )
            return "{}"

        def fake_cleanup(_cfg, group, component):
            cleanups.append(group)
            operations.append("cleanup:" + group)

        with (
            patch("scripts.build_slurm_image._source_preflight"),
            patch("scripts.build_slurm_image._image_version_count", return_value=0),
            patch("scripts.build_slurm_image._ensure_group"),
            patch("scripts.build_slurm_image._run", side_effect=fake_run),
            patch("scripts.build_slurm_image._az", side_effect=fake_az),
            patch("scripts.build_slurm_image._delete_owned_group", side_effect=fake_cleanup),
            patch("scripts.build_slurm_image._delete_owned_image_version") as delete_version,
        ):
            report = run_build(config())

        self.assertEqual(report["build_method"], "trusted-launch-vm-capture")
        self.assertFalse(report["build_storage_account_created"])
        self.assertFalse(delete_version.called)
        self.assertIn(config().build_resource_group, cleanups)
        expected = [
            "deployment group create",
            "vm run-command invoke",  # configure
            "vm run-command invoke",  # pre-capture verify
            "vm run-command invoke",  # deprovision
            "vm deallocate",
            "vm generalize",
            "sig image-version create",
            "cleanup:" + config().build_resource_group,
            "vm create",
            "vm run-command invoke",  # validation
        ]
        cursor = 0
        for wanted in expected:
            while cursor < len(operations) and wanted not in operations[cursor]:
                cursor += 1
            self.assertLess(cursor, len(operations), f"missing {wanted} in {operations}")
            cursor += 1

    def test_run_build_cleans_up_failures_before_and_after_capture(self):
        for failing_error, deletes_version in (
            ("Build VM configuration failed", False),
            ("Build VM pre-capture verification failed", False),
            ("Build VM deprovision failed", False),
            ("Gallery image version capture failed", True),
            ("Image interface validation failed", True),
        ):
            with self.subTest(failing_error=failing_error):
                cleanups = []

                def fake_run(command, *, error):
                    if command[0] == "ssh-keygen":
                        Path(command[-1] + ".pub").write_text(
                            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticOnly\n",
                            encoding="utf-8",
                        )
                    return ""

                def fake_az(_cfg, *args, error):
                    if error == failing_error:
                        raise RuntimeError(failing_error)
                    if args[:3] == ("deployment", "group", "create") and any(
                        "builder-" in arg for arg in args
                    ):
                        return builder_outputs()
                    if args[:2] == ("vm", "show"):
                        return SECURITY_PROFILE
                    if args[:3] == ("vm", "run-command", "invoke") and "configuration" in error:
                        return run_command_output("PRIVATE_SLURM_IMAGE_CONFIGURE_SUCCEEDED")
                    if args[:3] == ("vm", "run-command", "invoke") and "pre-capture" in error:
                        return run_command_output('{"build_vm_pre_capture": true, "kernel": "6.17.0-1022-azure", "secure_boot": "enabled"}')
                    if args[:3] == ("vm", "run-command", "invoke") and "deprovision" in error:
                        return run_command_output("PRIVATE_SLURM_IMAGE_DEPROVISION_SUCCEEDED")
                    if args[:3] == ("sig", "image-version", "show"):
                        return version_show()
                    return "{}"

                with (
                    patch("scripts.build_slurm_image._source_preflight"),
                    patch("scripts.build_slurm_image._image_version_count", return_value=0),
                    patch("scripts.build_slurm_image._ensure_group"),
                    patch("scripts.build_slurm_image._run", side_effect=fake_run),
                    patch("scripts.build_slurm_image._az", side_effect=fake_az),
                    patch(
                        "scripts.build_slurm_image._delete_owned_group",
                        side_effect=lambda _cfg, group, _component: cleanups.append(group),
                    ),
                    patch("scripts.build_slurm_image._delete_owned_image_version") as delete_version,
                ):
                    with self.assertRaisesRegex(RuntimeError, failing_error):
                        run_build(config())
                self.assertIn(config().build_resource_group, cleanups)
                self.assertEqual(delete_version.called, deletes_version)


if __name__ == "__main__":
    unittest.main()
