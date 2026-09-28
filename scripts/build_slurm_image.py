"""Build and validate the private Trusted Launch Slurm/AMLFS gallery image."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
GALLERY_TEMPLATE = ROOT / "infra" / "slurm-image-gallery.bicep"
BUILDER_TEMPLATE = ROOT / "infra" / "slurm-image-builder.bicep"
PROJECT = "genomics-variant-accelerator"
BUILD_COMPONENT = "hpc-image-build"
IMAGE_COMPONENT = "private-slurm-image"
GALLERY_PUBLISHER_ROLE = "Compute Gallery Artifacts Publisher"
CONTRIBUTOR_ROLE = "Contributor"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{2,23}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ImageBuildConfig:
    subscription_id: str
    location: str
    environment: str
    build_id: str
    gallery_resource_group: str
    gallery_name: str
    image_definition_name: str
    image_version: str
    source_image_version: str
    source_kernel: str
    amlfs_version: str
    amlfs_package_version: str
    nextflow_version: str
    nextflow_sha256: str
    nextflow_url: str
    azcopy_version: str
    azcopy_sha256: str
    azcopy_url: str
    repository_url: str
    repository_commit: str
    repository_path: str = "/opt/genomics-variant-analytics"
    slurm_partition: str = "debug"
    build_vm_size: str = "Standard_D4s_v7"
    validation_vm_size: str = "Standard_D4s_v7"

    @property
    def build_resource_group(self) -> str:
        return f"rg-genomics-image-build-{self.build_id}"

    @property
    def validation_resource_group(self) -> str:
        return f"rg-genomics-image-validate-{self.build_id}"

    @property
    def staging_resource_group(self) -> str:
        return f"rg-genomics-image-stage-{self.build_id}"

    @property
    def image_definition_id(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/"
            f"{self.gallery_resource_group}/providers/Microsoft.Compute/galleries/"
            f"{self.gallery_name}/images/{self.image_definition_name}"
        )

    @property
    def image_version_id(self) -> str:
        return f"{self.image_definition_id}/versions/{self.image_version}"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()


def _pinned_github_url(value: str, name: str) -> str:
    normalized = _required(value, name)
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/[A-Za-z0-9._/-]+", parsed.path)
    ):
        raise ValueError(
            f"{name} must be a credential-free HTTPS GitHub URL without query or fragment."
        )
    return normalized


def validate_config(config: ImageBuildConfig) -> dict[str, Any]:
    for name in (
        "subscription_id",
        "location",
        "environment",
        "gallery_resource_group",
        "gallery_name",
        "image_definition_name",
        "source_image_version",
        "source_kernel",
        "amlfs_version",
        "amlfs_package_version",
        "nextflow_version",
        "nextflow_url",
        "azcopy_version",
        "azcopy_url",
        "repository_url",
    ):
        _required(getattr(config, name), name)
    if not IDENTIFIER.fullmatch(config.build_id):
        raise ValueError("build_id must be 3-24 lowercase letters, digits, or hyphens.")
    if not VERSION.fullmatch(config.image_version):
        raise ValueError("image_version must be an explicit three-part gallery version.")
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{6,}", config.source_image_version):
        raise ValueError("source_image_version must be an explicit Canonical image version.")
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+-azure", config.source_kernel):
        raise ValueError("source_kernel must be an explicit Ubuntu Azure kernel release.")
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+-g[0-9a-f]+", config.amlfs_version):
        raise ValueError("amlfs_version must identify an explicit Microsoft AMLFS release.")
    if config.amlfs_package_version != config.source_kernel:
        raise ValueError("amlfs_package_version must equal the pinned source kernel.")
    for value, name in (
        (config.nextflow_sha256, "nextflow_sha256"),
        (config.azcopy_sha256, "azcopy_sha256"),
    ):
        if not DIGEST.fullmatch(value):
            raise ValueError(f"{name} must be a lowercase SHA-256 digest.")
    if not COMMIT.fullmatch(config.repository_commit):
        raise ValueError("repository_commit must be a full Git commit SHA.")
    if not re.fullmatch(r"/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+", config.repository_path):
        raise ValueError("repository_path must be a safe absolute non-root POSIX path.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", config.slurm_partition):
        raise ValueError("slurm_partition contains unsupported characters.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", config.nextflow_version):
        raise ValueError("nextflow_version contains unsupported characters.")
    nextflow_parts = tuple(int(part) for part in config.nextflow_version.split("."))
    if nextflow_parts < (23, 10, 0):
        raise ValueError("nextflow_version must be at least 23.10.0.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", config.azcopy_version):
        raise ValueError("azcopy_version contains unsupported characters.")
    if not re.fullmatch(r"Standard_[A-Za-z0-9_]+", config.build_vm_size):
        raise ValueError("build_vm_size must be an explicit Standard Azure VM SKU.")
    if not re.fullmatch(r"Standard_[A-Za-z0-9_]+", config.validation_vm_size):
        raise ValueError("validation_vm_size must be an explicit Standard Azure VM SKU.")
    _pinned_github_url(config.repository_url, "repository_url")
    _pinned_github_url(config.nextflow_url, "nextflow_url")
    _pinned_github_url(config.azcopy_url, "azcopy_url")

    source_urn = (
        "Canonical:ubuntu-24_04-lts:server:" + config.source_image_version
    )
    return {
        "mode": "local-static-validation",
        "azure_resources_created": False,
        "source_image_urn": source_urn,
        "source_kernel": config.source_kernel,
        "amlfs_install_method": "prebuilt-kmod",
        "image_version_id": config.image_version_id,
        "repository_commit": config.repository_commit,
        "repository_path": config.repository_path,
        "secure_boot_required": True,
        "vtpm_required": True,
    }


def _run(arguments: list[str], *, error: str) -> str:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise RuntimeError(f"{error}: executable not found: {arguments[0]}")
    command = [executable, *arguments[1:]]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        completed = subprocess.run(
            subprocess.list2cmdline(command),
            capture_output=True,
            text=True,
            check=False,
            shell=True,
        )
    else:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{error}: {detail}")
    return completed.stdout


def _az(config: ImageBuildConfig, *arguments: str, error: str) -> str:
    return _run(
        ["az", *arguments, "--subscription", config.subscription_id],
        error=error,
    )


def _expected_group_tags(config: ImageBuildConfig, component: str) -> dict[str, str]:
    return {
        "project": PROJECT,
        "component": component,
        "environment": config.environment,
        "buildId": config.build_id,
    }


def _ensure_group(
    config: ImageBuildConfig, name: str, component: str, *, retain: bool = False
) -> None:
    exists = _az(
        config, "group", "exists", "--name", name, "-o", "tsv",
        error=f"Could not inspect resource group {name}",
    ).strip().lower()
    required = _expected_group_tags(config, component)
    if retain:
        required.pop("buildId")
    if exists == "true":
        group = json.loads(_az(
            config, "group", "show", "--name", name, "-o", "json",
            error=f"Could not read resource group {name}",
        ))
        tags = group.get("tags") or {}
        mismatch = {key: (tags.get(key), value) for key, value in required.items()
                    if tags.get(key) != value}
        if mismatch:
            raise RuntimeError(
                f"Refusing resource group {name} with mismatched ownership tags: "
                + json.dumps(mismatch, sort_keys=True)
            )
        return
    tag_args = [f"{key}={value}" for key, value in required.items()]
    _az(
        config, "group", "create", "--name", name, "--location", config.location,
        "--tags", *tag_args, "-o", "none",
        error=f"Could not create resource group {name}",
    )


def _delete_owned_group(config: ImageBuildConfig, name: str, component: str) -> None:
    exists = _az(
        config, "group", "exists", "--name", name, "-o", "tsv",
        error=f"Could not inspect cleanup group {name}",
    ).strip().lower()
    if exists == "false":
        return
    group = json.loads(_az(
        config, "group", "show", "--name", name, "-o", "json",
        error=f"Could not inspect cleanup ownership for {name}",
    ))
    tags = group.get("tags") or {}
    required = _expected_group_tags(config, component)
    if any(tags.get(key) != value for key, value in required.items()):
        raise RuntimeError(f"Refusing to delete unowned resource group {name}.")
    _az(
        config, "group", "delete", "--name", name, "--yes", "--no-wait",
        error=f"Could not start cleanup for {name}",
    )
    _az(
        config, "group", "wait", "--deleted", "--name", name,
        "--interval", "15", "--timeout", "1800",
        error=f"Cleanup did not complete for {name}",
    )


def _image_version_count(config: ImageBuildConfig) -> int:
    output = _az(
        config,
        "sig",
        "image-version",
        "list",
        "--resource-group",
        config.gallery_resource_group,
        "--gallery-name",
        config.gallery_name,
        "--gallery-image-definition",
        config.image_definition_name,
        "--query",
        f"[?name=='{config.image_version}'] | length(@)",
        "-o",
        "tsv",
        error="Could not inspect gallery image-version immutability",
    ).strip()
    try:
        return int(output)
    except ValueError as error:
        raise RuntimeError(
            f"Gallery image-version count was not numeric: {output!r}."
        ) from error


def _delete_owned_image_version(config: ImageBuildConfig) -> None:
    if _image_version_count(config) == 0:
        return
    version = json.loads(
        _az(
            config,
            "sig",
            "image-version",
            "show",
            "--resource-group",
            config.gallery_resource_group,
            "--gallery-name",
            config.gallery_name,
            "--gallery-image-definition",
            config.image_definition_name,
            "--gallery-image-version",
            config.image_version,
            "-o",
            "json",
            error="Could not inspect failed image version",
        )
    )
    tags = version.get("tags") or {}
    required = {
        "project": PROJECT,
        "component": IMAGE_COMPONENT,
        "environment": config.environment,
        "buildId": config.build_id,
    }
    if any(tags.get(key) != value for key, value in required.items()):
        raise RuntimeError("Refusing to delete an image version without matching ownership tags.")
    _az(
        config,
        "sig",
        "image-version",
        "delete",
        "--resource-group",
        config.gallery_resource_group,
        "--gallery-name",
        config.gallery_name,
        "--gallery-image-definition",
        config.image_definition_name,
        "--gallery-image-version",
        config.image_version,
        "--yes",
        error="Could not remove unvalidated image version",
    )
    if _image_version_count(config) != 0:
        raise RuntimeError("Unvalidated gallery image version still exists after cleanup.")


def _verify_repository_commit(config: ImageBuildConfig) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        _run(
            ["git", "-C", temporary, "init", "--quiet"],
            error="Could not initialize repository provenance check",
        )
        _run(
            [
                "git",
                "-C",
                temporary,
                "fetch",
                "--quiet",
                "--depth",
                "1",
                config.repository_url,
                config.repository_commit,
            ],
            error="Pinned repository commit is not fetchable from the declared repository",
        )
        fetched = _run(
            ["git", "-C", temporary, "rev-parse", "FETCH_HEAD"],
            error="Could not resolve fetched repository commit",
        ).strip()
        if fetched != config.repository_commit:
            raise RuntimeError("Fetched repository commit does not match the declared commit.")
        slurm_config = _run(
            [
                "git",
                "-C",
                temporary,
                "show",
                "FETCH_HEAD:workflows/conf/slurm.config",
            ],
            error="Pinned repository commit lacks the Slurm profile",
        )
        launcher = _run(
            [
                "git",
                "-C",
                temporary,
                "show",
                "FETCH_HEAD:scripts/run_nextflow_secondary_pipeline.py",
            ],
            error="Pinned repository commit lacks the Nextflow launcher",
        )
        for required in (
            "SLURM_LUSTRE_WORKDIR is required",
            "docker.enabled = false",
        ):
            if required not in slurm_config:
                raise RuntimeError(
                    f"Pinned repository commit lacks audited Slurm interface: {required}."
                )
        if "AZURE_BATCH_ACR_LOGIN_SERVER" in slurm_config:
            raise RuntimeError(
                "Pinned repository Slurm profile still depends on the Batch container registry."
            )
        for required in (
            "--reference-manifest-sha256",
            "--input-uri-base",
            "--output-uri-base",
            "--log-uri",
            "--profile",
        ):
            if required not in launcher:
                raise RuntimeError(
                    f"Pinned repository commit lacks audited launcher option: {required}."
                )


def _source_preflight(config: ImageBuildConfig) -> None:
    for executable in ("az", "git", "ssh-keygen"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Required local tool is unavailable: {executable}.")
    _verify_repository_commit(config)
    for template in (GALLERY_TEMPLATE, BUILDER_TEMPLATE):
        _run(
            ["az", "bicep", "build", "--file", str(template), "--stdout"],
            error=f"Bicep compilation failed for {template.name}",
        )
    for namespace in (
        "Microsoft.Compute",
        "Microsoft.Network",
        "Microsoft.ContainerInstance",
        "Microsoft.ManagedIdentity",
        "Microsoft.VirtualMachineImages",
    ):
        state = _az(
            config, "provider", "show", "--namespace", namespace,
            "--query", "registrationState", "-o", "tsv",
            error=f"Could not inspect provider {namespace}",
        ).strip()
        if state != "Registered":
            _az(
                config, "provider", "register", "--namespace", namespace,
                "--wait", "-o", "none",
                error=f"Could not register provider {namespace}",
            )
    source = json.loads(_az(
        config, "vm", "image", "show", "--location", config.location,
        "--urn", "Canonical:ubuntu-24_04-lts:server:" + config.source_image_version,
        "-o", "json", error="Pinned Canonical source image is unavailable",
    ))
    features = {item["name"]: item["value"] for item in source.get("features", [])}
    if source.get("hyperVGeneration") != "V2":
        raise RuntimeError("Pinned source image is not Hyper-V generation V2.")
    if features.get("SecurityType") != "TrustedLaunchSupported":
        raise RuntimeError("Pinned source image is not TrustedLaunchSupported.")


def _builder_parameters(
    config: ImageBuildConfig, *, deploy_image_template: bool
) -> list[str]:
    values = {
        "location": config.location,
        "environment": config.environment,
        "buildId": config.build_id,
        "stagingResourceGroupId": (
            f"/subscriptions/{config.subscription_id}/resourceGroups/"
            f"{config.staging_resource_group}"
        ),
        "galleryResourceGroupName": config.gallery_resource_group,
        "galleryName": config.gallery_name,
        "imageDefinitionName": config.image_definition_name,
        "galleryImageVersion": config.image_version,
        "sourceImageVersion": config.source_image_version,
        "sourceKernel": config.source_kernel,
        "amlfsVersion": config.amlfs_version,
        "amlfsPackageVersion": config.amlfs_package_version,
        "nextflowVersion": config.nextflow_version,
        "nextflowSha256": config.nextflow_sha256,
        "nextflowUrl": config.nextflow_url,
        "azcopyVersion": config.azcopy_version,
        "azcopySha256": config.azcopy_sha256,
        "azcopyUrl": config.azcopy_url,
        "repositoryUrl": config.repository_url,
        "repositoryCommit": config.repository_commit,
        "repositoryPath": config.repository_path,
        "slurmPartition": config.slurm_partition,
        "buildVmSize": config.build_vm_size,
        "deployImageTemplate": str(deploy_image_template).lower(),
    }
    return [f"{key}={value}" for key, value in values.items()]


def _validation_script(config: ImageBuildConfig) -> str:
    return f"""set -Eeuo pipefail
test "$(uname -r)" = "{config.source_kernel}"
mokutil --sb-state | grep -F "SecureBoot enabled"
test -n "$(modinfo -F signer lustre)"
test "$(modinfo -F sig_id lustre)" = "PKCS#7"
test "$(modinfo -F vermagic lustre | cut -d ' ' -f 1)" = "{config.source_kernel}"
lustre_module="$(modinfo -F filename lustre)"
test -f "$lustre_module"
dpkg-query -W -f='${{Status}}\n' \
  "kmod-lustre-client-{config.source_kernel}-{config.amlfs_version}" \
  | grep -Fx 'install ok installed'
sudo -n modprobe lustre
for tool in mount.lustre azcopy java nextflow python3 samtools mount mountpoint findmnt sha256sum find sort xargs; do
  command -v "$tool" >/dev/null
done
NXF_VER="{config.nextflow_version}" NXF_HOME=/opt/nextflow \
  nextflow -version | grep -F "{config.nextflow_version}"
azcopy login --help | grep -q -- '--identity'
test -d "{config.repository_path}/workflows"
test "$(git -C "{config.repository_path}" rev-parse HEAD)" = "{config.repository_commit}"
grep -Fq 'SLURM_LUSTRE_WORKDIR is required' "{config.repository_path}/workflows/conf/slurm.config"
grep -Fq 'docker.enabled = false' "{config.repository_path}/workflows/conf/slurm.config"
! grep -Fq 'AZURE_BATCH_ACR_LOGIN_SERVER' "{config.repository_path}/workflows/conf/slurm.config"
grep -Fq -- '--reference-manifest-sha256' "{config.repository_path}/scripts/run_nextflow_secondary_pipeline.py"
systemctl is-active --quiet walinuxagent
systemctl is-active --quiet munge
systemctl is-active --quiet slurmctld
systemctl is-active --quiet slurmd
sinfo -h -p "{config.slurm_partition}" -o '%P|%a|%D' | grep -F "{config.slurm_partition}"
sudo -n true
sudo -n mount --help >/dev/null
sudo -n mkdir -p /mnt/amlfs
sudo -n chown "$(id -u):$(id -g)" /mnt/amlfs
test ! -e /var/lib/dkms/lustre-client
! command -v docker >/dev/null
python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path("/etc/genomics-variant-accelerator/image-manifest.json").read_text())
assert manifest["amlfs_install_method"] == "prebuilt-kmod"
assert manifest["secure_boot_required"] is True
assert manifest["vtpm_required"] is True
print(json.dumps({{
    "interface": "private-slurm-image",
    "secure_boot": "enabled",
    "vtpm": "enabled",
    "kernel": manifest["kernel"],
    "amlfs_client": manifest["amlfs_client"],
    "amlfs_install_method": manifest["amlfs_install_method"],
    "lustre_module": "{config.amlfs_package_version}/{config.amlfs_version}",
    "nextflow": manifest["nextflow"],
    "repository_commit": manifest["repository_commit"],
    "repository_path": manifest["repository_path"],
    "slurm_partition": manifest["slurm_partition"],
}}, sort_keys=True))
PY
"""


def run_build(config: ImageBuildConfig) -> dict[str, Any]:
    validate_config(config)
    _source_preflight(config)
    image_validated = False
    image_build_started = False
    build_error: Exception | None = None
    result: dict[str, Any] | None = None
    evidence: dict[str, Any] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "location": config.location,
        "image_version_id": config.image_version_id,
        "source_image_version": config.source_image_version,
        "source_kernel": config.source_kernel,
        "amlfs_install_method": "prebuilt-kmod",
        "secure_boot": True,
        "vtpm": True,
    }
    try:
        _ensure_group(
            config, config.gallery_resource_group, IMAGE_COMPONENT, retain=True
        )
        _az(
            config, "deployment", "group", "create",
            "--resource-group", config.gallery_resource_group,
            "--name", f"gallery-{config.build_id}",
            "--template-file", str(GALLERY_TEMPLATE),
            "--parameters",
            f"location={config.location}",
            f"galleryName={config.gallery_name}",
            f"imageDefinitionName={config.image_definition_name}",
            f"environment={config.environment}",
            "-o", "none", error="Gallery deployment failed",
        )
        if _image_version_count(config) != 0:
            raise RuntimeError(
                "Refusing to replace or reuse an existing gallery image version."
            )
        _ensure_group(config, config.build_resource_group, BUILD_COMPONENT)
        _ensure_group(config, config.staging_resource_group, BUILD_COMPONENT)
        _ensure_group(config, config.validation_resource_group, BUILD_COMPONENT)
        deployment = json.loads(_az(
            config, "deployment", "group", "create",
            "--resource-group", config.build_resource_group,
            "--name", f"builder-{config.build_id}",
            "--template-file", str(BUILDER_TEMPLATE),
            "--parameters", *_builder_parameters(
                config, deploy_image_template=False
            ),
            "-o", "json", error="Image Builder deployment failed",
        ))
        outputs = deployment["properties"]["outputs"]
        identity_id = outputs["identityId"]["value"]
        principal_id = _az(
            config, "identity", "show", "--ids", identity_id,
            "--query", "principalId", "-o", "tsv",
            error="Could not resolve Image Builder identity",
        ).strip()
        _az(
            config, "role", "assignment", "create",
            "--assignee-object-id", principal_id,
            "--assignee-principal-type", "ServicePrincipal",
            "--role", GALLERY_PUBLISHER_ROLE,
            "--scope", config.image_definition_id,
            "-o", "none", error="Could not grant gallery publication",
        )
        _az(
            config, "role", "assignment", "create",
            "--assignee-object-id", principal_id,
            "--assignee-principal-type", "ServicePrincipal",
            "--role", CONTRIBUTOR_ROLE,
            "--scope", (
                f"/subscriptions/{config.subscription_id}/resourceGroups/"
                f"{config.staging_resource_group}"
            ),
            "-o", "none", error="Could not grant staging resource-group access",
        )
        deployment = json.loads(_az(
            config, "deployment", "group", "create",
            "--resource-group", config.build_resource_group,
            "--name", f"builder-{config.build_id}",
            "--template-file", str(BUILDER_TEMPLATE),
            "--parameters", *_builder_parameters(
                config, deploy_image_template=True
            ),
            "-o", "json", error="Image Builder template deployment failed",
        ))
        outputs = deployment["properties"]["outputs"]
        template_name = outputs["imageTemplateName"]["value"]
        last_error = ""
        for attempt in range(6):
            try:
                _az(
                    config, "image", "builder", "run",
                    "--resource-group", config.build_resource_group,
                    "--name", template_name,
                    "--no-wait", "-o", "none",
                    error="Image Builder run could not start",
                )
                image_build_started = True
                break
            except RuntimeError as error:
                last_error = str(error)
                if attempt == 5:
                    raise
                time.sleep(20 * (attempt + 1))
        else:
            raise RuntimeError(last_error)

        deadline = time.monotonic() + 7200
        while time.monotonic() < deadline:
            state = json.loads(_az(
                config, "image", "builder", "show",
                "--resource-group", config.build_resource_group,
                "--name", template_name,
                "--query", "lastRunStatus", "-o", "json",
                error="Could not read Image Builder status",
            ))
            run_state = state.get("runState")
            if run_state == "Succeeded":
                break
            if run_state in {"Failed", "Canceled", "PartiallySucceeded"}:
                raise RuntimeError(
                    "Image Builder failed: " + json.dumps(state, sort_keys=True)
                )
            time.sleep(30)
        else:
            raise RuntimeError("Image Builder exceeded the bounded 120-minute wait.")

        version = json.loads(_az(
            config, "sig", "image-version", "show",
            "--resource-group", config.gallery_resource_group,
            "--gallery-name", config.gallery_name,
            "--gallery-image-definition", config.image_definition_name,
            "--gallery-image-version", config.image_version,
            "-o", "json", error="Gallery image version was not created",
        ))
        tags = version.get("tags") or {}
        for key, value in (
            ("project", PROJECT),
            ("component", IMAGE_COMPONENT),
            ("environment", config.environment),
            ("buildId", config.build_id),
            ("amlfsInstall", "prebuilt-kmod"),
            ("secureBoot", "required"),
            ("vtpm", "required"),
        ):
            if tags.get(key) != value:
                raise RuntimeError(f"Gallery image version tag {key} is invalid.")

        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "validation_key"
            _run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
                error="Could not create temporary validation SSH key",
            )
            public_key = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()
            validation_tags = [
                f"{key}={value}"
                for key, value in _expected_group_tags(
                    config, BUILD_COMPONENT
                ).items()
            ]
            _az(
                config, "vm", "create",
                "--resource-group", config.validation_resource_group,
                "--name", f"vm-validate-{config.build_id}",
                "--location", config.location,
                "--image", config.image_version_id,
                "--size", config.validation_vm_size,
                "--admin-username", "azureuser",
                "--ssh-key-values", public_key,
                "--public-ip-address", "",
                "--nsg", "",
                "--subnet", outputs["buildSubnetId"]["value"],
                "--security-type", "TrustedLaunch",
                "--enable-secure-boot", "true",
                "--enable-vtpm", "true",
                "--tags", *validation_tags,
                "-o", "none", error="Validation VM deployment failed",
            )
        vm_name = f"vm-validate-{config.build_id}"
        security_before = json.loads(_az(
            config, "vm", "show", "-g", config.validation_resource_group,
            "-n", vm_name, "--query", "securityProfile", "-o", "json",
            error="Could not inspect validation VM security profile",
        ))
        if security_before != {
            "securityType": "TrustedLaunch",
            "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True},
        }:
            raise RuntimeError("Validation VM security profile is not exact Trusted Launch.")
        invocation = json.loads(_az(
            config, "vm", "run-command", "invoke",
            "-g", config.validation_resource_group, "-n", vm_name,
            "--command-id", "RunShellScript",
            "--scripts", _validation_script(config),
            "-o", "json", error="Image interface validation failed",
        ))
        message = "\n".join(item.get("message", "") for item in invocation.get("value", []))
        marker = next(
            (line for line in message.splitlines() if '"interface": "private-slurm-image"' in line),
            None,
        )
        if marker is None:
            raise RuntimeError("Validation output did not contain the interface evidence.")
        security_after = json.loads(_az(
            config, "vm", "show", "-g", config.validation_resource_group,
            "-n", vm_name, "--query", "securityProfile", "-o", "json",
            error="Could not re-check validation VM security profile",
        ))
        if security_after != security_before:
            raise RuntimeError("Validation changed the VM security profile.")
        evidence["interface"] = json.loads(marker)
        evidence["security_profile_unchanged"] = True
        evidence["validated"] = True
        image_validated = True
        result = evidence
    except Exception as error:
        build_error = error
    finally:
        cleanup_errors: list[str] = []
        if not image_validated and image_build_started:
            try:
                _delete_owned_image_version(config)
            except Exception as error:
                cleanup_errors.append(str(error))
        for group_name in (
            config.validation_resource_group,
            config.build_resource_group,
            config.staging_resource_group,
        ):
            try:
                _delete_owned_group(config, group_name, BUILD_COMPONENT)
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            cleanup_detail = "; ".join(cleanup_errors)
            if build_error is not None:
                raise RuntimeError(
                    f"{build_error}; cleanup also failed: {cleanup_detail}"
                ) from build_error
            raise RuntimeError(f"Image-build cleanup failed: {cleanup_detail}")
    if build_error is not None:
        raise build_error
    if result is None:
        raise RuntimeError("Image build ended without a terminal result.")
    return result


def _config(arguments: argparse.Namespace) -> ImageBuildConfig:
    return ImageBuildConfig(**{
        key: value for key, value in vars(arguments).items()
        if key not in {"action", "evidence_path"}
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("validate", "run"), default="validate")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--gallery-resource-group", required=True)
    parser.add_argument("--gallery-name", required=True)
    parser.add_argument("--image-definition-name", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--source-image-version", required=True)
    parser.add_argument("--source-kernel", required=True)
    parser.add_argument("--amlfs-version", required=True)
    parser.add_argument("--amlfs-package-version", required=True)
    parser.add_argument("--nextflow-version", required=True)
    parser.add_argument("--nextflow-sha256", required=True)
    parser.add_argument("--nextflow-url", required=True)
    parser.add_argument("--azcopy-version", required=True)
    parser.add_argument("--azcopy-sha256", required=True)
    parser.add_argument("--azcopy-url", required=True)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--repository-path", default="/opt/genomics-variant-analytics")
    parser.add_argument("--slurm-partition", default="debug")
    parser.add_argument("--build-vm-size", default="Standard_D4s_v7")
    parser.add_argument("--validation-vm-size", default="Standard_D4s_v7")
    parser.add_argument("--evidence-path", type=Path)
    args = parser.parse_args(argv)
    try:
        config = _config(args)
        report = validate_config(config)
        if args.action == "run":
            report = run_build(config)
        if args.evidence_path:
            args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            args.evidence_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Private Slurm image rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
