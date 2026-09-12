#!/usr/bin/env python3
"""Verify the immutable offline dependency set used by retained V1 validation."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


WHEELS = {
    "attrs-26.1.0-py3-none-any.whl": (67548, "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309"),
    "jsonschema-4.26.0-py3-none-any.whl": (90630, "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce"),
    "jsonschema_specifications-2025.9.1-py3-none-any.whl": (18437, "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe"),
    "referencing-0.37.0-py3-none-any.whl": (26766, "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231"),
    "rfc3339_validator-0.1.4-py2.py3-none-any.whl": (3490, "24f6ec1eda14ef823da9e36ec7113124b39c04d50a4d3d3a3c2859577e7791fa"),
    "rpds_py-2026.6.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": (366189, "ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6"),
    "six-1.17.0-py2.py3-none-any.whl": (11050, "4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274"),
    "typing_extensions-4.16.0-py3-none-any.whl": (45571, "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8"),
}
REQUIREMENTS_SIZE = 11473
REQUIREMENTS_SHA256 = "580b1b8d109c9c4d44ab93b7b023e60307a68d0dbb8961736a37197a67f07e88"


class WheelhouseError(RuntimeError):
    """The retained V1 wheelhouse differs from reviewed authority."""


def verify(root: Path) -> None:
    reviewed_root = root.resolve()
    requirements = reviewed_root / "requirements-ci.txt"
    if not requirements.is_file() or requirements.is_symlink():
        raise WheelhouseError("The immutable V1 requirements file is unavailable.")
    requirements_bytes = requirements.read_bytes()
    if (
        len(requirements_bytes) != REQUIREMENTS_SIZE
        or hashlib.sha256(requirements_bytes).hexdigest() != REQUIREMENTS_SHA256
    ):
        raise WheelhouseError("The immutable V1 requirements identity differs.")

    wheelhouse = reviewed_root / "ci" / "wheelhouse"
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise WheelhouseError("The immutable V1 wheelhouse directory is unavailable.")
    entries = list(wheelhouse.iterdir())
    if {entry.name for entry in entries} != set(WHEELS):
        raise WheelhouseError("The immutable V1 wheelhouse file set differs.")
    for entry in entries:
        if not entry.is_file() or entry.is_symlink():
            raise WheelhouseError("An immutable V1 wheelhouse entry is not a normal file.")
        expected_size, expected_sha256 = WHEELS[entry.name]
        data = entry.read_bytes()
        if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise WheelhouseError("An immutable V1 wheelhouse identity differs.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        verify(args.root)
    except (OSError, ValueError, WheelhouseError):
        print("Immutable V1 wheelhouse verification FAILED.", file=sys.stderr)
        return 1
    print("Immutable V1 wheelhouse verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
