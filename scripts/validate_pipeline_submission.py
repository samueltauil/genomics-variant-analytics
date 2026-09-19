"""Validate supply-chain evidence before a compute allocator can be called."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.supply_chain import verify_submission, verify_gh_attestations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--verify-registry", action="store_true")
    arguments = parser.parse_args()
    try:
        with arguments.submission.open(encoding="utf-8") as source:
            submission = json.load(source)
        verified = verify_submission(submission)
        if arguments.verify_registry:
            verify_gh_attestations(
                verified["image"],
                verified["provenance"]["repository"],
                verified["provenance"]["workflow"],
            )
        print(json.dumps({"compute_allocated": False, "submission": verified}, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Pipeline submission rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
