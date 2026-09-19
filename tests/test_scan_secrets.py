from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.scan_secrets import find_secrets, scan_repository


SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "scan_secrets.py"


class ScanSecretsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write("README.md", b"Synthetic test repository\n")
        self.base = self.commit()

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.decode("utf-8").strip()

    def write(self, name, content):
        path = self.repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Synthetic test change")
        return self.git("rev-parse", "HEAD")

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-I", str(SCANNER), "--repo", str(self.repository), *arguments],
            capture_output=True, text=True,
        )

    def test_clean_repository_passes(self):
        self.assertEqual(scan_repository(self.repository, base=self.base), [])
        self.assertEqual(self.run_cli().returncode, 0)

    def test_storage_connection_string_is_rejected(self):
        self.write(
            "config/legacy.env",
            b"DefaultEndpointsProtocol=https;AccountName=stgland;"
            b"Account" b"Key=abcd1234ABCD5678efgh9012IJKL3456mnop7890QRST1234"
            b"uvwx5678YZAB9012cdef3456==;EndpointSuffix=core.windows.net\n",
        )
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].path, "config/legacy.env")
        self.assertIn("connection string", violations[0].reason)
        self.assertEqual(self.run_cli("--base", self.base).returncode, 1)

    def test_service_bus_shared_access_key_is_rejected(self):
        self.write(
            "config/bus.env",
            b"Endpoint=sb://demo.servicebus.windows.net/;"
            b"SharedAccessKeyName=RootManageSharedAccessKey;"
            b"SharedAccess" b"Key=abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJ=\n",
        )
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertIn("Service Bus", violations[0].reason)

    def test_sas_query_string_is_rejected(self):
        self.write(
            "config/sas.txt",
            b"https://stglake.blob.core.windows.net/c/f.txt?sv=2020-01-01"
            b"&s" b"ig=abcdefghijklmnop1234567890ABCDEF%3D&se=2026-01-01T00:00:00Z\n",
        )
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertIn("SAS", violations[0].reason)

    def test_private_key_block_is_rejected(self):
        self.write("config/id_rsa", b"-----BEGIN RSA PRIVATE" b" KEY-----\nMIIB\n")
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertIn("PEM private key", violations[0].reason)

    def test_client_secret_literal_is_rejected(self):
        self.write("config/app.json", b'{"client_' b'secret": "S3cr3tLiteralValue"}\n')
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertIn("client secret", violations[0].reason)

    def test_placeholder_values_are_not_rejected(self):
        self.write(
            "docs/example.md",
            b'client_secret: "changeme"\naccount_key: "***"\nAccountKey=REDACTED\n',
        )
        self.commit()
        self.assertEqual(scan_repository(self.repository, base=self.base), [])

    def test_managed_identity_references_are_not_rejected(self):
        self.write(
            "docs/architecture.md",
            b"Every service authenticates with a managed identity via IMDS; "
            b"allowSharedKeyAccess is false and no key exists to mount with.\n",
        )
        self.commit()
        self.assertEqual(scan_repository(self.repository, base=self.base), [])

    def test_find_secrets_helper_matches_scan_repository(self):
        self.assertEqual(find_secrets("nothing sensitive here"), [])
        self.assertTrue(
            find_secrets(
                "Account" "Key=abcd1234ABCD5678efgh9012IJKL3456mnop7890=="
            )
        )

    def test_missing_revision_fails_closed(self):
        result = self.run_cli("--base", "missing-revision")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not complete", result.stderr)

    def test_nonpositive_limit_fails_closed(self):
        for limit in ("0", "-1"):
            with self.subTest(limit=limit):
                self.assertEqual(self.run_cli("--max-bytes", limit).returncode, 2)

    def test_missing_repository_fails_closed(self):
        result = self.run_cli("--repo", str(self.repository / "missing"))
        self.assertEqual(result.returncode, 2)

    def test_binary_blob_is_not_inspected(self):
        self.write("config/binary.bin", bytes(range(256)))
        self.commit()
        self.assertEqual(scan_repository(self.repository, base=self.base), [])

    def test_oversized_blob_is_skipped(self):
        self.write(
            "config/large.env",
            b"Account" b"Key=abcd1234ABCD5678efgh9012IJKL3456mnop7890QRST1234"
            b"uvwx5678YZAB9012cdef3456==" + b" " * 200,
        )
        self.commit()
        self.assertEqual(scan_repository(self.repository, base=self.base, max_bytes=32), [])


if __name__ == "__main__":
    unittest.main()
