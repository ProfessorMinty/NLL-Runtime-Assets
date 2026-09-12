#!/usr/bin/env python3
"""Public CI gate: validate runtime semantics without requiring ignored binaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime_validation import validate_runtime

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors, counts = validate_runtime(args.root.resolve(), verify_derivatives=False)
    if errors:
        print(f"NLL Runtime semantic validation FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        "NLL Runtime semantic validation passed without repository-local binaries: "
        f"{counts['assets']} asset(s), {counts['variants']} derivative record(s), "
        f"{counts['collections']} collection(s), {counts['themes']} theme(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
