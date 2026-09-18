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

MANIFEST_MAX_BYTES = 1 << 20


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


def manifest_matcher(template):
    """Compile a transfer-manifest template so a manifest is found even when no file of its run arrived."""
    marker_path(template, {"run_id": "run", "sample_id": "sample", "path": "file"})
    fields = [field for _, field, _, _ in Formatter().parse(template) if field is not None]
    if fields != ["run_id"]:
        raise ValueError("Transfer manifest template must use {run_id} exactly once.")
    prefix, _, suffix = template.partition("{run_id}")
    return re.compile("%s(?P<run_id>[^/]+)%s" % (re.escape(prefix), re.escape(suffix)))


def parse_transfer_manifest(payload, run_id, manifest_path):
    """Return the declared byte size of each file the named run promises to deliver."""
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict) or set(document) != {"run_id", "files"}:
        raise ValueError("Transfer manifest must be an object with exactly run_id and files.")
    if document["run_id"] != run_id:
        raise ValueError("Transfer manifest run_id does not match the run in its own path.")
    entries = document["files"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Transfer manifest files must be a non-empty list.")
    declared = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size_bytes"}:
            raise ValueError("Each transfer manifest entry needs exactly path and size_bytes.")
        path, size_bytes = entry["path"], entry["size_bytes"]
        if not isinstance(path, str) or isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise ValueError("Transfer manifest path must be text and size_bytes an integer.")
        if size_bytes < 0:
            raise ValueError("Transfer manifest size_bytes cannot be negative.")
        if "\\" in path or ":" in path or path.startswith("/") or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            raise ValueError("Transfer manifest paths must be relative to the landing root.")
        if path.split("/")[0] != run_id:
            raise ValueError("A run manifest may only declare files of its own run.")
        if path == manifest_path:
            raise ValueError("A transfer manifest cannot declare itself.")
        if path in declared:
            raise ValueError("Transfer manifest declares %s more than once." % path)
        declared[path] = size_bytes
    return declared


def read_transfer_manifests(read_bytes, template, observations):
    """Resolve every observed transfer manifest, keeping a rejected manifest from declaring anything."""
    matcher = manifest_matcher(template)
    declarations, errors = {}, {}
    for relative, _, _, size_bytes, *_ in observations:
        match = matcher.fullmatch(relative)
        if not match:
            continue
        run_id = match.group("run_id")
        try:
            if size_bytes > MANIFEST_MAX_BYTES:
                raise ValueError("Transfer manifest exceeds %d bytes." % MANIFEST_MAX_BYTES)
            declarations.update(parse_transfer_manifest(read_bytes(relative), run_id, relative))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            errors[run_id] = str(error)
    return declarations, errors


def elapsed_seconds(since, observed_at):
    return (datetime.fromisoformat(observed_at) - datetime.fromisoformat(since)).total_seconds()


def add_columns(connection, table, columns):
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(%s)" % table)}
    for name, definition in columns:
        if name not in existing:
            connection.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, definition))


def available_for_staging(report):
    """Return only the paths a staging run may copy; arriving and failed files are withheld."""
    return [
        record["path"] for record in report["files"]
        if record["state"] == "complete" and not record["metadata_error"]
    ]


def scan_once(root, inventory, pattern=DEFAULT_PATTERN, completion_marker=None,
              transfer_manifest=None, stall_seconds=None):
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
    if transfer_manifest is not None:
        manifest_matcher(transfer_manifest)
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

    declarations, manifest_errors = {}, {}
    if transfer_manifest is not None:
        declarations, manifest_errors = read_transfer_manifests(
            lambda relative: (root / relative).read_bytes(), transfer_manifest, observations,
        )

    return evaluate_inventory(
        observations, inventory, str(root), pattern, completion_marker, observed_at,
        transfer_manifest=transfer_manifest, stall_seconds=stall_seconds,
        declarations=declarations, manifest_errors=manifest_errors,
    )


def evaluate_inventory(observations, inventory, source_key, pattern, completion_marker,
                       observed_at, mode="local-only", transfer_manifest=None,
                       stall_seconds=None, declarations=None, manifest_errors=None):
    """Apply the completeness and failure rules to observations from any landing-zone source."""
    if stall_seconds is not None and (
        isinstance(stall_seconds, bool) or not isinstance(stall_seconds, (int, float))
        or not math.isfinite(stall_seconds) or stall_seconds <= 0
    ):
        raise ValueError("Stall deadline must be finite and positive.")
    if transfer_manifest is not None and stall_seconds is None:
        raise ValueError("A transfer manifest requires a stall deadline before failure is declared.")
    declarations = dict(declarations or {})
    manifest_errors = dict(manifest_errors or {})
    connection = sqlite3.connect(inventory)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS source (root TEXT PRIMARY KEY, pattern TEXT NOT NULL)")
            add_columns(connection, "source", [
                ("completion_marker", "TEXT"), ("transfer_manifest", "TEXT"), ("stall_seconds", "REAL"),
            ])
            configuration = (source_key, pattern, completion_marker, transfer_manifest, stall_seconds)
            binding = connection.execute(
                "SELECT root, pattern, completion_marker, transfer_manifest, stall_seconds FROM source"
            ).fetchall()
            if binding and [tuple(row) for row in binding] != [configuration]:
                raise ValueError(
                    "Inventory is already bound to a different root, path pattern, completion marker, "
                    "transfer manifest or stall deadline."
                )
            connection.execute("INSERT OR IGNORE INTO source VALUES (?, ?, ?, ?, ?)", configuration)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, run_id TEXT, sample_id TEXT,
                    size_bytes INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
                    arrival_timestamp TEXT NOT NULL, last_seen_timestamp TEXT NOT NULL,
                    metadata_error TEXT, state TEXT NOT NULL DEFAULT 'arriving',
                    present INTEGER NOT NULL DEFAULT 1
                )
            """)
            add_columns(connection, "files", [
                ("failure_reason", "TEXT"), ("unchanged_since", "TEXT"), ("declared_size_bytes", "INTEGER"),
            ])
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
            declared_runs = {run_id for run_id in manifest_errors}
            declared_runs.update(path.split("/")[0] for path in declarations)
            evaluated = []
            for observation in observations:
                relative, run_id, sample_id, size_bytes, modified_ns, arrival, last_seen, metadata_error = observation
                if metadata_error is None and transfer_manifest is not None and (
                    run_id in manifest_errors or run_id not in declared_runs
                ):
                    manifest_errors.setdefault(run_id, "Transfer manifest was not found for this run.")
                    metadata_error = "manifest-unavailable"
                prior = previous.get(relative)
                unchanged = (
                    prior is not None and prior["present"]
                    and prior["size_bytes"] == size_bytes and prior["modified_ns"] == modified_ns
                )
                unchanged_since = prior["unchanged_since"] if unchanged and prior["unchanged_since"] else observed_at
                stalled = stall_seconds is not None and elapsed_seconds(unchanged_since, observed_at) >= stall_seconds
                declared = declarations.get(relative)
                marker = by_path.get(markers.get(relative))
                marked = marker is not None and marker[4] >= modified_ns
                state, failure_reason = "arriving", None
                if metadata_error is not None:
                    pass
                elif declared is not None and size_bytes > declared:
                    state, failure_reason = "failed", "size-exceeds-declared"
                elif declared is not None and size_bytes < declared:
                    if stalled:
                        state, failure_reason = "failed", "incomplete-transfer"
                elif relative not in marker_paths and (unchanged or marked):
                    state = "complete"
                evaluated.append((
                    relative, run_id, sample_id, size_bytes, modified_ns, arrival, last_seen,
                    metadata_error, state, failure_reason, unchanged_since, declared, 1,
                ))

            matcher = re.compile(pattern)
            for path in sorted(set(declarations) - set(by_path)):
                prior = previous.get(path)
                absent_before = prior is not None and not prior["present"]
                unchanged_since = (
                    prior["unchanged_since"] if absent_before and prior["unchanged_since"] else observed_at
                )
                stalled = stall_seconds is not None and elapsed_seconds(unchanged_since, observed_at) >= stall_seconds
                match = matcher.fullmatch(path)
                evaluated.append((
                    path,
                    match.group("run_id") if match else path.split("/")[0],
                    match.group("sample_id") if match else None,
                    prior["size_bytes"] if prior else 0,
                    prior["modified_ns"] if prior else 0,
                    prior["arrival_timestamp"] if prior else observed_at,
                    observed_at, None,
                    "failed" if stalled else "arriving",
                    "missing-transfer" if stalled else None,
                    unchanged_since, declarations[path], 0,
                ))

            connection.execute("UPDATE files SET present = 0, state = 'arriving', failure_reason = NULL")
            connection.executemany("""
                INSERT INTO files (
                    path, run_id, sample_id, size_bytes, modified_ns,
                    arrival_timestamp, last_seen_timestamp, metadata_error, state,
                    failure_reason, unchanged_since, declared_size_bytes, present
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    run_id = excluded.run_id, sample_id = excluded.sample_id,
                    size_bytes = excluded.size_bytes, modified_ns = excluded.modified_ns,
                    last_seen_timestamp = excluded.last_seen_timestamp,
                    metadata_error = excluded.metadata_error, state = excluded.state,
                    failure_reason = excluded.failure_reason, unchanged_since = excluded.unchanged_since,
                    declared_size_bytes = excluded.declared_size_bytes, present = excluded.present
            """, evaluated)
            records = [dict(row) for row in connection.execute("SELECT * FROM files ORDER BY path")]
        for record in records:
            record["present"] = bool(record["present"])
        return {
            "schema_version": 3, "mode": mode, "observed_at": observed_at,
            "file_count": len(observations), "files": records,
            "completeness_evaluated": True,
            "failure_detection": "declared-size" if transfer_manifest is not None else "not-evaluated",
            "stall_seconds": stall_seconds,
            "manifest_errors": manifest_errors,
            "failed_count": sum(1 for record in records if record["state"] == "failed"),
            "azure_readiness": "not-evaluated",
        }
    finally:
        connection.close()


def poll_inventory(root, inventory, pattern=DEFAULT_PATTERN, polls=1, interval_seconds=60,
                   completion_marker=None, transfer_manifest=None, stall_seconds=None):
    if isinstance(polls, bool) or not isinstance(polls, int) or polls < 1:
        raise ValueError("Poll count must be a positive integer.")
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("Poll interval must be finite and positive.")
    for poll_index in range(polls):
        if poll_index:
            time.sleep(interval_seconds)
        yield scan_once(root, inventory, pattern, completion_marker, transfer_manifest, stall_seconds)


def main():
    parser = argparse.ArgumentParser(description="Inventory a trusted local landing directory without reading file contents.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--path-pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--completion-marker", help="Root-relative vendor marker template, e.g. {run_id}/RTAComplete.txt")
    parser.add_argument("--transfer-manifest", help="Root-relative manifest template, e.g. {run_id}/transfer-manifest.json")
    parser.add_argument("--stall-seconds", type=float, help="Seconds a short or absent declared file may stay unchanged before it is failed")
    parser.add_argument("--polls", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=60)
    arguments = parser.parse_args()
    try:
        for report in poll_inventory(
            arguments.root, arguments.inventory, arguments.path_pattern,
            arguments.polls, arguments.interval_seconds,
            arguments.completion_marker, arguments.transfer_manifest, arguments.stall_seconds,
        ):
            print(json.dumps(report), flush=True)
    except (OSError, ValueError, re.error, sqlite3.Error) as error:
        print(f"Landing scan failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())