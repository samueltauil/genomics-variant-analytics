"""Tests for the loopback-only local synthetic demo UI."""

from http.client import HTTPConnection
import threading
import unittest
from pathlib import Path

from scripts.demo_ui import DemoHTTPServer, DemoRequestHandler, DemoSession


class DemoSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = DemoSession()
        self.addCleanup(self.session.close)

    def test_manifest_landing_pipeline_and_safeguards_run_locally(self):
        self.assertEqual(self.session.status()["mode"], "local-synthetic-only")
        self.assertFalse(self.session.status()["azure_actions_available"])

        with self.assertRaisesRegex(ValueError, "Validate the synthetic manifest"):
            self.session.run_action("landing")
        self.assertEqual(self.session.actions["landing"]["state"], "failed")

        manifest = self.session.run_action("manifest")
        self.assertTrue(manifest["all_subject_ids_synthetic"])
        self.assertEqual(manifest["patient_identifying_values"], 0)

        landing = self.session.run_action("landing")
        self.assertTrue(landing["verified"])
        self.assertTrue(landing["paths_preserved"])
        self.assertEqual(landing["file_count"], 34)

        pipeline = self.session.run_action("pipeline")
        self.assertEqual(pipeline["terminal_state"], "succeeded")
        self.assertEqual(pipeline["reference_build"], "SYN-demo-genome")
        self.assertEqual(pipeline["reference_version"], "synthetic-1385e2e921c4")
        self.assertEqual(pipeline["output_count"], 3)

        safeguards = self.session.run_action("safeguards")
        self.assertTrue(safeguards["all_passed"])
        self.assertFalse(safeguards["infrastructure_touched"])
        self.assertEqual(len(safeguards["demonstrations"]), 3)

    def test_reset_removes_only_its_unique_owned_session_directory(self):
        outside = self.session.root.parent / f"{self.session.root.name}-neighbor.txt"
        outside.write_text("leave this file alone", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        previous_root = self.session.root
        self.session.run_action("manifest")

        self.session.reset()

        self.assertFalse(previous_root.exists())
        self.assertTrue(outside.is_file())
        self.assertTrue(self.session.status()["reports"] == {})
        self.assertEqual(self.session.actions["manifest"]["state"], "ready")

    def test_reset_refuses_a_session_without_its_owner_marker(self):
        marker = self.session.root / ".demo-ui-owner"
        owner = marker.read_text(encoding="ascii")
        marker.write_text("not-the-owner", encoding="ascii")
        try:
            with self.assertRaisesRegex(RuntimeError, "not owned"):
                self.session.reset()
            self.assertTrue(self.session.root.is_dir())
        finally:
            marker.write_text(owner, encoding="ascii")

    def test_unknown_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown demo action"):
            self.session.run_action("azure-deploy")


class DemoUIHTTPTests(unittest.TestCase):
    def setUp(self):
        self.session = DemoSession()
        self.server = DemoHTTPServer(("127.0.0.1", 0), DemoRequestHandler, self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.session.close()

    def _request(self, method, path, *, origin=None, body=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Length"] = str(len(body))
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, response.headers, response.read()
        connection.close()
        return result

    def test_serves_ui_with_local_only_status_and_security_headers(self):
        status, headers, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"no Azure actions", body)
        self.assertIn(b"separate harnesses", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

        status, _, body = self._request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIn(b'"azure_actions_available": false', body)

    def test_manifest_and_landing_actions_are_exposed_as_local_api(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, _, _ = self._request(
            "POST", "/api/run/manifest", origin=origin
        )
        self.assertEqual(status, 200)
        status, _, body = self._request(
            "POST", "/api/run/landing", origin=origin
        )
        self.assertEqual(status, 200)
        self.assertIn(b'"file_count": 34', body)

    def test_rejects_cross_origin_and_body_requests(self):
        foreign_origin = "http://example.invalid"
        status, _, _ = self._request(
            "POST", "/api/run/manifest", origin=foreign_origin
        )
        self.assertEqual(status, 403)

        status, _, _ = self._request(
            "POST",
            "/api/run/manifest",
            origin=f"http://127.0.0.1:{self.server.server_port}",
            body=b"unexpected",
        )
        self.assertEqual(status, 400)

    def test_azure_routes_are_not_exposed(self):
        status, _, _ = self._request("POST", "/api/run/azure-deploy")
        self.assertEqual(status, 404)
        status, _, _ = self._request("POST", "/api/deploy")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
