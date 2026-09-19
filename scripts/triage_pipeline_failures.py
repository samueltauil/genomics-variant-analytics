"""Create or update one GitHub issue for each recurring pipeline failure."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


MARKER_PREFIX = "<!-- pipeline-failure:"
REQUIRED_FIELDS = (
    "failing_stage",
    "run_id",
    "reference_build",
    "pipeline_version",
    "log_location",
)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required.")
    value = value.strip()
    if "\r" in value or "\n" in value:
        raise ValueError(f"{field} must be a single line.")
    return value


@dataclass(frozen=True)
class Failure:
    failing_stage: str
    run_id: str
    reference_build: str
    pipeline_version: str
    log_location: str
    occurrence_id: str
    occurred_at: str
    failure_key: str

    @classmethod
    def from_mapping(cls, value: Any) -> "Failure":
        if not isinstance(value, dict):
            raise ValueError("Each failure must be an object.")
        fields = {name: _required_text(value.get(name), name) for name in REQUIRED_FIELDS}
        failure_key = _required_text(
            value.get("failure_key", f"{fields['run_id']}:{fields['failing_stage']}"),
            "failure_key",
        )
        occurred_at = _required_text(
            value.get("occurred_at", datetime.now(timezone.utc).isoformat()),
            "occurred_at",
        )
        occurrence_id = _required_text(
            value.get("occurrence_id", occurred_at),
            "occurrence_id",
        )
        return cls(**fields, failure_key=failure_key, occurred_at=occurred_at,
                   occurrence_id=occurrence_id)

    @property
    def marker(self) -> str:
        return f"{MARKER_PREFIX}{urllib.parse.quote(self.failure_key, safe='')} -->"


class IssueAdapter(Protocol):
    def find(self, marker: str) -> dict[str, Any] | None: ...
    def create(self, title: str, body: str) -> dict[str, Any]: ...
    def update(self, number: int, title: str, body: str) -> dict[str, Any]: ...


def _occurrence_marker(occurrence_id: str) -> str:
    return f"<!-- occurrence:{urllib.parse.quote(occurrence_id, safe='')} -->"


def _body(failure: Failure, count: int, occurrence_markers: list[str]) -> str:
    return "\n".join([
        failure.marker,
        *occurrence_markers,
        "## Pipeline failure",
        "",
        f"- Failing stage: `{failure.failing_stage}`",
        f"- Run identifier: `{failure.run_id}`",
        f"- Reference build: `{failure.reference_build}`",
        f"- Pipeline version: `{failure.pipeline_version}`",
        f"- Log location: {failure.log_location}",
        f"- Latest occurrence: `{failure.occurred_at}`",
        f"- Recurrence count: {count}",
        "",
        "This issue contains operational provenance only. Do not attach genomic data, "
        "patient identifiers, credentials, or copied log content.",
    ])


def triage(failures: list[Failure], adapter: IssueAdapter) -> list[dict[str, Any]]:
    actions = []
    for failure in failures:
        existing = adapter.find(failure.marker)
        occurrence = _occurrence_marker(failure.occurrence_id)
        title = f"Pipeline failure: {failure.run_id} / {failure.failing_stage}"
        if existing is None:
            result = adapter.create(title, _body(failure, 1, [occurrence]))
            actions.append({"action": "create", "failure_key": failure.failure_key, **result})
            continue
        body = str(existing.get("body") or "")
        if occurrence in body:
            actions.append({
                "action": "unchanged",
                "failure_key": failure.failure_key,
                "number": existing["number"],
            })
            continue
        markers = [line for line in body.splitlines() if line.startswith("<!-- occurrence:")]
        result = adapter.update(
            int(existing["number"]),
            title,
            _body(failure, len(markers) + 1, [*markers, occurrence]),
        )
        actions.append({"action": "update", "failure_key": failure.failure_key, **result})
    return actions


class DryRunAdapter:
    def __init__(self, issues: list[dict[str, Any]] | None = None):
        self.issues = list(issues or [])

    def find(self, marker: str) -> dict[str, Any] | None:
        return next((issue for issue in self.issues if marker in str(issue.get("body", ""))), None)

    def create(self, title: str, body: str) -> dict[str, Any]:
        issue = {"number": len(self.issues) + 1, "title": title, "body": body}
        self.issues.append(issue)
        return {"number": issue["number"]}

    def update(self, number: int, title: str, body: str) -> dict[str, Any]:
        issue = next(issue for issue in self.issues if issue["number"] == number)
        issue.update(title=title, body=body)
        return {"number": number}


class GitHubIssueAdapter:
    def __init__(
        self,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        opener=urllib.request.urlopen,
    ):
        if repository.count("/") != 1:
            raise ValueError("repository must use OWNER/REPO form.")
        self.base = f"{api_url.rstrip('/')}/repos/{repository}"
        self.token = _required_text(token, "GitHub token")
        self.opener = opener

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "genomics-variant-accelerator-triage",
            },
        )
        try:
            with self.opener(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"GitHub API {method} {path} failed: {error.code} {detail}") from error

    def find(self, marker: str) -> dict[str, Any] | None:
        page = 1
        while True:
            issues = self._request("GET", f"/issues?state=all&per_page=100&page={page}")
            match = next(
                (issue for issue in issues if marker in str(issue.get("body", ""))),
                None,
            )
            if match is not None or len(issues) < 100:
                return match
            page += 1

    def create(self, title: str, body: str) -> dict[str, Any]:
        issue = self._request("POST", "/issues", {"title": title, "body": body})
        return {"number": issue["number"], "html_url": issue.get("html_url")}

    def update(self, number: int, title: str, body: str) -> dict[str, Any]:
        issue = self._request("PATCH", f"/issues/{number}", {
            "title": title, "body": body, "state": "open",
        })
        return {"number": issue["number"], "html_url": issue.get("html_url")}


def load_failures(path: Path) -> list[Failure]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Failure input must be a JSON array.")
    return [Failure.from_mapping(item) for item in payload]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--token")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        failures = load_failures(arguments.input)
        if arguments.dry_run:
            adapter: IssueAdapter = DryRunAdapter()
        else:
            repository = arguments.repository or os.environ.get("GITHUB_REPOSITORY")
            token = arguments.token or os.environ.get("GH_TOKEN")
            adapter = GitHubIssueAdapter(
                _required_text(repository, "repository"),
                _required_text(token, "GitHub token"),
            )
        actions = triage(failures, adapter)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Pipeline failure triage could not complete: {error}", file=sys.stderr)
        return 2
    print(json.dumps(actions, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
