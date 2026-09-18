"""Generate and validate the metadata-only Platinum Genomes demo manifest."""

import argparse
import copy
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
DEFAULT_IDENTITY_COUNT = 17
DEFAULT_COHORT_COUNT = 2
SUBJECT_ID_PATTERN = r"SYN-PG-SUBJECT-[0-9]{4}"
SAMPLE_ID_PATTERN = r"SYN-PG-SAMPLE-[0-9]{4}"
COHORT_ID_PATTERN = r"SYN-PG-COHORT-[0-9]{2}"
MANIFEST_ID_PATTERN = r"SYN-PG-MANIFEST-[0-9]{3}"

SOURCE_DATASET = {
    "provider": "Illumina",
    "name": "Platinum Genomes",
    "release": "2017-1.0",
    "authorization_basis": "azure-open-datasets-public-sample",
    "authorization_uri": (
        "https://learn.microsoft.com/azure/open-datasets/dataset-genomics-data-lake"
    ),
    "collection_uri": "https://datasetplatinumgenomes.blob.core.windows.net/dataset",
    "collection_path": "2017-1.0/hg38",
}
REFERENCE = {
    "build": "GRCh38",
    "immutable_source_version": "2017-1.0/hg38",
    "compatibility_status": "validation-required-before-compute",
}

FORBIDDEN_FIELD_TOKENS = frozenset({
    "address",
    "birth",
    "contact",
    "customer",
    "dob",
    "email",
    "firstname",
    "lastname",
    "medicalrecord",
    "mrn",
    "patient",
    "phone",
    "socialsecurity",
    "ssn",
})
FORBIDDEN_VALUE_PATTERNS = (
    ("email address", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("US Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "telephone number",
        re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"),
    ),
    ("source donor identifier", re.compile(r"\b(?:NA|HG)\d{5}\b")),
)


def _fields(value, expected, label):
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(expected))}.")


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace.")
    return value


def _https_uri(value, label):
    parsed = urlsplit(_text(value, label))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS URI without query or fragment.")
    return value


def _scan_for_direct_identifiers(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(token in normalized for token in FORBIDDEN_FIELD_TOKENS):
                raise ValueError(f"Patient-identifying field is forbidden at {path}.{key}.")
            _scan_for_direct_identifiers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_direct_identifiers(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for label, pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"Patient-identifying value ({label}) is forbidden at {path}.")


def build_manifest(identity_count=DEFAULT_IDENTITY_COUNT, cohort_count=DEFAULT_COHORT_COUNT):
    if type(identity_count) is not int or not 1 <= identity_count <= 9999:
        raise ValueError("identity_count must be an integer from 1 through 9999.")
    if type(cohort_count) is not int or not 1 <= cohort_count <= 99:
        raise ValueError("cohort_count must be an integer from 1 through 99.")
    identities = []
    for index in range(1, identity_count + 1):
        cohort = ((index - 1) % cohort_count) + 1
        identities.append({
            "subject_id": f"SYN-PG-SUBJECT-{index:04d}",
            "sample_id": f"SYN-PG-SAMPLE-{index:04d}",
            "cohort_id": f"SYN-PG-COHORT-{cohort:02d}",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": "SYN-PG-MANIFEST-001",
        "source_dataset": copy.deepcopy(SOURCE_DATASET),
        "reference": copy.deepcopy(REFERENCE),
        "synthetic_identity_policy": {
            "subject_id_pattern": f"^{SUBJECT_ID_PATTERN}$",
            "sample_id_pattern": f"^{SAMPLE_ID_PATTERN}$",
            "cohort_id_pattern": f"^{COHORT_ID_PATTERN}$",
        },
        "identities": identities,
    }


def validate_manifest(manifest):
    _scan_for_direct_identifiers(manifest)
    _fields(
        manifest,
        {
            "schema_version",
            "manifest_id",
            "source_dataset",
            "reference",
            "synthetic_identity_policy",
            "identities",
        },
        "Manifest",
    )
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version; expected {SCHEMA_VERSION}.")
    if re.fullmatch(MANIFEST_ID_PATTERN, _text(manifest["manifest_id"], "manifest_id")) is None:
        raise ValueError(f"manifest_id must match {MANIFEST_ID_PATTERN}.")

    _fields(manifest["source_dataset"], SOURCE_DATASET.keys(), "source_dataset")
    for field, expected in SOURCE_DATASET.items():
        if manifest["source_dataset"][field] != expected:
            raise ValueError(f"source_dataset.{field} must be {expected!r}.")
    for field in ("authorization_uri", "collection_uri"):
        _https_uri(manifest["source_dataset"][field], f"source_dataset.{field}")

    _fields(manifest["reference"], REFERENCE.keys(), "reference")
    for field, expected in REFERENCE.items():
        if manifest["reference"][field] != expected:
            raise ValueError(f"reference.{field} must be {expected!r}.")

    expected_patterns = {
        "subject_id_pattern": f"^{SUBJECT_ID_PATTERN}$",
        "sample_id_pattern": f"^{SAMPLE_ID_PATTERN}$",
        "cohort_id_pattern": f"^{COHORT_ID_PATTERN}$",
    }
    patterns = manifest["synthetic_identity_policy"]
    _fields(patterns, expected_patterns.keys(), "synthetic_identity_policy")
    if patterns != expected_patterns:
        raise ValueError("Synthetic identity patterns must match the documented policy.")

    identities = manifest["identities"]
    if not isinstance(identities, list) or not identities:
        raise ValueError("identities must be a nonempty array.")
    seen_subjects = set()
    seen_samples = set()
    for index, identity in enumerate(identities):
        label = f"identities[{index}]"
        _fields(identity, {"subject_id", "sample_id", "cohort_id"}, label)
        for field, pattern in (
            ("subject_id", SUBJECT_ID_PATTERN),
            ("sample_id", SAMPLE_ID_PATTERN),
            ("cohort_id", COHORT_ID_PATTERN),
        ):
            if re.fullmatch(pattern, _text(identity[field], f"{label}.{field}")) is None:
                raise ValueError(f"{label}.{field} must match {pattern}.")
        if identity["subject_id"] in seen_subjects:
            raise ValueError(f"Duplicate subject_id: {identity['subject_id']}.")
        if identity["sample_id"] in seen_samples:
            raise ValueError(f"Duplicate sample_id: {identity['sample_id']}.")
        seen_subjects.add(identity["subject_id"])
        seen_samples.add(identity["sample_id"])

    return {
        "manifest_id": manifest["manifest_id"],
        "identity_count": len(identities),
        "patient_identifying_fields": 0,
        "patient_identifying_values": 0,
        "all_subject_ids_synthetic": True,
        "genomic_payloads_embedded": False,
        "reference_build": manifest["reference"]["build"],
        "reference_version": manifest["reference"]["immutable_source_version"],
        "compatibility_status": manifest["reference"]["compatibility_status"],
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _load(path):
    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=_unique_object)


def main():
    default_manifest = Path(__file__).resolve().parents[1] / "demo" / "dataset-manifest.json"
    parser = argparse.ArgumentParser(
        description="Generate or validate the metadata-only Platinum Genomes demo manifest."
    )
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--write", action="store_true", help="Write the deterministic manifest first.")
    parser.add_argument("--identity-count", type=int, default=DEFAULT_IDENTITY_COUNT)
    parser.add_argument("--cohort-count", type=int, default=DEFAULT_COHORT_COUNT)
    arguments = parser.parse_args()
    try:
        if arguments.write:
            manifest = build_manifest(arguments.identity_count, arguments.cohort_count)
            arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
            arguments.manifest.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        report = validate_manifest(_load(arguments.manifest))
        print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError) as error:
        print(f"Demo dataset manifest rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
