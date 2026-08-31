#!/usr/bin/env python3
"""Public CI gate: validate runtime semantics without requiring ignored binaries."""

from __future__ import annotations

import sys
from pathlib import Path

from runtime_validation import validate_runtime

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors, counts = validate_runtime(ROOT, verify_derivatives=False)
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
