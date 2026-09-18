import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


REFERENCE_TYPES = {
    "genome", "gene-annotation", "transcript-annotation",
    "clinical-knowledge", "population-reference",
}


def fields(value, expected, label):
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(expected))}.")


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace.")
    return value


def reference_key(reference, artifact=False):
    expected = {"type", "name", "version"}
    fields(reference, expected | ({"uri", "sha256"} if artifact else set()), "Reference")
    key = tuple(text(reference[field], field) for field in ("type", "name", "version"))
    if key[0] not in REFERENCE_TYPES:
        raise ValueError(f"Unknown reference type: {key[0]}.")
    if artifact:
        uri = urlsplit(text(reference["uri"], "uri"))
        if (uri.scheme not in {"file", "https", "abfss"} or not uri.path
                or uri.query or uri.fragment or (uri.scheme != "file" and not uri.netloc)
                or uri.password or (uri.scheme == "https" and uri.username)):
            raise ValueError("Reference URI must be a credential-free file, HTTPS or ABFSS location.")
        if not re.fullmatch(r"[0-9a-f]{64}", text(reference["sha256"], "sha256")):
            raise ValueError("Reference sha256 must be 64 lowercase hexadecimal characters.")
    return key


def reference_set(references):
    if not isinstance(references, list) or not references:
        raise ValueError("A reference set must be a nonempty array.")
    keys = [reference_key(reference) for reference in references]
    if len(set(keys)) != len(keys) or len({(key[0], key[1]) for key in keys}) != len(keys):
        raise ValueError("A reference set cannot contain duplicate entries or multiple versions of one entry.")
    if sum(key[0] == "genome" for key in keys) != 1:
        raise ValueError("A reference set must declare exactly one genome build and version.")
    return frozenset(keys)


def document(value, collection):
    fields(value, {"schema_version", collection}, collection)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported manifest schema_version; expected 1.")
    if not isinstance(value[collection], list) or not value[collection]:
        raise ValueError(f"{collection} must be a nonempty array.")
    return value[collection]


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_request_compatibility(request, compatibility):
    fields(
        request,
        {"run_id", "workflow_id", "workflow_version", "reference_build",
         "reference_version", "references"},
        "Submission",
    )
    for field in ("run_id", "workflow_id", "workflow_version", "reference_build",
                  "reference_version"):
        text(request[field], field)
    requested = reference_set(request["references"])
    genome = next(reference for reference in request["references"] if reference["type"] == "genome")
    workflows = {}
    for workflow in document(compatibility, "workflows"):
        fields(workflow, {"workflow_id", "workflow_version", "reference_sets"}, "Workflow")
        key = (text(workflow["workflow_id"], "workflow_id"), text(workflow["workflow_version"], "workflow_version"))
        if key in workflows:
            raise ValueError("Duplicate workflow version in compatibility manifest.")
        if not isinstance(workflow["reference_sets"], list) or not workflow["reference_sets"]:
            raise ValueError("Workflow must declare at least one compatible reference set.")
        workflows[key] = [reference_set(references) for references in workflow["reference_sets"]]
    workflow_key = (request["workflow_id"], request["workflow_version"])
    if workflow_key not in workflows:
        raise ValueError(f"Undeclared workflow version: {workflow_key}.")
    if requested not in workflows[workflow_key]:
        raise ValueError(f"Incompatible reference set for workflow {workflow_key}: {sorted(requested)}.")
    if (request["reference_build"], request["reference_version"]) != (
        genome["name"], genome["version"]
    ):
        raise ValueError(
            "Explicit reference_build/reference_version must match the requested genome reference."
        )
    return requested


def validate_submission(request, compatibility, inventory):
    requested = validate_request_compatibility(request, compatibility)
    available = {}
    for reference in document(inventory, "references"):
        key = reference_key(reference, artifact=True)
        if key in available:
            raise ValueError("Duplicate reference version in inventory.")
        available[key] = reference
    missing = requested - available.keys()
    if missing:
        raise ValueError(f"Declared reference versions unavailable: {sorted(missing)}; no fallback permitted.")
    return {
        "schema_version": 1,
        "run_id": request["run_id"],
        "workflow_id": request["workflow_id"],
        "workflow_version": request["workflow_version"],
        "references": [copy.deepcopy(available[key]) for key in sorted(requested)],
        "compatibility_manifest_sha256": digest(compatibility),
        "reference_manifest_sha256": digest(inventory),
    }


def submit_run(request, compatibility, inventory, allocate):
    validated = validate_submission(request, compatibility, inventory)
    return allocate(validated)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate a local workflow/reference submission without allocating compute.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--compatibility", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        documents = []
        for path in (arguments.request, arguments.compatibility, arguments.inventory):
            with path.open(encoding="utf-8") as source:
                documents.append(json.load(source, object_pairs_hook=unique_object))
        validated = validate_submission(*documents)
        print(json.dumps({"mode": "local-only", "compute_allocated": False,
                          "azure_readiness": "not-evaluated", "submission": validated}))
    except (OSError, ValueError) as error:
        print(f"Submission rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())