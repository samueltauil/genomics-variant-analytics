"""Reset and diagnose local demo delivery state without touching infrastructure.

Only explicitly named SQLite files directly under ``--state-root`` are removed.
Missing files are already clean, so an interrupted reset can be diagnosed by
running the command again with ``--diagnose``.
"""

from __future__ import annotations

import argparse
import json
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
    return {
        "state_root": str(state_root),
        "infrastructure_touched": False,
        "stores": stores,
        "clean": all(store["clean"] for store in stores),
    }


def reset(state_root: Path) -> dict:
    before = diagnose(state_root)
    removed = []
    for name in STORE_FILES:
        path = state_root / name
        if path.exists():
            path.unlink()
            removed.append(name)
    after = diagnose(state_root)
    return {
        "state_root": str(state_root),
        "infrastructure_touched": False,
        "removed": removed,
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
