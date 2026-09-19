#!/usr/bin/env python3
"""Nextflow bin: quality-control stage."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.secondary_pipeline import StageFailure, run_quality_control  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--force-fail", action="store_true")
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    try:
        result = run_quality_control(
            Path(manifest["reads_r1"]), Path(manifest["reads_r2"]), Path("."),
            force_fail=arguments.force_fail,
        )
    except StageFailure as failure:
        print(str(failure), file=sys.stderr)
        return 1

    print(json.dumps({"report_path": str(result["report_path"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())