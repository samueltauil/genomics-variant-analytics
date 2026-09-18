"""Stage a metadata-only synthetic demo run in an instrument-style landing layout."""

import argparse
import json
from pathlib import Path, PurePosixPath
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.demo_dataset_manifest import _load, validate_manifest
    from scripts.scan_landing import DEFAULT_PATTERN, local_path, scan_once
except ModuleNotFoundError:
    from demo_dataset_manifest import _load, validate_manifest
    from scan_landing import DEFAULT_PATTERN, local_path, scan_once


DEFAULT_RUN_ID = "SYN-RUN-001"
INSTRUMENT_RELATIVE_ROOT = PurePosixPath("Data/Intensities/BaseCalls")
PLACEHOLDER_BYTES = b"synthetic metadata-only landing placeholder\n"


def expected_layout(manifest, run_id=DEFAULT_RUN_ID):
    """Return the exact synthetic file paths derived from manifest identities."""
    validate_manifest(manifest)
    if not isinstance(run_id, str) or not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be a nonempty single path component.")

    paths = []
    for index, identity in enumerate(manifest["identities"], start=1):
        for read in (1, 2):
            relative = PurePosixPath(run_id) / INSTRUMENT_RELATIVE_ROOT / (
                f"{identity['sample_id']}_S{index}_L001_R{read}_001.fastq.gz"
            )
            paths.append({
                "relative_path": relative.as_posix(),
                "run_id": run_id,
                "sample_id": identity["sample_id"],
                "read": read,
            })
    return paths


def _write_placeholder(root, relative_path):
    destination = root.joinpath(*PurePosixPath(relative_path).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file():
            raise ValueError(f"Expected a regular file at {relative_path}.")
        if destination.read_bytes() != PLACEHOLDER_BYTES:
            raise ValueError(f"Existing file is not the generated placeholder: {relative_path}.")
    else:
        destination.write_bytes(PLACEHOLDER_BYTES)


def stage_manifest(manifest_path, root, inventory, run_id=DEFAULT_RUN_ID):
    """Generate the synthetic layout and verify it through the landing scanner."""
    manifest_path = Path(manifest_path)
    manifest = _load(manifest_path)
    expected = expected_layout(manifest, run_id)

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    root = local_path(root)
    inventory = local_path(inventory)
    if root in inventory.parents or inventory == root:
        raise ValueError("Inventory must be outside the landing root.")

    for entry in expected:
        _write_placeholder(root, entry["relative_path"])

    first_report = scan_once(root, inventory, DEFAULT_PATTERN)
    second_report = scan_once(root, inventory, DEFAULT_PATTERN)
    expected_paths = [entry["relative_path"] for entry in expected]
    observed_paths = [record["path"] for record in second_report["files"]]
    if observed_paths != sorted(expected_paths):
        raise ValueError("Scanner output does not match the manifest-defined layout.")
    if any(record["path"] != record["path"].replace("\\", "/")
           for record in second_report["files"]):
        raise ValueError("Scanner rewrote a source path.")
    if any(record["state"] != "complete" for record in second_report["files"]):
        raise ValueError("Manifest-defined files did not reach complete state.")

    return {
        "manifest_id": manifest["manifest_id"],
        "run_id": run_id,
        "reference_build": manifest["reference"]["build"],
        "reference_version": manifest["reference"]["immutable_source_version"],
        "identity_count": len(manifest["identities"]),
        "file_count": len(expected),
        "placeholder_bytes": len(PLACEHOLDER_BYTES),
        "paths_preserved": True,
        "first_scan_file_count": first_report["file_count"],
        "verified": True,
        "files": second_report["files"],
    }


def main():
    default_manifest = Path(__file__).resolve().parents[1] / "demo" / "dataset-manifest.json"
    parser = argparse.ArgumentParser(
        description="Generate and verify a metadata-only synthetic instrument landing layout."
    )
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    arguments = parser.parse_args()
    try:
        report = stage_manifest(
            arguments.manifest, arguments.root, arguments.inventory, arguments.run_id
        )
    except (OSError, ValueError):
        print("Demo landing staging failed.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
