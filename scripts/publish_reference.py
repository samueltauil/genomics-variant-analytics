"""Publishes versioned reference data into an immutable zone and lists what is available.

Storage access is supplied as a transport so the publication rules can be exercised without a
storage account. Each version is written once: the manifest is the commit point, and an entry whose
manifest already exists is refused before any artifact is written.
"""

import hashlib
import json
import re

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"

ENTRY_TYPES = frozenset({
    "genome", "gene-annotation", "transcript-annotation", "knowledge-base", "population",
})

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
CHUNK_BYTES = 8 * 1024 * 1024


class ReferenceExistsError(Exception):
    """Raised when a publish targets a version that is already published."""


def _identifier(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must match {IDENTIFIER.pattern}.")
    return value


def validate_entry(entry):
    """Check the type, name and version that identify a reference entry."""
    if not isinstance(entry, dict) or entry.keys() != {"type", "name", "version"}:
        raise ValueError("Entry must supply exactly type, name and version.")
    if entry["type"] not in ENTRY_TYPES:
        raise ValueError(f"Entry type must be one of {sorted(ENTRY_TYPES)}.")
    _identifier(entry["name"], "Entry name")
    _identifier(entry["version"], "Entry version")
    return entry


def reference_path(entry, filename=MANIFEST_NAME):
    """Return the zone-relative path for an artifact, laid out as type/name/version."""
    validate_entry(entry)
    _identifier(filename, "Artifact filename")
    return f"{entry['type']}/{entry['name']}/{entry['version']}/{filename}"


def manifest_document(entry, artifacts, published_at):
    """Build the per-artifact checksum manifest that makes a version citable."""
    validate_entry(entry)
    if not artifacts:
        raise ValueError("A published version must contain at least one artifact.")
    return {
        "schema_version": SCHEMA_VERSION,
        "type": entry["type"],
        "name": entry["name"],
        "version": entry["version"],
        "published_at": published_at,
        "artifacts": sorted(artifacts, key=lambda artifact: artifact["filename"]),
    }


def parse_inventory(manifests):
    """Summarize published manifests as the type, name and version of each entry."""
    entries = []
    for document in manifests:
        entries.append({
            "type": document["type"],
            "name": document["name"],
            "version": document["version"],
            "artifact_count": len(document["artifacts"]),
            "published_at": document.get("published_at"),
        })
    return sorted(entries, key=lambda entry: (entry["type"], entry["name"], entry["version"]))


class ReferenceZone:
    """Publication and listing over a write-once reference container."""

    def __init__(self, transport):
        self._transport = transport

    def is_published(self, entry):
        return self._transport.exists(reference_path(entry))

    def publish(self, entry, artifacts, published_at):
        """Stream each artifact into the zone, then commit the manifest.

        `artifacts` supplies a filename and a callable returning a readable stream.
        """
        validate_entry(entry)
        if not artifacts:
            raise ValueError("A published version must contain at least one artifact.")
        if self.is_published(entry):
            raise ReferenceExistsError(
                f"{entry['type']}/{entry['name']}/{entry['version']} is already published;"
                " publish a new version instead."
            )

        recorded = []
        for artifact in artifacts:
            filename = artifact["filename"]
            path = reference_path(entry, filename)
            digest = hashlib.sha256()
            size = 0

            def counted(stream=artifact["open"]()):
                nonlocal size
                while True:
                    chunk = stream.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    yield chunk

            self._transport.put(path, counted())
            recorded.append({
                "filename": filename,
                "sha256": digest.hexdigest(),
                "size_bytes": size,
                "source": artifact.get("source"),
            })

        document = manifest_document(entry, recorded, published_at)
        self._transport.put_bytes(
            reference_path(entry), json.dumps(document, indent=2).encode("utf-8")
        )
        return document

    def manifests(self):
        documents = []
        for path in sorted(self._transport.list("")):
            if path.endswith("/" + MANIFEST_NAME):
                documents.append(json.loads(self._transport.get(path)))
        return documents

    def inventory(self):
        return parse_inventory(self.manifests())

    def get_manifest(self, entry):
        """Return a published manifest, or None when the version is absent."""
        path = reference_path(entry)
        if not self._transport.exists(path):
            return None
        return json.loads(self._transport.get(path))
