"""Reset and diagnose local demo delivery state without touching infrastructure.

Only explicitly named SQLite files and explicitly named directories directly
under ``--state-root`` are removed: no glob, no recursive scan of the root,
and nothing outside those exact names is ever touched. Missing files or
directories are already clean, so an interrupted reset can be diagnosed by
running the command again with ``--diagnose``: each store and directory
reports its own existence and cleanliness independently, and finishing the
reset is idempotent -- a store or directory already removed is left alone.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path


STORE_FILES = (
    "variant_store.sqlite3",
    "metadata_store.sqlite3",
    "staging.sqlite3",
    "landing_inventory.sqlite3",
    "run_history.sqlite3",
    "issues.sqlite3",
)

# Explicitly named, demo-owned directories. Never a glob or a scan of
# --state-root itself: only these exact relative names are ever removed, and
# only when they exist directly under the supplied root.
STORE_DIRECTORIES = (
    "rehearsal-landing",
)


def _table_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


def _directory_file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for candidate in path.rglob("*") if candidate.is_file())


def diagnose(state_root: Path) -> dict:
    stores = []
    for name in STORE_FILES:
        path = state_root / name
        counts = _table_counts(path)
        stores.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "clean": not counts or all(value == 0 for value in counts.values()),
            "table_counts": counts,
        })
    directories = []
    for name in STORE_DIRECTORIES:
        path = state_root / name
        file_count = _directory_file_count(path)
        directories.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "clean": file_count == 0,
            "file_count": file_count,
        })
    return {
        "state_root": str(state_root),
        "infrastructure_touched": False,
        "stores": stores,
        "directories": directories,
        "clean": all(store["clean"] for store in stores)
        and all(directory["clean"] for directory in directories),
    }


def reset(state_root: Path) -> dict:
    before = diagnose(state_root)
    removed_files = []
    for name in STORE_FILES:
        path = state_root / name
        if path.exists():
            path.unlink()
            removed_files.append(name)
    removed_directories = []
    for name in STORE_DIRECTORIES:
        path = state_root / name
        if path.exists():
            shutil.rmtree(path)
            removed_directories.append(name)
    after = diagnose(state_root)
    return {
        "state_root": str(state_root),
        "infrastructure_touched": False,
        "removed": removed_files,
        "removed_directories": removed_directories,
        "before": before,
        "after": after,
        "clean": after["clean"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    state_root = args.state_root.resolve()
    if not state_root.is_dir():
        parser.error(f"state root is not a directory: {state_root}")
    report = diagnose(state_root) if args.diagnose else reset(state_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
