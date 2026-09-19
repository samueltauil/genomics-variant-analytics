"""Review provenance-affecting pull-request changes from trusted Git objects."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REFERENCE_MANIFEST = "workflows/reference-compatibility.json"
VARIANT_SCHEMA = "scripts/variant_store.py"
VARIANT_SPEC = (
    "openspec/changes/add-genomics-variant-accelerator/specs/"
    "variant-store/delta-variant-store/spec.md"
)


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


def _git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _blob(repo: Path, revision: str, path: str) -> str | None:
    result = _git(repo, "show", f"{revision}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def changed_paths(repo: Path, base: str, head: str) -> set[str]:
    result = _git(repo, "diff", "--name-only", f"{base}...{head}")
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def is_reviewed_path(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        path.startswith(".github/workflows/")
        or path.startswith("workflows/")
        or path.startswith("containers/")
        or name == "dockerfile"
        or name.endswith(".dockerfile")
        or path == REFERENCE_MANIFEST
        or path == VARIANT_SCHEMA
        or path == VARIANT_SPEC
    )


def _compatibility_entries(document: str, path: str) -> dict[str, dict]:
    try:
        payload = json.loads(document)
        workflows = payload["workflows"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"{path} is not a valid compatibility manifest: {error}") from error
    if not isinstance(workflows, list):
        raise ValueError(f"{path} workflows must be an array.")
    entries: dict[str, dict] = {}
    for entry in workflows:
        if not isinstance(entry, dict) or not isinstance(entry.get("workflow_id"), str):
            raise ValueError(f"{path} contains a workflow without a workflow_id.")
        workflow_id = entry["workflow_id"]
        if workflow_id in entries:
            raise ValueError(f"{path} repeats workflow_id {workflow_id}.")
        entries[workflow_id] = entry
    return entries


def review_reference_manifest(base_text: str | None, head_text: str | None) -> list[Finding]:
    if head_text is None:
        return [Finding(REFERENCE_MANIFEST, "Reference compatibility manifest was deleted.")]
    try:
        head = _compatibility_entries(head_text, REFERENCE_MANIFEST)
        base = _compatibility_entries(base_text, REFERENCE_MANIFEST) if base_text else {}
    except ValueError as error:
        return [Finding(REFERENCE_MANIFEST, str(error))]

    findings = []
    for workflow_id, current in head.items():
        previous = base.get(workflow_id)
        if previous is None:
            continue
        if previous.get("reference_sets") != current.get("reference_sets"):
            if previous.get("workflow_version") == current.get("workflow_version"):
                findings.append(Finding(
                    REFERENCE_MANIFEST,
                    f"Reference selection changed for workflow {workflow_id!r} without a "
                    "workflow_version bump.",
                ))
    return findings


def _assigned_string_tuple(source: str, variable: str, path: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise ValueError(f"{path} is not valid Python: {error.msg}") from error
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == variable for target in targets):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError) as error:
                    raise ValueError(f"{path} {variable} must be a literal sequence.") from error
                if not isinstance(value, (tuple, list)) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise ValueError(f"{path} {variable} must contain only string columns.")
                return tuple(value)
    raise ValueError(f"{path} does not declare {variable}.")


def _spec_columns(spec: str) -> tuple[str, ...]:
    core_marker = "Every variant record SHALL carry the core VCF fields:"
    context_marker = "Every variant record SHALL additionally carry"
    columns: list[str] = []
    for marker in (core_marker, context_marker):
        start = spec.find(marker)
        if start < 0:
            raise ValueError(f"{VARIANT_SPEC} is missing the governed schema statement: {marker}")
        paragraph = spec[start:spec.find("\n\n", start)]
        paragraph = paragraph.split(". ", 1)[0]
        columns.extend(part for index, part in enumerate(paragraph.split("`")) if index % 2)
    if len(columns) != 20 or len(set(columns)) != 20:
        raise ValueError(f"{VARIANT_SPEC} must define exactly 20 unique variant columns.")
    return tuple(columns)


def review_variant_schema(schema_text: str | None, spec_text: str | None) -> list[Finding]:
    if schema_text is None:
        return [Finding(VARIANT_SCHEMA, "Variant schema implementation was deleted.")]
    if spec_text is None:
        return [Finding(VARIANT_SPEC, "Governed variant-store specification was deleted.")]
    try:
        implemented = _assigned_string_tuple(schema_text, "VARIANT_FIELDS", VARIANT_SCHEMA)
        specified = _spec_columns(spec_text)
    except ValueError as error:
        return [Finding(VARIANT_SCHEMA, str(error))]
    absent = [column for column in implemented if column not in specified]
    missing = [column for column in specified if column not in implemented]
    findings = [
        Finding(
            VARIANT_SCHEMA,
            f"Variant-store column {column!r} is absent from {VARIANT_SPEC}; update the "
            "governed schema contract in the same reviewed change before implementation.",
        )
        for column in absent
    ]
    if missing:
        findings.append(Finding(
            VARIANT_SCHEMA,
            "Variant implementation is missing spec columns: " + ", ".join(missing),
        ))
    if len(implemented) != len(set(implemented)):
        findings.append(Finding(VARIANT_SCHEMA, "Variant implementation repeats a column name."))
    return findings


def review_repository(repo: Path, base: str, head: str) -> tuple[set[str], list[Finding]]:
    paths = changed_paths(repo, base, head)
    reviewed = {path for path in paths if is_reviewed_path(path)}
    findings: list[Finding] = []
    if REFERENCE_MANIFEST in paths:
        findings.extend(review_reference_manifest(
            _blob(repo, base, REFERENCE_MANIFEST),
            _blob(repo, head, REFERENCE_MANIFEST),
        ))
    if VARIANT_SCHEMA in paths or VARIANT_SPEC in paths:
        findings.extend(review_variant_schema(
            _blob(repo, head, VARIANT_SCHEMA),
            _blob(repo, head, VARIANT_SPEC),
        ))
    return reviewed, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    arguments = parser.parse_args(argv)
    try:
        reviewed, findings = review_repository(arguments.repo.resolve(), arguments.base, arguments.head)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Engineering review could not complete: {error}", file=sys.stderr)
        return 2
    print("Reviewed provenance-affecting paths:")
    for path in sorted(reviewed):
        print(f"- {path}")
    if findings:
        print("Engineering review findings:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.path}: {finding.message}", file=sys.stderr)
        return 1
    print("Engineering review passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
