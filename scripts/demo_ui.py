"""Serve a loopback-only browser UI for the local synthetic demo."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
from urllib.parse import urlsplit
from uuid import uuid4

from scripts.demo_dataset_manifest import _load, validate_manifest
from scripts.rehearse_demo_failures import rehearse_all
from scripts.run_secondary_pipeline import execute as run_pipeline
from scripts.stage_demo_landing import stage_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPOSITORY_ROOT / "demo-ui"
MANIFEST_PATH = REPOSITORY_ROOT / "demo" / "dataset-manifest.json"
DOCS = {
    "/docs/coverage.md": REPOSITORY_ROOT / "docs" / "coverage.md",
    "/docs/solution-engineer-guide.md": (
        REPOSITORY_ROOT / "docs" / "solution-engineer-guide.md"
    ),
}
REFERENCE_BUILD = "SYN-demo-genome"
REFERENCE_VERSION = "synthetic-1385e2e921c4"
REFERENCE_MANIFEST_SHA256 = (
    "7e3be36672095e4018dfded5466ddb002848387e19d314595cb1a128a231be83"
)
ACTION_NAMES = ("manifest", "landing", "pipeline", "safeguards")
ASSETS = {
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class DemoSession:
    """Own the generated files for one local browser session."""

    def __init__(self):
        self.lock = threading.Lock()
        self.root = self._new_root()
        self.reports: dict[str, dict] = {}
        self.actions = {
            name: {"state": "ready", "error": None} for name in ACTION_NAMES
        }
        self.pipeline_counter = 0

    def _new_root(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="genomics-demo-ui-")).resolve()
        self.owner_token = uuid4().hex
        (path / ".demo-ui-owner").write_text(self.owner_token, encoding="ascii")
        return path

    def _owns_root(self) -> bool:
        root = self.root.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        marker = root / ".demo-ui-owner"
        if not (
            root.parent == temp_root
            and root.name.startswith("genomics-demo-ui-")
            and root.is_dir()
            and marker.is_file()
            and not marker.is_symlink()
        ):
            return False
        try:
            return marker.read_text(encoding="ascii") == self.owner_token
        except (OSError, UnicodeError):
            return False

    def status(self) -> dict:
        return {
            "mode": "local-synthetic-only",
            "azure_actions_available": False,
            "tracks_are_independent": True,
            "actions": self.actions,
            "reports": self.reports,
        }

    def run_action(self, name: str) -> dict:
        if name not in ACTION_NAMES:
            raise ValueError("Unknown demo action.")
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("Another demo action is still running.")
        try:
            self.actions[name] = {"state": "running", "error": None}
            try:
                report = getattr(self, f"_run_{name}")()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                self.actions[name] = {"state": "failed", "error": str(error)}
                raise
            self.actions[name] = {"state": "passed", "error": None}
            self.reports[name] = report
            return report
        finally:
            self.lock.release()

    def _run_manifest(self) -> dict:
        return validate_manifest(_load(MANIFEST_PATH))

    def _run_landing(self) -> dict:
        if self.actions["manifest"]["state"] != "passed":
            raise ValueError("Validate the synthetic manifest before preparing landing metadata.")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        report = stage_manifest(
            MANIFEST_PATH,
            self.root / "landing",
            self.root / "landing-inventory.sqlite3",
        )
        return {
            "manifest_id": report["manifest_id"],
            "run_id": report["run_id"],
            "reference_build": report["reference_build"],
            "reference_version": report["reference_version"],
            "identity_count": report["identity_count"],
            "file_count": report["file_count"],
            "paths_preserved": report["paths_preserved"],
            "verified": report["verified"],
            "example_paths": [item["path"] for item in report["files"][:3]],
        }

    def _run_pipeline(self) -> dict:
        self.pipeline_counter += 1
        run_id = f"SYN-UI-DEMO-{self.pipeline_counter:03d}"
        report = run_pipeline(
            run_id=run_id,
            work_dir=self.root / "pipeline-work" / run_id,
            publish_dir=self.root / "published" / run_id,
            provenance_db=self.root / "pipeline-provenance.sqlite3",
            reference_build=REFERENCE_BUILD,
            reference_version=REFERENCE_VERSION,
            reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
        )
        return {
            "run_id": report["run_id"],
            "terminal_state": report["terminal_state"],
            "workflow_version": report["provenance"]["workflow_version"],
            "reference_build": report["reference_build"],
            "reference_version": report["reference_version"],
            "reference_manifest_sha256": report["reference_manifest_sha256"],
            "output_count": len(report["provenance"]["output_uris"]),
            "outputs": [
                Path(urlsplit(uri).path).name
                for uri in report["provenance"]["output_uris"]
            ],
        }

    def _run_safeguards(self) -> dict:
        report = rehearse_all(self.root / "state")
        return {
            "all_passed": report["all_passed"],
            "infrastructure_touched": report["infrastructure_touched"],
            "demonstrations": [
                {
                    "name": item["demonstration"],
                    "passed": item["passed"],
                    "expected_response": item["expected_response"],
                    "actual_response": item["actual_response"],
                }
                for item in report["demonstrations"]
            ],
        }

    def reset(self) -> None:
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("Wait for the running demo action before resetting.")
        try:
            if not self._owns_root():
                raise RuntimeError("The demo session directory is not owned by this UI.")
            shutil.rmtree(self.root)
            self.root = self._new_root()
            self.reports.clear()
            self.actions = {
                name: {"state": "ready", "error": None} for name in ACTION_NAMES
            }
            self.pipeline_counter = 0
        finally:
            self.lock.release()

    def close(self) -> None:
        if self._owns_root():
            shutil.rmtree(self.root)


class DemoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, session: DemoSession):
        self.session = session
        super().__init__(address, handler)


class DemoRequestHandler(BaseHTTPRequestHandler):
    server: DemoHTTPServer

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _request_is_local(self) -> bool:
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
            host = self.headers.get("Host", "")
            if host != f"127.0.0.1:{self.server.server_port}":
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                return (
                    parsed.scheme == "http"
                    and parsed.hostname == "127.0.0.1"
                    and parsed.port == self.server.server_port
                    and not parsed.username
                    and not parsed.password
                )
            return True
        except ValueError:
            return False

    def do_GET(self) -> None:
        if not self._request_is_local():
            self._json_response(403, {"error": "Requests are limited to this local demo."})
            return

        if self.path == "/":
            target = WEB_ROOT / "index.html"
            content_type = "text/html; charset=utf-8"
        elif self.path in ASSETS:
            filename, content_type = ASSETS[self.path]
            target = WEB_ROOT / filename
        elif self.path in DOCS:
            target = DOCS[self.path]
            content_type = "text/markdown; charset=utf-8"
        elif self.path == "/api/status":
            self._json_response(200, self.server.session.status())
            return
        else:
            self._json_response(404, {"error": "Not found."})
            return

        try:
            body = target.read_bytes()
        except OSError:
            self._json_response(500, {"error": "Demo UI asset could not be read."})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._request_is_local():
            self._json_response(403, {"error": "Requests are limited to this local demo."})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json_response(400, {"error": "Request bodies are not accepted."})
            return
        try:
            body_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(400, {"error": "Invalid request length."})
            return
        if body_length != 0:
            self._json_response(400, {"error": "Request bodies are not accepted."})
            return

        if self.path == "/api/reset":
            try:
                self.server.session.reset()
            except BlockingIOError as error:
                self._json_response(409, {"error": str(error)})
                return
            except (OSError, RuntimeError) as error:
                self._json_response(500, {"error": str(error)})
                return
            self._json_response(200, {"reset": True, **self.server.session.status()})
            return

        prefix = "/api/run/"
        if not self.path.startswith(prefix):
            self._json_response(404, {"error": "Not found."})
            return

        action = self.path[len(prefix):]
        if action not in ACTION_NAMES:
            self._json_response(404, {"error": "Not found."})
            return
        try:
            report = self.server.session.run_action(action)
        except BlockingIOError as error:
            self._json_response(409, {"error": str(error)})
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            self._json_response(422, {
                "error": str(error),
                "status": self.server.session.status(),
            })
        else:
            self._json_response(200, {
                "report": report,
                "status": self.server.session.status(),
            })

    def log_message(self, format: str, *args) -> None:
        print(f"[demo-ui] {format % args}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args(argv)
    if not 1024 <= arguments.port <= 65535:
        parser.error("--port must be between 1024 and 65535.")

    session = DemoSession()
    try:
        server = DemoHTTPServer(("127.0.0.1", arguments.port), DemoRequestHandler, session)
    except OSError:
        session.close()
        raise
    address = f"http://127.0.0.1:{server.server_port}/"
    print(f"Local synthetic demo UI: {address}")
    print("This UI has no Azure actions. Press Ctrl+C to stop and remove its temporary files.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local demo UI.")
    finally:
        server.server_close()
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
