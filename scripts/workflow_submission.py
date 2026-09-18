"""Workflow submission boundary with mandatory published-reference validation."""

import hashlib
import json
import re

from scripts.publish_reference import reference_path, validate_entry
from scripts.validate_submission import (
    digest,
    fields,
    text,
    unique_object,
    validate_request_compatibility,
)


MANIFEST_FIELDS = {
    "schema_version", "type", "name", "version", "published_at", "artifacts",
}
ARTIFACT_FIELDS = {"filename", "sha256", "size_bytes", "source"}


def _published_manifest(payload, expected):
    try:
        manifest = json.loads(payload, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Published reference manifest is not valid JSON: {error}") from error

    fields(manifest, MANIFEST_FIELDS, "Published reference manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported published reference manifest schema_version; expected 1.")

    entry = {field: manifest[field] for field in ("type", "name", "version")}
    validate_entry(entry)
    actual = tuple(entry[field] for field in ("type", "name", "version"))
    if actual != expected:
        raise ValueError(
            f"Published reference manifest identity {actual} does not match requested {expected}."
        )
    text(manifest["published_at"], "published_at")
    if not isinstance(manifest["artifacts"], list) or not manifest["artifacts"]:
        raise ValueError("Published reference manifest must contain at least one artifact.")

    artifacts = []
    filenames = set()
    for artifact in manifest["artifacts"]:
        fields(artifact, ARTIFACT_FIELDS, "Published reference artifact")
        filename = text(artifact["filename"], "filename")
        reference_path(entry, filename)
        if filename in filenames:
            raise ValueError(f"Duplicate artifact filename in published manifest: {filename}.")
        filenames.add(filename)
        checksum = text(artifact["sha256"], "sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Published reference artifact sha256 must be 64 lowercase hex characters.")
        if type(artifact["size_bytes"]) is not int or artifact["size_bytes"] < 0:
            raise ValueError("Published reference artifact size_bytes must be a nonnegative integer.")
        if artifact["source"] is not None:
            text(artifact["source"], "source")
        artifacts.append(artifact)
    return entry, artifacts


def _resolve_reference(zone, key):
    entry = dict(zip(("type", "name", "version"), key))
    payload = zone.get_manifest_bytes(entry)
    if payload is None:
        raise ValueError(f"Declared reference version unavailable: {key}; no fallback permitted.")
    resolved_entry, artifacts = _published_manifest(payload, key)
    return {
        **resolved_entry,
        "manifest_uri": zone.uri(entry),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "artifacts": [
            {
                "filename": artifact["filename"],
                "uri": zone.uri(entry, artifact["filename"]),
                "sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"],
            }
            for artifact in artifacts
        ],
    }


def prepare_workflow_submission(request, compatibility, reference_zone):
    """Resolve and pin every compatible published reference before allocation."""
    requested = validate_request_compatibility(request, compatibility)
    references = [_resolve_reference(reference_zone, key) for key in sorted(requested)]
    genome = next(reference for reference in references if reference["type"] == "genome")
    return {
        "schema_version": 1,
        "run_id": request["run_id"],
        "workflow_id": request["workflow_id"],
        "workflow_version": request["workflow_version"],
        "reference_build": genome["name"],
        "reference_version": genome["version"],
        "references": references,
        "compatibility_manifest_sha256": digest(compatibility),
    }


def submit_workflow(request, compatibility, reference_zone, allocate):
    """Validate and pin the submission before invoking the compute allocator."""
    prepared = prepare_workflow_submission(request, compatibility, reference_zone)
    return allocate(prepared)
