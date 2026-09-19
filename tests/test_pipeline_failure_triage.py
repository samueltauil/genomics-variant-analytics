import io
import json
import unittest

from scripts.triage_pipeline_failures import (
    DryRunAdapter,
    Failure,
    GitHubIssueAdapter,
    triage,
)


def failure(occurrence):
    return Failure.from_mapping({
        "failure_key": "SYN-RUN-001:variant-calling",
        "occurrence_id": occurrence,
        "occurred_at": f"2026-09-19T0{occurrence}:00:00Z",
        "failing_stage": "variant-calling",
        "run_id": "SYN-RUN-001",
        "reference_build": "GRCh38",
        "pipeline_version": "v0.1.0",
        "log_location": "https://logs.example.invalid/runs/SYN-RUN-001",
    })


class PipelineFailureTriageTests(unittest.TestCase):
    def test_first_failure_creates_issue_with_required_provenance(self):
        adapter = DryRunAdapter()
        actions = triage([failure("1")], adapter)
        self.assertEqual(actions[0]["action"], "create")
        self.assertEqual(len(adapter.issues), 1)
        body = adapter.issues[0]["body"]
        for value in ("variant-calling", "SYN-RUN-001", "GRCh38", "v0.1.0",
                      "https://logs.example.invalid/runs/SYN-RUN-001"):
            self.assertIn(value, body)

    def test_recurrence_updates_existing_issue(self):
        adapter = DryRunAdapter()
        triage([failure("1")], adapter)
        actions = triage([failure("2")], adapter)
        self.assertEqual(actions[0]["action"], "update")
        self.assertEqual(len(adapter.issues), 1)
        self.assertIn("Recurrence count: 2", adapter.issues[0]["body"])

    def test_same_occurrence_is_idempotent(self):
        adapter = DryRunAdapter()
        triage([failure("1")], adapter)
        actions = triage([failure("1")], adapter)
        self.assertEqual(actions[0]["action"], "unchanged")
        self.assertEqual(len(adapter.issues), 1)

    def test_missing_provenance_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "reference_build is required"):
            Failure.from_mapping({
                "failing_stage": "alignment",
                "run_id": "SYN-RUN-002",
                "pipeline_version": "v0.1.0",
                "log_location": "https://logs.example.invalid/run",
            })

    def test_github_adapter_uses_issue_api_without_real_network_access(self):
        requests = []
        responses = iter([
            [{"number": 7, "body": failure("1").marker}],
            {"number": 8, "html_url": "https://example.invalid/issues/8"},
            {"number": 7, "html_url": "https://example.invalid/issues/7"},
        ])

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                self.close()

        def opener(request, timeout):
            requests.append((request.method, request.full_url, request.data, timeout))
            return Response(json.dumps(next(responses)).encode())

        adapter = GitHubIssueAdapter("owner/repo", "synthetic-token", opener=opener)
        self.assertEqual(adapter.find(failure("1").marker)["number"], 7)
        self.assertEqual(adapter.create("title", "body")["number"], 8)
        self.assertEqual(adapter.update(7, "title", "body")["number"], 7)
        self.assertEqual([item[0] for item in requests], ["GET", "POST", "PATCH"])
        self.assertIn("/repos/owner/repo/issues", requests[0][1])
        self.assertEqual(requests[0][3], 30)


if __name__ == "__main__":
    unittest.main()
