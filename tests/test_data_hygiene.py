from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.check_data_hygiene import is_genomic_path, scan_repository


SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "check_data_hygiene.py"


class DataHygieneTests(unittest.TestCase):
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

    def test_genomic_extensions_include_compressed_and_uppercase_forms(self):
        for suffix in ("vcf", "gvcf", "bam", "bai", "cram", "crai", "sam", "fastq",
                       "fq", "bcl", "fasta", "fa", "2bit"):
            for compression in ("", ".gz", ".bgz", ".bz2", ".xz", ".zst", ".zip"):
                with self.subTest(suffix=suffix, compression=compression):
                    self.assertTrue(is_genomic_path(f"run/sample.{suffix}{compression}".upper()))
        self.assertTrue(is_genomic_path("sample.vcf.gz.zip"))
        self.assertFalse(is_genomic_path("docs/vcf-format.md"))
        self.assertFalse(is_genomic_path("docs/sample.vcf.md"))

    def test_committed_genomic_files_fail_even_when_ignored(self):
        self.write(".gitignore", b"*.vcf\n")
        for suffix in ("vcf", "bam", "cram", "fastq", "VCF.GZ"):
            self.write(f"synthetic sample.{suffix}", b"not genomic data\n")
        self.git("add", "--force", "synthetic sample.vcf")
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 5)
        self.assertTrue(all(item.reason == "genomic file extension" for item in violations))
        self.assertEqual(self.run_cli("--base", self.base).returncode, 1)

    def test_genomic_files_without_a_stem_are_rejected(self):
        for name in (".vcf", ".VCF.GZ", ".bam", ".cram", ".fastq"):
            self.write(name, b"not genomic data\n")
        self.commit()
        self.assertEqual(len(scan_repository(self.repository, base=self.base)), 5)

    def test_submodule_entries_are_rejected(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},external")
        self.git("commit", "--quiet", "-m", "Synthetic gitlink")
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].path, "external")
        self.assertEqual(violations[0].reason, "uninspectable non-blob entry")

    def test_size_limit_is_inclusive_and_checks_git_blob_size(self):
        self.write("at-limit.txt", b"x" * 64)
        self.write("over-limit.txt", b"x" * 65)
        self.commit()
        self.write("over-limit.txt", b"small working copy")
        violations = scan_repository(self.repository, max_bytes=64)
        self.assertEqual([item.path for item in violations], ["over-limit.txt"])
        self.assertIn("65 bytes exceeds 64 bytes", violations[0].reason)

    def test_deleted_genomic_file_is_still_rejected_in_introduced_history(self):
        self.write("temporary.vcf", b"not genomic data\n")
        offending_commit = self.commit()
        self.git("rm", "temporary.vcf")
        self.commit()
        violations = scan_repository(self.repository, base=self.base)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].commit, offending_commit)

    def test_renamed_genomic_file_is_still_rejected(self):
        self.write("temporary.bam", b"not genomic data\n")
        self.commit()
        self.git("mv", "temporary.bam", "notes.txt")
        self.commit()
        self.assertEqual(len(scan_repository(self.repository, base=self.base)), 1)

    def test_repeated_blob_is_reported_once(self):
        self.write("temporary.fastq", b"not genomic data\n")
        self.commit()
        self.write("notes.txt", b"unrelated change\n")
        self.commit()
        self.assertEqual(len(scan_repository(self.repository, base=self.base)), 1)

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


if __name__ == "__main__":
    unittest.main()