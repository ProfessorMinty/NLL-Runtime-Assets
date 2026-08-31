#!/usr/bin/env python3
"""Private integrity gate: validate semantics and every local derivative byte."""

from __future__ import annotations

import sys
from pathlib import Path

from runtime_validation import validate_runtime

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors, counts = validate_runtime(ROOT, verify_derivatives=True)
    if errors:
        print(f"NLL Runtime private integrity validation FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        "NLL Runtime private integrity validation passed: "
        f"{counts['assets']} asset(s), {counts['variants']} derivative(s), "
        f"{counts['collections']} collection(s), {counts['themes']} theme(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
