"""Local repository scanner for embedded connection strings and storage account keys.

This complements `check_data_hygiene.py`. Both walk Git blobs directly (working tree
and, optionally, history introduced since a base revision) rather than relying on a
push-time service, so the check is reproducible offline and in CI. It targets task 8.2:
service-to-service access is expected to run entirely on managed identities and any
external secret is expected to come from Key Vault at runtime, so no connection string,
account key, or comparable bearer secret should ever be committed as a literal value.

Detected categories are intentionally narrow and pattern-anchored to avoid flagging the
unrelated base64 and identifier text already common in this repository (object ids,
hashes, tags):

- Storage/Cosmos/Service Bus/Event Hub connection strings carrying `AccountKey=`,
  `SharedAccessKey=`, or `SharedAccessSignature=` in `key=value;` form.
- A bare Azure Storage/Cosmos account key: 88 base64 characters ending in `==`,
  immediately after a `key`-shaped label so an unrelated base64 blob is not matched.
- A SAS query string carrying both a signature (`sig=`) and expiry (`se=`) parameter.
- A PEM-encoded private key block.
- A `client_secret` assignment carrying a non-placeholder literal value.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


DEFAULT_MAX_BYTES = 1024 * 1024

# Non-secret values that legitimately appear in fixtures/docs and must not trip the scanner.
PLACEHOLDER_TOKENS = frozenset({
    "changeme", "placeholder", "example", "redacted", "your-secret-here",
    "<secret>", "***", "******",
})

_KEY_VALUE_PAIR = r"[A-Za-z][A-Za-z0-9]*=[^;\r\n]+"
PATTERNS = (
    ("Azure Storage/Cosmos connection string",
     re.compile(r"(?i)AccountKey=[A-Za-z0-9+/]{20,}={0,2}")),
    ("Service Bus/Event Hub shared access key",
     re.compile(r"(?i)SharedAccessKey=[A-Za-z0-9+/]{20,}={0,2}")),
    ("shared access signature connection string",
     re.compile(r"(?i)SharedAccessSignature=[A-Za-z0-9%+/_.-]{20,}")),
    ("bare storage/Cosmos account key",
     re.compile(r"(?i)(?:account|primary|secondary|storage)[-_]?key[\"']?\s*[:=]\s*"
                r"[\"']?[A-Za-z0-9+/]{86}==")),
    ("SAS query string with signature and expiry",
     re.compile(r"(?i)(?=.*\bsig=[A-Za-z0-9%+/]{16,})(?=.*\bse=[0-9TZ:%-]{6,}).{0,200}")),
    ("PEM private key block",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("client secret literal",
     re.compile(r"(?i)client[-_]?secret[\"']?\s*[:=]\s*[\"']?([^\s\"',;]{8,})")),
)


@dataclass(frozen=True)
class Violation:
    commit: str
    path: str
    reason: str


def _is_placeholder(text: str) -> bool:
    stripped = text.strip().strip("\"'").lower()
    return stripped in PLACEHOLDER_TOKENS or set(stripped) <= {"*"}


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


def find_secrets(text: str) -> list[str]:
    reasons = []
    for label, pattern in PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        group = match.group(1) if match.groups() else match.group(0)
        if _is_placeholder(group):
            continue
        reasons.append(label)
    return reasons


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
            if object_type != b"blob" or int(size) > max_bytes:
                continue
            content = git(repository, "cat-file", "-p", object_id.decode("ascii"))
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for reason in find_secrets(text):
                violations.append(Violation(commit, path, reason))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject committed connection strings and storage/service keys."
    )
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
        print(f"Secret scan could not complete: {error}", file=sys.stderr)
        return 2
    for violation in violations:
        print(f"FAIL {violation.commit[:12]} {violation.path!r}: {violation.reason}")
    if violations:
        print(f"Secret scan failed: {len(violations)} violation(s).")
        return 1
    print("Secret scan passed: no embedded connection string or storage key found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
