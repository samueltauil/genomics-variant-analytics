"""Review presenter-facing material and proposal assumptions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


CLAIM_REGISTER = Path("docs/claim-register.md")
PROPOSAL = Path("openspec/changes/add-genomics-variant-accelerator/proposal.md")
TASKS = Path("openspec/changes/add-genomics-variant-accelerator/tasks.md")
COVERAGE = Path("docs/coverage.md")
ASSUMPTION_REGISTER = Path("docs/assumption-register.json")
POSITIONING_REPORT = Path("docs/positioning-review.json")

PRESENTER_ROOT_FILES = (Path("README.md"), Path("SUPPORT.md"), Path("infra/README.md"))
PRESENTER_SUFFIXES = {".md", ".html", ".htm", ".txt"}
GENERATED_DIRECTORIES = {"generated", "presentations", "slides", "handouts"}

REQUIRED_BOUNDARIES = (
    "Boundary 1 — Released blueprint and product status",
    "Boundary 2 — Compliance",
    "Boundary 3 — Customer references",
    "Boundary 4 — Clinical use",
)
SEARCH_TERMS = (
    "customer", "production", "deployed", "blueprint", "generally available",
    "supported", "compliant", "HIPAA", "GDPR", "clinical", "diagnoses",
    "pathogenicity",
)


@dataclass(frozen=True)
class Rule:
    identifier: str
    boundary: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str


RULES = (
    Rule("released-offering", "released-blueprint", re.compile(
        r"\b(?:Microsoft (?:has a genomics accelerator|blueprint|product)|"
        r"released Microsoft blueprint|generally available|productized|"
        r"supported Microsoft (?:offering|product|service))\b", re.I,
    )),
    Rule("automatic-compliance", "compliance", re.compile(
        r"\b(?:HIPAA compliant|GDPR compliant|compliance (?:solution|outcome)|"
        r"(?:makes?|made|making) (?:your |the )?(?:genomic )?data compliant|"
        r"handles? the compliance side)\b", re.I,
    )),
    Rule("customer-attribution", "customer-reference", re.compile(
        r"\b(?:customers? use(?:s|d)? (?:this|the) accelerator|"
        r"(?:this|the) accelerator (?:is )?(?:deployed|used) (?:at|by|for)|"
        r"production use across (?:genomics )?customers?|"
        r"confirmed end-to-end customer deployment)\b", re.I,
    )),
    Rule("clinical-output", "clinical-use", re.compile(
        r"\b(?:AI (?:interprets?|diagnoses?|determines?)|"
        r"(?:assisted|AI-assisted) (?:output|analysis|interpretation).{0,35}"
        r"(?:clinical determination|diagnos(?:is|tic)|pathogenicity|"
        r"treatment recommendation|clinical decision)|"
        r"supports? clinical decision-making|clinical decision-support (?:capability|system))\b",
        re.I,
    )),
)

NEGATION = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|does not|do not|must not|"
    r"isn't|aren't|neither|nor|excluded|prohibited|avoid|refus(?:e|es|ed)|"
    r"unverified)\b",
    re.I,
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def discover_presenter_material(root: Path) -> list[Path]:
    paths = {root / item for item in PRESENTER_ROOT_FILES if (root / item).is_file()}
    docs = root / "docs"
    if docs.is_dir():
        paths.update(path for path in docs.rglob("*.md") if path.is_file())
    for directory in GENERATED_DIRECTORIES:
        base = root / directory
        if base.is_dir():
            paths.update(
                path for path in base.rglob("*")
                if path.is_file() and path.suffix.lower() in PRESENTER_SUFFIXES
            )
    paths.discard(root / POSITIONING_REPORT)
    return sorted(paths, key=lambda path: _relative(path, root))


def validate_claim_register(root: Path) -> str:
    path = root / CLAIM_REGISTER
    text = path.read_text(encoding="utf-8")
    missing = [heading for heading in REQUIRED_BOUNDARIES if heading not in text]
    if missing:
        raise ValueError("Claim register is missing boundaries: " + ", ".join(missing))
    return text


def _is_allowed_context(path: str, line: str, match_start: int) -> tuple[bool, str]:
    if path == CLAIM_REGISTER.as_posix():
        return True, "canonical claim-register guidance"
    prefix = line[max(0, match_start - 90):match_start]
    if NEGATION.search(prefix) or NEGATION.search(line):
        return True, "explicitly negated or prohibited"
    return False, "prohibited assertion"


def review_material(root: Path) -> tuple[list[str], list[dict], list[Finding]]:
    reviewed: list[str] = []
    matches: list[dict] = []
    findings: list[Finding] = []
    for material in discover_presenter_material(root):
        relative = _relative(material, root)
        reviewed.append(relative)
        text = material.read_text(encoding="utf-8")
        lines = text.splitlines()
        for line_number, line in enumerate(lines, 1):
            for rule in RULES:
                for match in rule.pattern.finditer(line):
                    previous = lines[line_number - 2] if line_number > 1 else ""
                    context = f"{previous} {line}" if previous.strip() else line
                    context_start = len(previous) + 1 + match.start() if previous.strip() else match.start()
                    allowed, disposition = _is_allowed_context(
                        relative, context, context_start,
                    )
                    record = {
                        "path": relative,
                        "line": line_number,
                        "boundary": rule.boundary,
                        "rule": rule.identifier,
                        "text": line.strip(),
                        "disposition": disposition,
                    }
                    matches.append(record)
                    if not allowed:
                        findings.append(Finding(
                            relative, line_number, rule.identifier, line.strip(),
                        ))
    return reviewed, matches, findings


def proposal_assumptions(text: str) -> list[str]:
    marker = "### Assumptions"
    start = text.find(marker)
    if start < 0:
        raise ValueError("proposal.md has no Assumptions section.")
    section = text[start + len(marker):]
    next_heading = re.search(r"^###? ", section, re.M)
    if next_heading:
        section = section[:next_heading.start()]
    assumptions = [
        match.group(1).strip()
        for match in re.finditer(r"^- (.+(?:\n  .+)*)$", section, re.M)
    ]
    return [" ".join(item.splitlines()) for item in assumptions]


def _task_states(text: str) -> dict[str, str]:
    return {
        match.group(2): ("complete" if match.group(1) == "x" else "open")
        for match in re.finditer(r"^- \[([x ])\] (\d+\.\d+)\b", text, re.M)
    }


def _coverage_states(text: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(
            r"^\| \[`([^`]+)`\]\([^)]+\) \| \*\*(Demonstrated|Partially demonstrated|Specified only)\*\* \|",
            line,
        )
        if match:
            states[match.group(1)] = match.group(2)
    return states


def validate_assumptions(root: Path) -> list[dict]:
    proposal = (root / PROPOSAL).read_text(encoding="utf-8")
    assumptions = proposal_assumptions(proposal)
    document = json.loads((root / ASSUMPTION_REGISTER).read_text(encoding="utf-8"))
    entries = document.get("assumptions")
    if not isinstance(entries, list):
        raise ValueError("Assumption register must contain an assumptions array.")
    registered = [entry.get("proposal_text") for entry in entries]
    if registered != assumptions:
        raise ValueError(
            "Assumption register does not exactly match the ordered proposal assumptions."
        )

    task_states = _task_states((root / TASKS).read_text(encoding="utf-8"))
    coverage = (root / COVERAGE).read_text(encoding="utf-8")
    coverage_states = _coverage_states(coverage)
    seen_ids: set[str] = set()
    results: list[dict] = []
    for entry in entries:
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            raise ValueError("Every assumption needs a unique non-empty id.")
        seen_ids.add(identifier)
        status = entry.get("status")
        confirmation = entry.get("reviewed_confirmation")
        if status not in {"assumption", "confirmed"}:
            raise ValueError(f"{identifier}: status must be assumption or confirmed.")
        if status == "confirmed":
            if not isinstance(confirmation, dict):
                raise ValueError(f"{identifier}: confirmation requires reviewed evidence.")
            for field in ("source", "reviewer", "date"):
                if not confirmation.get(field):
                    raise ValueError(f"{identifier}: confirmation is missing {field}.")
        elif confirmation is not None:
            raise ValueError(f"{identifier}: an assumption cannot carry confirmation evidence.")

        task_ids = entry.get("task_evidence")
        implementation = entry.get("implementation_evidence")
        capability = entry.get("coverage_capability")
        expected_coverage_status = entry.get("coverage_status")
        if not isinstance(task_ids, list) or not task_ids:
            raise ValueError(f"{identifier}: task evidence is required.")
        unknown_tasks = [task for task in task_ids if task not in task_states]
        if unknown_tasks:
            raise ValueError(f"{identifier}: unknown task evidence {unknown_tasks}.")
        if not isinstance(implementation, list):
            raise ValueError(f"{identifier}: implementation_evidence must be an array.")
        missing_paths = [
            path for path in implementation
            if not isinstance(path, str) or not (root / path).is_file()
        ]
        if missing_paths:
            raise ValueError(f"{identifier}: missing implementation evidence {missing_paths}.")
        if not isinstance(capability, str) or capability not in coverage_states:
            raise ValueError(f"{identifier}: coverage capability is absent from docs/coverage.md.")
        if expected_coverage_status != coverage_states[capability]:
            raise ValueError(
                f"{identifier}: registered coverage status {expected_coverage_status!r} "
                f"does not match {coverage_states[capability]!r}."
            )
        if not isinstance(entry.get("assessment"), str) or not entry["assessment"].strip():
            raise ValueError(f"{identifier}: assessment is required.")
        results.append({
            "id": identifier,
            "status": status,
            "task_evidence": [
                {"task": task, "status": task_states[task]} for task in task_ids
            ],
            "implementation_evidence": implementation,
            "coverage_capability": capability,
            "coverage_status": coverage_states[capability],
            "assessment": entry["assessment"],
        })
    return results


def build_report(root: Path, review_date: str) -> tuple[dict, list[Finding]]:
    claim_text = validate_claim_register(root)
    reviewed, matches, findings = review_material(root)
    assumptions = validate_assumptions(root)
    report = {
        "schema_version": 1,
        "review_date": review_date,
        "reviewer": "automated repository positioning review",
        "claim_register": CLAIM_REGISTER.as_posix(),
        "claim_register_sha256": hashlib.sha256(claim_text.encode("utf-8")).hexdigest(),
        "result": "pass" if not findings else "changes required",
        "search_terms": list(SEARCH_TERMS),
        "reviewed_files": reviewed,
        "flagged_matches": matches,
        "assumption_cross_check": assumptions,
    }
    return report, findings


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--review-date", default=date.today().isoformat())
    parser.add_argument("--write-report", type=Path)
    parser.add_argument("--check-report", type=Path)
    arguments = parser.parse_args(argv)
    root = arguments.repo.resolve()
    try:
        report, findings = build_report(root, arguments.review_date)
        if arguments.write_report:
            output = arguments.write_report
            if not output.is_absolute():
                output = root / output
            _write_json(output, report)
        if arguments.check_report:
            expected_path = arguments.check_report
            if not expected_path.is_absolute():
                expected_path = root / expected_path
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            if expected != report:
                print(
                    f"Positioning report is stale; regenerate {expected_path}.",
                    file=sys.stderr,
                )
                return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Positioning review could not complete: {error}", file=sys.stderr)
        return 2

    print(f"Reviewed {len(report['reviewed_files'])} presenter-facing files.")
    print(f"Recorded {len(report['flagged_matches'])} contextual claim matches.")
    print(f"Cross-checked {len(report['assumption_cross_check'])} proposal assumptions.")
    if findings:
        print("Prohibited positioning claims:", file=sys.stderr)
        for finding in findings:
            print(
                f"- {finding.path}:{finding.line} [{finding.rule}] {finding.text}",
                file=sys.stderr,
            )
        return 1
    print("Positioning and assumption review passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
