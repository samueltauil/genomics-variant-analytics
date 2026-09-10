import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
from string import Formatter
import sys
import time


DEFAULT_PATTERN = (
    r"(?P<run_id>[^/]+)/(?:.*/)?(?P<sample_id>[^/]+)"
    r"_S[0-9]+_L[0-9]{3}_R[12]_[0-9]{3}\.fastq(?:\.gz)?"
)


def is_redirected(metadata):
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def local_path(value):
    raw = os.fspath(value)
    path = Path(raw)
    if raw.replace("\\", "/").startswith("//") or not path.is_absolute():
        raise ValueError("An absolute local path is required; UNC/device paths are prohibited.")
    if ".." in path.parts:
        raise ValueError("Parent traversal is prohibited.")
    if os.name == "nt":
        import ctypes

        get_drive_type = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        if get_drive_type(path.anchor) != 3:
            raise ValueError("Only a fixed local drive is supported.")
    for ancestor in (*reversed(path.parents), path):
        try:
            metadata = ancestor.lstat()
        except FileNotFoundError:
            if ancestor == path:
                break
            raise
        if is_redirected(metadata):
            raise ValueError("Symbolic links and reparse points are prohibited.")
    return path


def marker_path(template, values):
    for _, field, format_spec, conversion in Formatter().parse(template):
        if field is not None and (
            field not in {"run_id", "sample_id", "path"} or format_spec or conversion
        ):
            raise ValueError("Marker template supports only run_id, sample_id and path fields.")
    relative = template.format(**values)
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/"):
        raise ValueError("Completion marker must be a relative path inside the landing root.")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError("Completion marker cannot contain empty or dot path segments.")
    return PurePosixPath(relative).as_posix()


def scan_once(root, inventory, pattern=DEFAULT_PATTERN, completion_marker=None):
    root = local_path(root)
    inventory = local_path(inventory)
    if not root.is_dir():
        raise ValueError("Landing root must be an existing directory.")
    if inventory == root or root in inventory.parents:
        raise ValueError("Inventory must be outside the landing root.")
    matcher = re.compile(pattern)
    if not {"run_id", "sample_id"}.issubset(matcher.groupindex):
        raise ValueError("Path pattern requires named run_id and sample_id groups.")
    if completion_marker is not None:
        marker_path(completion_marker, {"run_id": "run", "sample_id": "sample", "path": "file"})
    observed_at = datetime.now(timezone.utc).isoformat()
    observations = []

    def walk_error(error):
        raise error

    for directory, folders, filenames in os.walk(root, onerror=walk_error, followlinks=False):
        folders.sort()
        for name in sorted(folders + filenames):
            path = Path(directory) / name
            metadata = path.lstat()
            if is_redirected(metadata):
                raise ValueError("Symbolic links and reparse points are prohibited.")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Only regular files and directories can be inventoried.")
            relative = path.relative_to(root).as_posix()
            match = matcher.fullmatch(relative)
            run_id = match.group("run_id") if match else None
            sample_id = match.group("sample_id") if match else None
            parsed = bool(run_id and sample_id)
            observations.append((
                relative, run_id if parsed else None, sample_id if parsed else None,
                metadata.st_size, metadata.st_mtime_ns, observed_at, observed_at,
                None if parsed else "unrecognized-path",
            ))

    connection = sqlite3.connect(inventory)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS source (root TEXT PRIMARY KEY, pattern TEXT NOT NULL)")
            if "completion_marker" not in {row["name"] for row in connection.execute("PRAGMA table_info(source)")}:
                connection.execute("ALTER TABLE source ADD COLUMN completion_marker TEXT")
            binding = connection.execute("SELECT root, pattern, completion_marker FROM source").fetchall()
            if binding and [tuple(row) for row in binding] != [(str(root), pattern, completion_marker)]:
                raise ValueError("Inventory is already bound to a different root, path pattern or completion marker.")
            connection.execute("INSERT OR IGNORE INTO source VALUES (?, ?, ?)", (str(root), pattern, completion_marker))
            connection.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, run_id TEXT, sample_id TEXT,
                    size_bytes INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
                    arrival_timestamp TEXT NOT NULL, last_seen_timestamp TEXT NOT NULL,
                    metadata_error TEXT, state TEXT NOT NULL DEFAULT 'arriving',
                    present INTEGER NOT NULL DEFAULT 1
                )
            """)
            previous = {row["path"]: dict(row) for row in connection.execute("SELECT * FROM files")}
            by_path = {observation[0]: observation for observation in observations}
            markers = {}
            if completion_marker is not None:
                for relative, run_id, sample_id, *_, metadata_error in observations:
                    if metadata_error is None:
                        markers[relative] = marker_path(completion_marker, {
                            "run_id": run_id, "sample_id": sample_id, "path": relative,
                        })
                if any(relative == marker for relative, marker in markers.items()):
                    raise ValueError("A file cannot be its own completion marker.")
            marker_paths = frozenset(markers.values())
            evaluated = []
            for observation in observations:
                relative, _, _, size_bytes, modified_ns, _, _, metadata_error = observation
                prior = previous.get(relative)
                stable = (
                    prior is not None and prior["present"] and metadata_error is None
                    and prior["size_bytes"] == size_bytes and prior["modified_ns"] == modified_ns
                )
                marker = by_path.get(markers.get(relative))
                marked = marker is not None and marker[4] >= modified_ns
                complete = metadata_error is None and relative not in marker_paths and (stable or marked)
                evaluated.append((*observation, "complete" if complete else "arriving"))
            connection.execute("UPDATE files SET present = 0, state = 'arriving'")
            connection.executemany("""
                INSERT INTO files (
                    path, run_id, sample_id, size_bytes, modified_ns,
                    arrival_timestamp, last_seen_timestamp, metadata_error, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    run_id = excluded.run_id, sample_id = excluded.sample_id,
                    size_bytes = excluded.size_bytes, modified_ns = excluded.modified_ns,
                    last_seen_timestamp = excluded.last_seen_timestamp,
                    metadata_error = excluded.metadata_error, state = excluded.state, present = 1
            """, evaluated)
            records = [dict(row) for row in connection.execute("SELECT * FROM files ORDER BY path")]
        for record in records:
            record["present"] = bool(record["present"])
        return {
            "schema_version": 2, "mode": "local-only", "observed_at": observed_at,
            "file_count": len(observations), "files": records,
            "completeness_evaluated": True, "azure_readiness": "not-evaluated",
        }
    finally:
        connection.close()


def poll_inventory(root, inventory, pattern=DEFAULT_PATTERN, polls=1, interval_seconds=60,
                   completion_marker=None):
    if isinstance(polls, bool) or not isinstance(polls, int) or polls < 1:
        raise ValueError("Poll count must be a positive integer.")
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("Poll interval must be finite and positive.")
    for poll_index in range(polls):
        if poll_index:
            time.sleep(interval_seconds)
        yield scan_once(root, inventory, pattern, completion_marker)


def main():
    parser = argparse.ArgumentParser(description="Inventory a trusted local landing directory without reading file contents.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--path-pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--completion-marker", help="Root-relative vendor marker template, e.g. {run_id}/RTAComplete.txt")
    parser.add_argument("--polls", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=60)
    arguments = parser.parse_args()
    try:
        for report in poll_inventory(
            arguments.root, arguments.inventory, arguments.path_pattern,
            arguments.polls, arguments.interval_seconds,
            arguments.completion_marker,
        ):
            print(json.dumps(report), flush=True)
    except (OSError, ValueError, re.error, sqlite3.Error) as error:
        print(f"Landing scan failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())