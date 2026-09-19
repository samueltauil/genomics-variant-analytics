"""Fail-closed verification for pipeline images and repository dependencies."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_PROVENANCE = {"repository", "commit", "workflow"}
REQUIRED_TOOLS = {"aligner", "variant-caller"}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()


def _exact_fields(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} must contain exactly: {', '.join(sorted(expected))}.")
    return value


def verify_submission(submission: Mapping[str, Any]) -> dict[str, Any]:
    required = {"image", "image_digest", "pipeline_version", "provenance", "sbom", "dependencies"}
    payload = _exact_fields(submission, required, "Supply-chain submission")
    image = _required_text(payload["image"], "image")
    digest = _required_text(payload["image_digest"], "image_digest")
    if not _SHA256.fullmatch(digest):
        raise ValueError("image_digest must be a sha256 digest.")
    pipeline_version = _required_text(payload["pipeline_version"], "pipeline_version")

    provenance = _exact_fields(payload["provenance"], REQUIRED_PROVENANCE, "provenance")
    repository = _required_text(provenance["repository"], "provenance.repository")
    commit = _required_text(provenance["commit"], "provenance.commit")
    workflow = _required_text(provenance["workflow"], "provenance.workflow")
    if not _COMMIT.fullmatch(commit):
        raise ValueError("provenance.commit must be a full commit SHA.")

    sbom = payload["sbom"]
    if not isinstance(sbom, list) or not sbom:
        raise ValueError("sbom must be a nonempty component list.")
    tools = set()
    for component in sbom:
        entry = _exact_fields(component, {"name", "version"}, "SBOM component")
        tools.add(_required_text(entry["name"], "SBOM component name"))
        _required_text(entry["version"], "SBOM component version")
    missing_tools = REQUIRED_TOOLS - tools
    if missing_tools:
        raise ValueError(f"SBOM is missing required tool components: {sorted(missing_tools)}.")

    dependencies = payload["dependencies"]
    if not isinstance(dependencies, list):
        raise ValueError("dependencies must be a list.")
    for dependency in dependencies:
        entry = _exact_fields(dependency, {"name", "commit"}, "dependency")
        _required_text(entry["name"], "dependency.name")
        dependency_commit = _required_text(entry["commit"], "dependency.commit")
        if not _COMMIT.fullmatch(dependency_commit):
            raise ValueError(
                f"Untracked dependency {entry['name']!r}: a 40-character commit SHA is required."
            )

    return {
        "image": image,
        "image_digest": digest,
        "pipeline_version": pipeline_version,
        "provenance": dict(provenance),
        "sbom": [dict(component) for component in sbom],
        "dependencies": [dict(dependency) for dependency in dependencies],
    }


def verify_gh_attestations(
    image: str,
    repository: str,
    workflow: str | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    for predicate in ("https://slsa.dev/provenance/v1", "https://cyclonedx.org/bom"):
        command = [
            "gh", "attestation", "verify", f"oci://{image}", "--repo", repository,
            "--bundle-from-oci", "--predicate-type", predicate,
        ]
        if workflow:
            command.extend(["--signer-workflow", workflow])
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(
                f"Attestation verification failed for {image} ({predicate}): "
                f"{(result.stderr or result.stdout).strip()}"
            )


def load_submission(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)
