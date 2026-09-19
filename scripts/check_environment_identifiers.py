"""Fail when tracked files contain live Azure environment identifiers.

The check examines only files tracked by Git. Local environment records belong
under the ignored ``.azure`` directory and must not affect a clean clone.
Examples may use explicit placeholders such as ``<subscription-id>``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


IDENTIFIER_FIELDS = re.compile(
    r"""(?ix)
    (?:
        ["']?(?:subscription|tenant)(?:[_-]?id)?["']?\s*[:=]\s*["']?
        |
        /subscriptions/
    )
    [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}
    """
)


def tracked_files(repository_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return [
        repository_root / entry.decode("utf-8")
        for entry in result.stdout.split(b"\0")
        if entry
    ]


def find_identifiers(repository_root: Path) -> list[str]:
    findings = []
    for path in tracked_files(repository_root):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if IDENTIFIER_FIELDS.search(line):
                findings.append(f"{path.relative_to(repository_root)}:{line_number}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    findings = find_identifiers(root)
    if findings:
        print("Tracked Azure environment identifiers found:")
        print("\n".join(findings))
        return 1
    print("No tracked Azure subscription or tenant identifiers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
