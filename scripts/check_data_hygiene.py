import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import subprocess
import sys


DEFAULT_MAX_BYTES = 1024 * 1024
GENOMIC_SUFFIXES = frozenset(
    {".vcf", ".gvcf", ".bam", ".bai", ".cram", ".crai", ".sam", ".fastq",
     ".fq", ".bcl", ".fasta", ".fa", ".2bit"}
)
COMPRESSION_SUFFIXES = frozenset({".gz", ".bgz", ".bz2", ".xz", ".zst", ".zip"})


@dataclass(frozen=True)
class Violation:
    commit: str
    path: str
    reason: str


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def resolve_commit(repository: Path, revision: str) -> str:
    return git(
        repository, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
    ).decode("ascii").strip()


def is_genomic_path(path: str) -> bool:
    name = PurePosixPath(path.lower()).name
    suffix = PurePosixPath(name).suffix
    while suffix in COMPRESSION_SUFFIXES:
        name = name[:-len(suffix)]
        suffix = PurePosixPath(name).suffix
    return name.endswith(tuple(GENOMIC_SUFFIXES))


def scan_repository(
    repository: Path,
    head: str = "HEAD",
    base: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[Violation]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")
    head_commit = resolve_commit(repository, head)
    commits = [head_commit]
    if base is not None:
        base_commit = resolve_commit(repository, base)
        commits.extend(
            git(repository, "rev-list", f"{base_commit}..{head_commit}")
            .decode("ascii").splitlines()
        )
    violations = []
    seen_entries = set()
    for commit in dict.fromkeys(commits):
        for entry in git(repository, "ls-tree", "-r", "-l", "-z", commit).split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id, size = metadata.split()
            identity = (raw_path, object_id, mode)
            if identity in seen_entries:
                continue
            seen_entries.add(identity)
            path = raw_path.decode("utf-8", errors="backslashreplace")
            if object_type != b"blob":
                violations.append(Violation(commit, path, "uninspectable non-blob entry"))
                continue
            if is_genomic_path(path):
                violations.append(Violation(commit, path, "genomic file extension"))
            if int(size) > max_bytes:
                violations.append(
                    Violation(commit, path, f"{int(size)} bytes exceeds {max_bytes} bytes")
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject genomic and oversized Git blobs.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--base", help="Also scan every commit introduced since this revision.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    arguments = parser.parse_args()
    try:
        violations = scan_repository(
            arguments.repo, arguments.head, arguments.base, arguments.max_bytes
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Data hygiene could not complete: {error}", file=sys.stderr)
        return 2
    for violation in violations:
        print(f"FAIL {violation.commit[:12]} {violation.path!r}: {violation.reason}")
    if violations:
        print(f"Data hygiene failed: {len(violations)} violation(s).")
        return 1
    print(f"Data hygiene passed (maximum {arguments.max_bytes} bytes per file).")
    return 0


if __name__ == "__main__":
    sys.exit(main())