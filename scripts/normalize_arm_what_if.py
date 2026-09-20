"""Fail-closed normalization of known ARM what-if prediction noise."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


ALLOWED_MODIFICATIONS = {
    "Microsoft.Compute/virtualMachines": {
        "properties.storageProfile.osDisk.diskSizeGB",
        "properties.storageProfile.osDisk.managedDisk.storageAccountType",
    },
    "Microsoft.ContainerRegistry/registries": {
        "properties.anonymousPullEnabled",
        "properties.encryption",
        "properties.policies.azureADAuthenticationAsArmPolicy",
    },
    "Microsoft.DataFactory/factories": {"properties.trustModeClaimForMi"},
    "Microsoft.DataFactory/factories/integrationRuntimes": {
        "properties.managedVirtualNetwork.id"
    },
    "Microsoft.DataFactory/factories/managedVirtualNetworks": {"properties"},
    "Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints": {
        "properties.fqdns",
        "properties.ipAddress",
        "properties.resourceId",
    },
    "Microsoft.DataFactory/factories/pipelines": {"properties.lastPublishTime"},
    "Microsoft.Network/networkInterfaces": {
        "kind",
        "properties.allowPort25Out",
        "properties.auxiliaryMode",
        "properties.auxiliarySku",
        "properties.disableTcpStateTracking",
        "properties.ipConfigurations",
    },
    "Microsoft.Network/privateDnsZones/virtualNetworkLinks": {
        "properties.resolutionPolicy"
    },
    "Microsoft.Network/privateEndpoints": {
        "properties.isIPv6EnabledPrivateEndpoint",
        "properties.subnet.id",
    },
    "Microsoft.Network/privateEndpoints/privateDnsZoneGroups": {
        "properties.privateDnsZoneConfigs"
    },
    "Microsoft.Network/virtualNetworks": {
        "properties.privateEndpointVNetPolicies",
        "properties.subnets",
    },
    "Microsoft.Storage/storageAccounts/blobServices": {
        "properties.deleteRetentionPolicy.allowPermanentDelete"
    },
    "Microsoft.Storage/storageAccounts/blobServices/containers": {
        "properties.defaultEncryptionScope",
        "properties.denyEncryptionScopeOverride",
    },
    "Microsoft.Storage/storageAccounts/fileServices": {
        "properties.shareDeleteRetentionPolicy"
    },
    "Microsoft.Authorization/roleAssignments": {
        "properties.principalId",
        "properties.principalType",
    },
}

ALLOWED_RUNTIME_ROLE_IDS = {
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
    "69566ab7-960f-475b-8e7c-b3118f30c6bd",
    "8311e382-0749-4cb8-b61a-304f252e45ec",
    "a235d3ee-5935-4cfb-8cc5-a3303ad5995e",
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
}


def _resource_type(change: Mapping[str, Any]) -> str:
    for side in ("after", "before"):
        value = change.get(side)
        if isinstance(value, Mapping) and isinstance(value.get("type"), str):
            return value["type"]
    return ""


def normalize_what_if(payload: Mapping[str, Any]) -> dict[str, Any]:
    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise ValueError("ARM what-if payload must contain a changes list.")

    normalized = []
    effective = []
    for change in changes:
        if not isinstance(change, Mapping):
            raise ValueError("ARM what-if changes must be objects.")
        change_type = change.get("changeType")
        resource_id = str(change.get("resourceId", ""))
        resource_type = _resource_type(change)
        if change_type in {"NoChange", "Ignore"}:
            continue
        if change_type == "Unsupported":
            role_ids = set(
                re.findall(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    resource_id,
                    flags=re.IGNORECASE,
                )
            )
            supported_noise = (
                "Microsoft.Authorization/roleAssignments" in resource_id
                and "extensionResourceId(" in resource_id
                and "reference(" in resource_id
                and len(role_ids & ALLOWED_RUNTIME_ROLE_IDS) == 1
            )
            target = normalized if supported_noise else effective
            target.append(
                {
                    "changeType": change_type,
                    "resourceId": resource_id,
                    "reason": "runtime-managed-identity-role-assignment"
                    if supported_noise
                    else "unrecognized-unsupported-resource",
                }
            )
            continue
        if change_type != "Modify":
            effective.append(
                {
                    "changeType": change_type,
                    "resourceId": resource_id,
                    "reason": "resource-change",
                }
            )
            continue

        deltas = change.get("delta")
        if not isinstance(deltas, list) or not deltas:
            effective.append(
                {
                    "changeType": change_type,
                    "resourceId": resource_id,
                    "reason": "modify-without-inspectable-delta",
                }
            )
            continue
        allowed_paths = ALLOWED_MODIFICATIONS.get(resource_type, set())
        unknown_paths = sorted(
            {
                str(delta.get("path", ""))
                for delta in deltas
                if not isinstance(delta, Mapping)
                or delta.get("path") not in allowed_paths
            }
        )
        target = effective if unknown_paths else normalized
        target.append(
            {
                "changeType": change_type,
                "resourceId": resource_id,
                "resourceType": resource_type,
                "paths": sorted(
                    str(delta.get("path", ""))
                    for delta in deltas
                    if isinstance(delta, Mapping)
                ),
                "reason": "unrecognized-property-paths"
                if unknown_paths
                else "documented-server-or-runtime-properties",
                "unknownPaths": unknown_paths,
            }
        )

    return {
        "schemaVersion": 1,
        "effectiveChangeCount": len(effective),
        "normalizedNoiseCount": len(normalized),
        "noEffectiveChanges": not effective,
        "effectiveChanges": effective,
        "normalizedNoise": normalized,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = normalize_what_if(payload)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if report["noEffectiveChanges"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ARM what-if normalization failed: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
