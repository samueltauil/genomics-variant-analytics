"""Single-campaign Slurm/AMLFS orchestration with managed-identity Blob staging.

The live path is deliberately explicit and fail-closed. It validates the
workflow/reference pairing before creating resources, deploys only into a
campaign-tagged resource group, executes the worker through Azure VM run
command, and removes the group only after the worker reports verified copy-out.
Local validation never contacts Azure or provisions resources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from scripts.secondary_pipeline import generate_demo_sample
from scripts.validate_submission import validate_request_compatibility


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "hpc-campaign.bicep"
COMPATIBILITY = ROOT / "workflows" / "reference-compatibility.json"
PROJECT_TAG = "genomics-variant-accelerator"
COMPONENT_TAG = "hpc-campaign"
CAMPAIGN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,23}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CampaignConfig:
    subscription_id: str
    location: str
    campaign_id: str
    campaign_owner: str
    admin_public_key: str
    reference_build: str
    reference_version: str
    reference_manifest_sha256: str
    slurm_image_id: str
    staging_identity_resource_id: str
    staging_identity_client_id: str
    staging_identity_principal_id: str
    staging_storage_account_id: str
    staging_storage_account_name: str
    staging_environment: str
    input_container_name: str = "healthcare"
    output_container_name: str = "healthcare"
    log_container_name: str = "healthcare"
    input_prefix: str = "Process/HPC/Input"
    output_prefix: str = "Process/HPC/Output"
    log_prefix: str = "Inventory/HPC/Logs"
    repository_path: str = "/opt/genomics-variant-analytics"
    slurm_partition: str = "debug"
    expires_in_days: int = 1

    @property
    def resource_group(self) -> str:
        return f"rg-genomics-hpc-{self.campaign_id}"


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


def validate_config(config: CampaignConfig) -> dict[str, Any]:
    _text(config.subscription_id, "subscription_id")
    _text(config.location, "location")
    if not CAMPAIGN_PATTERN.fullmatch(config.campaign_id):
        raise ValueError(
            "campaign_id must be 3-24 lowercase letters, digits, or hyphens, "
            "starting with a letter or digit."
        )
    _text(config.campaign_owner, "campaign_owner")
    if "\n" in config.campaign_owner or "\r" in config.campaign_owner:
        raise ValueError("campaign_owner must be a single line.")
    if not config.admin_public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
        raise ValueError("admin_public_key must be an SSH public key.")
    if not re.fullmatch(
        r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Compute/"
        r"galleries/[^/]+/images/[^/]+/versions/[^/]+",
        config.slurm_image_id,
        re.IGNORECASE,
    ):
        raise ValueError(
            "slurm_image_id must identify an explicit Azure Compute Gallery image version."
        )
    for resource_id, label, resource_type in (
        (config.staging_identity_resource_id, "staging_identity_resource_id",
         "Microsoft.ManagedIdentity/userAssignedIdentities"),
        (config.staging_storage_account_id, "staging_storage_account_id",
         "Microsoft.Storage/storageAccounts"),
    ):
        if f"/providers/{resource_type}/".lower() not in resource_id.lower():
            raise ValueError(f"{label} must identify {resource_type}.")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", config.staging_identity_client_id):
        raise ValueError("staging_identity_client_id must be a UUID.")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", config.staging_identity_principal_id):
        raise ValueError("staging_identity_principal_id must be a UUID.")
    if not re.fullmatch(r"[a-z0-9]{3,24}", config.staging_storage_account_name):
        raise ValueError("staging_storage_account_name must be a valid storage account name.")
    _text(config.staging_environment, "staging_environment")
    for name, label in (
        (config.input_container_name, "input_container_name"),
        (config.output_container_name, "output_container_name"),
        (config.log_container_name, "log_container_name"),
    ):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", name):
            raise ValueError(f"{label} must be a valid lowercase Blob container name.")
    for prefix, label in (
        (config.input_prefix, "input_prefix"),
        (config.output_prefix, "output_prefix"),
        (config.log_prefix, "log_prefix"),
    ):
        if (prefix.startswith("/") or prefix.endswith("/") or ".." in prefix.split("/")
                or not all(re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in prefix.split("/"))):
            raise ValueError(f"{label} must be a safe relative Blob prefix.")
    durable_paths = {
        (config.input_container_name, config.input_prefix),
        (config.output_container_name, config.output_prefix),
        (config.log_container_name, config.log_prefix),
    }
    if len(durable_paths) != 3:
        raise ValueError("Input, output, and log Blob locations must be distinct.")
    if not config.repository_path.startswith("/"):
        raise ValueError("repository_path must be an absolute POSIX path.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", config.slurm_partition):
        raise ValueError("slurm_partition contains unsupported characters.")
    if not 1 <= config.expires_in_days <= 7:
        raise ValueError("expires_in_days must be between 1 and 7.")
    if not DIGEST_PATTERN.fullmatch(config.reference_manifest_sha256):
        raise ValueError(
            "reference_manifest_sha256 must be an explicit 64-character lowercase SHA-256."
        )

    compatibility = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))
    request = {
        "run_id": f"SYN-HPC-{config.campaign_id}",
        "workflow_id": "genomics-secondary-analysis",
        "workflow_version": "v0.1.0",
        "reference_build": _text(config.reference_build, "reference_build"),
        "reference_version": _text(config.reference_version, "reference_version"),
        "reference_manifest_sha256": config.reference_manifest_sha256,
        "references": [{
            "type": "genome",
            "name": config.reference_build,
            "version": config.reference_version,
        }],
    }
    resolved = validate_request_compatibility(request, compatibility)
    return {
        "campaign_id": config.campaign_id,
        "resource_group": config.resource_group,
        "workflow_id": request["workflow_id"],
        "workflow_version": request["workflow_version"],
        "reference_build": config.reference_build,
        "reference_version": config.reference_version,
        "reference_manifest_sha256": config.reference_manifest_sha256,
        "resolved_references": [list(item) for item in sorted(resolved)],
        "mode": "local-static-validation",
        "azure_resources_created": False,
    }


def build_synthetic_bundle(directory: Path, config: CampaignConfig) -> dict[str, Any]:
    """Generate metadata and tiny synthetic sequence files only in caller scratch."""
    validate_config(config)
    directory = Path(directory)
    sample = generate_demo_sample(directory, sample_id="SYN-SAMPLE-0001", read_count=4)
    if sample["reference_build"] != config.reference_build:
        raise ValueError("Generated reference build does not match the declared build.")
    if sample["reference_version"] != config.reference_version:
        raise ValueError("Generated reference version does not match the declared version.")

    files = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            files[path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": 1,
        "campaign_id": config.campaign_id,
        "sample_id": sample["sample_id"],
        "reference_build": config.reference_build,
        "reference_version": config.reference_version,
        "reference_manifest_sha256": config.reference_manifest_sha256,
        "synthetic": True,
        "files": files,
    }
    (directory / "campaign-input-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


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
            stdin=subprocess.DEVNULL,
        )
    else:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{error}: {detail}")
    return completed.stdout


def _az(config: CampaignConfig, *arguments: str, error: str) -> str:
    return _run(
        ["az", *arguments, "--subscription", config.subscription_id],
        error=error,
    )


def cloud_preflight(config: CampaignConfig) -> None:
    validate_config(config)
    for executable in ("az",):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Required tool is unavailable: {executable}.")
    _az(config, "account", "show", "-o", "none", error="Azure subscription is unavailable")
    image = json.loads(_az(
        config, "resource", "show", "--ids", config.slurm_image_id, "-o", "json",
        error="The explicitly selected private Slurm image is unavailable",
    ))
    definition_id = config.slurm_image_id.rsplit("/versions/", 1)[0]
    definition = json.loads(_az(
        config, "resource", "show", "--ids", definition_id,
        "--api-version", "2024-03-03", "-o", "json",
        error="The selected gallery image definition is unavailable",
    ))
    storage = json.loads(_az(
        config, "resource", "show", "--ids", config.staging_storage_account_id,
        "--api-version", "2025-01-01", "-o", "json",
        error="The explicitly selected staging storage account is unavailable",
    ))
    identity = json.loads(_az(
        config, "resource", "show", "--ids", config.staging_identity_resource_id,
        "--api-version", "2023-01-31", "-o", "json",
        error="The explicitly selected staging identity is unavailable",
    ))
    for resource, label in (
        (storage, "storage account"),
        (identity, "managed identity"),
        (image, "Slurm image"),
    ):
        tags = resource.get("tags") or {}
        if (tags.get("project") != PROJECT_TAG
                or tags.get("environment") != config.staging_environment):
            raise RuntimeError(
                f"Refusing {label} without matching accelerator project and environment tags."
            )
    features = {
        item.get("name"): item.get("value")
        for item in (definition.get("properties") or {}).get("features", [])
    }
    if (definition.get("properties") or {}).get("hyperVGeneration") != "V2":
        raise RuntimeError("Slurm image definition must be Hyper-V generation V2.")
    if features.get("SecurityType") != "TrustedLaunchSupported":
        raise RuntimeError("Slurm image definition must be TrustedLaunchSupported.")
    image_tags = image.get("tags") or {}
    for key, value in (
        ("component", "private-slurm-image"),
        ("amlfsInstall", "prebuilt-kmod"),
        ("secureBoot", "required"),
        ("vtpm", "required"),
    ):
        if image_tags.get(key) != value:
            raise RuntimeError(f"Slurm image tag {key} must equal {value}.")
    if storage.get("name") != config.staging_storage_account_name:
        raise RuntimeError("Staging storage account name does not match its resource id.")
    identity_properties = identity.get("properties") or {}
    if identity_properties.get("clientId", "").lower() != config.staging_identity_client_id.lower():
        raise RuntimeError("Staging identity client id does not match its resource id.")
    if identity_properties.get("principalId", "").lower() != config.staging_identity_principal_id.lower():
        raise RuntimeError("Staging identity principal id does not match its resource id.")
    properties = storage.get("properties") or {}
    if properties.get("allowSharedKeyAccess") is not False:
        raise RuntimeError("Staging storage must have shared-key access disabled.")
    if properties.get("publicNetworkAccess") != "Disabled":
        raise RuntimeError("Staging storage must have public network access disabled.")
    if properties.get("isHnsEnabled") is not True:
        raise RuntimeError("Staging storage must have hierarchical namespace enabled.")
    assignments = json.loads(_az(
        config, "role", "assignment", "list",
        "--assignee-object-id", config.staging_identity_principal_id,
        "--scope", config.staging_storage_account_id,
        "--include-inherited", "-o", "json",
        error="Could not verify staging identity storage authorization",
    ))
    allowed_roles = {
        "Storage Blob Data Contributor",
        "Storage Blob Data Owner",
    }
    if not any(item.get("roleDefinitionName") in allowed_roles for item in assignments):
        raise RuntimeError(
            "Staging identity requires Storage Blob Data Contributor or Owner on the staging account."
        )
    for container in set((
        config.input_container_name,
        config.output_container_name,
        config.log_container_name,
    )):
        _az(
            config, "resource", "show",
            "--ids", (
                f"{config.staging_storage_account_id}/blobServices/default/"
                f"containers/{container}"
            ),
            "--api-version", "2025-01-01", "-o", "none",
            error=f"Required durable campaign container is unavailable: {container}",
        )
    for namespace in ("Microsoft.Compute", "Microsoft.Network", "Microsoft.Storage",
                      "Microsoft.StorageCache", "Microsoft.ManagedIdentity"):
        state = _az(
            config, "provider", "show", "--namespace", namespace,
            "--query", "registrationState", "-o", "tsv",
            error=f"Could not inspect provider {namespace}",
        ).strip()
        if state != "Registered":
            raise RuntimeError(f"Provider {namespace} is {state!r}; Registered is required.")
    _run(
        ["az", "bicep", "build", "--file", str(TEMPLATE), "--stdout"],
        error="HPC campaign Bicep build failed",
    )


def _expected_tags(config: CampaignConfig) -> dict[str, str]:
    return {
        "project": PROJECT_TAG,
        "component": COMPONENT_TAG,
        "campaignId": config.campaign_id,
        "campaignOwner": config.campaign_owner,
    }


def _assert_group_owned(config: CampaignConfig) -> bool:
    exists = _az(
        config, "group", "exists", "--name", config.resource_group, "-o", "tsv",
        error="Could not test campaign resource-group existence",
    ).strip().lower()
    if exists == "false":
        return False
    group = json.loads(_az(
        config, "group", "show", "--name", config.resource_group, "-o", "json",
        error="Could not inspect existing campaign resource group",
    ))
    tags = group.get("tags") or {}
    mismatches = {
        key: {"found": tags.get(key), "required": value}
        for key, value in _expected_tags(config).items()
        if tags.get(key) != value
    }
    if mismatches:
        raise RuntimeError(
            "Refusing to reuse campaign resource group with mismatched ownership tags: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return True


def _worker_script(config: CampaignConfig, outputs: dict[str, Any]) -> str:
    account = outputs["storageAccountName"]["value"]
    input_container = outputs["inputContainerName"]["value"]
    output_container = outputs["outputContainerName"]["value"]
    log_container = outputs["logContainerName"]["value"]
    identity_client_id = outputs["identityClientId"]["value"]
    mount_address = outputs["amlfsMountAddress"]["value"]
    run_id = f"SYN-HPC-{config.campaign_id}"
    q = shlex.quote
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

campaign_id={q(config.campaign_id)}
run_id={q(run_id)}
repo={q(config.repository_path)}
reference_build={q(config.reference_build)}
reference_version={q(config.reference_version)}
reference_manifest_sha256={q(config.reference_manifest_sha256)}
storage_account={q(account)}
identity_client_id={q(identity_client_id)}
mount_address={q(mount_address)}
mount_path=/mnt/amlfs
campaign_root="$mount_path/campaigns/$campaign_id"
input_path="$campaign_root/input"
work_path="$campaign_root/work"
result_path="$campaign_root/results"
log_path="$campaign_root/logs"
seed_path="/var/tmp/$campaign_id-seed"
verify_path="/var/tmp/$campaign_id-verify"
input_uri="https://$storage_account.blob.core.windows.net/{input_container}/{config.input_prefix}/$campaign_id"
output_uri="https://$storage_account.blob.core.windows.net/{output_container}/{config.output_prefix}/$campaign_id"
log_uri="https://$storage_account.blob.core.windows.net/{log_container}/{config.log_prefix}/$campaign_id"

for tool in azcopy python3 java nextflow sbatch sinfo mount mount.lustre mountpoint \
  findmnt sha256sum find sort xargs samtools sudo; do
  command -v "$tool" >/dev/null || {{ echo "missing required tool: $tool" >&2; exit 20; }}
done
test -d "$repo/workflows" || {{ echo "repository checkout missing at $repo" >&2; exit 21; }}
test "$reference_manifest_sha256" != "" || {{ echo "reference manifest digest missing" >&2; exit 22; }}
sinfo -h -p {q(config.slurm_partition)} >/dev/null

sudo mkdir -p "$mount_path"
if ! mountpoint -q "$mount_path"; then
  sudo mount -t lustre -o noatime,flock "$mount_address@tcp:/lustrefs" "$mount_path"
fi
test "$(findmnt -n -o FSTYPE "$mount_path")" = "lustre"
sudo mkdir -p "$campaign_root"
sudo chown -R "$(id -u):$(id -g)" "$campaign_root"
mkdir -p "$input_path" "$work_path" "$result_path" "$log_path" "$seed_path" "$verify_path"

export AZCOPY_AUTO_LOGIN_TYPE=MSI
export AZCOPY_MSI_CLIENT_ID="$identity_client_id"
export SLURM_PARTITION={q(config.slurm_partition)}
export SLURM_LUSTRE_WORKDIR="$work_path/nextflow-work"
azcopy login --identity --identity-client-id "$identity_client_id" >/dev/null

cleanup_seed() {{ rm -rf "$seed_path"; }}
copy_failure_logs() {{
  set +e
  cp "$work_path/.nextflow.log" "$log_path/" 2>/dev/null
  printf '%s\n' "failed" > "$log_path/terminal-state.txt"
  azcopy copy "$log_path/*" "$log_uri" --recursive=true --overwrite=true >/dev/null
}}
trap 'copy_failure_logs' ERR

cd "$seed_path"
python3 "$repo/workflows/bin/generate_demo_sample.py" \
  --reference-build "$reference_build" \
  --reference-version "$reference_version" \
  --sample-id SYN-SAMPLE-0001 \
  --read-count 4
sha256sum ./* > SHA256SUMS
python3 - "$campaign_id" "$reference_build" "$reference_version" "$reference_manifest_sha256" <<'PY'
import json, sys
from pathlib import Path
campaign_id, build, version, digest = sys.argv[1:]
Path("campaign-input-manifest.json").write_text(json.dumps({{
    "schema_version": 1,
    "campaign_id": campaign_id,
    "sample_id": "SYN-SAMPLE-0001",
    "reference_build": build,
    "reference_version": version,
    "reference_manifest_sha256": digest,
    "synthetic": True,
}}, sort_keys=True, indent=2) + "\\n")
PY
azcopy copy "$seed_path/*" "$input_uri" --recursive=true --overwrite=false
cleanup_seed

azcopy copy "$input_uri/*" "$input_path" --recursive=true
cd "$input_path"
sha256sum -c SHA256SUMS

cd "$work_path"
python3 "$repo/scripts/run_nextflow_secondary_pipeline.py" \
  --run-id "$run_id" \
  --work-dir "$work_path" \
  --provenance-db "$log_path/provenance.sqlite3" \
  --reference-build "$reference_build" \
  --reference-version "$reference_version" \
  --reference-manifest-sha256 "$reference_manifest_sha256" \
  --profile slurm \
  --input-bundle-dir "$input_path" \
  --input-uri-base "$input_uri" \
  --output-uri-base "$output_uri" \
  --log-uri "$log_uri/.nextflow.log" \
  --execution-target slurm \
  --compute-pool {q(config.slurm_partition)} \
  > "$log_path/launcher-report.json" 2> "$log_path/launcher.stderr.log"

test -d "$work_path/results"
cp -a "$work_path/results/." "$result_path/"
cp "$work_path/.nextflow.log" "$log_path/"
printf '%s\n' "succeeded" > "$log_path/terminal-state.txt"
cd "$result_path"
find . -type f ! -name OUTPUT-SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > OUTPUT-SHA256SUMS
test -s OUTPUT-SHA256SUMS

azcopy copy "$result_path/*" "$output_uri" --recursive=true --overwrite=false
azcopy copy "$log_path/*" "$log_uri" --recursive=true --overwrite=true
azcopy copy "$output_uri/*" "$verify_path" --recursive=true
cd "$verify_path"
sha256sum -c OUTPUT-SHA256SUMS
printf '%s\n' "CAMPAIGN_COPY_OUT_VERIFIED=1"
"""


def _delete_owned_group(config: CampaignConfig) -> None:
    if not _assert_group_owned(config):
        return
    _az(
        config, "group", "delete", "--name", config.resource_group, "--yes",
        error="Guarded campaign teardown could not start",
    )
    exists = _az(
        config, "group", "exists", "--name", config.resource_group, "-o", "tsv",
        error="Could not verify campaign teardown",
    ).strip().lower()
    if exists != "false":
        raise RuntimeError(
            f"Campaign resource group {config.resource_group} still exists after teardown."
        )


def run_campaign(config: CampaignConfig) -> dict[str, Any]:
    cloud_preflight(config)
    existed = _assert_group_owned(config)
    expires_on = (date.today() + timedelta(days=config.expires_in_days)).isoformat()
    campaign_error: Exception | None = None
    result: dict[str, Any] | None = None
    try:
        if not existed:
            tags = _expected_tags(config) | {
                "lifecycle": "ephemeral",
                "expiresOn": expires_on,
            }
            tag_args = [f"{key}={value}" for key, value in tags.items()]
            _az(
                config, "group", "create", "--name", config.resource_group,
                "--location", config.location, "--tags", *tag_args, "-o", "none",
                error="Could not create campaign-owned resource group",
            )

        deployment = json.loads(_az(
            config, "deployment", "group", "create",
            "--resource-group", config.resource_group,
            "--name", f"hpc-{config.campaign_id}",
            "--template-file", str(TEMPLATE),
            "--parameters",
            f"location={config.location}",
            f"campaignId={config.campaign_id}",
            f"campaignOwner={config.campaign_owner}",
            f"expiresOn={expires_on}",
            f"adminPublicKey={config.admin_public_key}",
            f"slurmSourceImageId={config.slurm_image_id}",
            f"stagingIdentityResourceId={config.staging_identity_resource_id}",
            f"stagingIdentityClientId={config.staging_identity_client_id}",
            f"stagingStorageAccountId={config.staging_storage_account_id}",
            f"stagingStorageAccountName={config.staging_storage_account_name}",
            f"inputContainerName={config.input_container_name}",
            f"outputContainerName={config.output_container_name}",
            f"logContainerName={config.log_container_name}",
            "-o", "json",
            error="HPC campaign deployment failed",
        ))
        outputs = deployment["properties"]["outputs"]
        worker = _worker_script(config, outputs)
        invocation = _az(
            config, "vm", "run-command", "invoke",
            "--resource-group", config.resource_group,
            "--name", outputs["slurmVmName"]["value"],
            "--command-id", "RunShellScript",
            "--scripts", worker,
            "-o", "json",
            error="Campaign worker failed",
        )

        if "CAMPAIGN_COPY_OUT_VERIFIED=1" not in invocation:
            raise RuntimeError("Campaign worker returned without verified copy-out.")
        result = {
            "campaign_id": config.campaign_id,
            "resource_group": config.resource_group,
            "terminal_state": "succeeded",
            "copy_out_verified": True,
            "teardown_started": True,
            "reference_build": config.reference_build,
            "reference_version": config.reference_version,
            "reference_manifest_sha256": config.reference_manifest_sha256,
        }
    except Exception as error:
        campaign_error = error
    finally:
        try:
            _delete_owned_group(config)
        except Exception as cleanup_error:
            if campaign_error is not None:
                raise RuntimeError(
                    f"{campaign_error}; guarded campaign teardown also failed: "
                    f"{cleanup_error}"
                ) from cleanup_error
            raise

    if campaign_error is not None:
        raise campaign_error
    if result is None:
        raise RuntimeError("Campaign ended without a terminal result.")
    return result


def _config(arguments: argparse.Namespace) -> CampaignConfig:
    return CampaignConfig(
        subscription_id=arguments.subscription_id,
        location=arguments.location,
        campaign_id=arguments.campaign_id,
        campaign_owner=arguments.campaign_owner,
        admin_public_key=arguments.admin_public_key,
        reference_build=arguments.reference_build,
        reference_version=arguments.reference_version,
        reference_manifest_sha256=arguments.reference_manifest_sha256,
        slurm_image_id=arguments.slurm_image_id,
        staging_identity_resource_id=arguments.staging_identity_resource_id,
        staging_identity_client_id=arguments.staging_identity_client_id,
        staging_identity_principal_id=arguments.staging_identity_principal_id,
        staging_storage_account_id=arguments.staging_storage_account_id,
        staging_storage_account_name=arguments.staging_storage_account_name,
        staging_environment=arguments.staging_environment,
        input_container_name=arguments.input_container_name,
        output_container_name=arguments.output_container_name,
        log_container_name=arguments.log_container_name,
        input_prefix=arguments.input_prefix,
        output_prefix=arguments.output_prefix,
        log_prefix=arguments.log_prefix,
        repository_path=arguments.repository_path,
        slurm_partition=arguments.slurm_partition,
        expires_in_days=arguments.expires_in_days,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("validate", "run"), default="validate")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--campaign-owner", required=True)
    parser.add_argument("--admin-public-key", required=True)
    parser.add_argument("--reference-build", required=True)
    parser.add_argument("--reference-version", required=True)
    parser.add_argument("--reference-manifest-sha256", required=True)
    parser.add_argument("--slurm-image-id", required=True)
    parser.add_argument("--staging-identity-resource-id", required=True)
    parser.add_argument("--staging-identity-client-id", required=True)
    parser.add_argument("--staging-identity-principal-id", required=True)
    parser.add_argument("--staging-storage-account-id", required=True)
    parser.add_argument("--staging-storage-account-name", required=True)
    parser.add_argument("--staging-environment", required=True)
    parser.add_argument("--input-container-name", default="healthcare")
    parser.add_argument("--output-container-name", default="healthcare")
    parser.add_argument("--log-container-name", default="healthcare")
    parser.add_argument("--input-prefix", default="Process/HPC/Input")
    parser.add_argument("--output-prefix", default="Process/HPC/Output")
    parser.add_argument("--log-prefix", default="Inventory/HPC/Logs")
    parser.add_argument("--repository-path", default="/opt/genomics-variant-analytics")
    parser.add_argument("--slurm-partition", default="debug")
    parser.add_argument("--expires-in-days", type=int, default=1)
    parser.add_argument("--synthetic-bundle-dir", type=Path)
    arguments = parser.parse_args(argv)
    try:
        config = _config(arguments)
        report = validate_config(config)
        if arguments.synthetic_bundle_dir:
            report["synthetic_bundle"] = build_synthetic_bundle(
                arguments.synthetic_bundle_dir, config
            )
        if arguments.action == "run":
            report = run_campaign(config)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"HPC campaign rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
