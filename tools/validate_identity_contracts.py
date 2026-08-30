#!/usr/bin/env python3
"""Validate immutable-identity schemas and representative contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def load(name: str) -> dict:
    with (SCHEMAS / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(schema: dict, value: dict) -> None:
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise SystemExit("\n".join(error.message for error in errors))


def main() -> int:
    digest = "a" * 64
    registry = {
        "schemaVersion": "2.0.0",
        "generator": "NL Asset Control",
        "generatedAt": "2026-08-30T20:00:00Z",
        "assetCount": 1,
        "assets": [
            {
                "id": "blueprint-732c2ce454",
                "runtimeId": "blueprint-732c2ce454",
                "assetVersion": f"sha256:{'b' * 64}",
                "name": "Blueprint",
                "type": "icon",
                "status": "active",
                "runtimeStatus": "READY",
                "runtimeStatusReason": "",
                "runtimeFormats": ["svg"],
                "automaticSelection": "ELIGIBLE",
                "automaticSelectionReason": "",
                "derivativePath": "assets/icon/icon/blueprint-732c2ce454/blueprint-732c2ce454.svg",
                "accessibility": {"role": "decorative"},
                "rights": {"status": "approved-runtime-use"},
                "variants": [
                    {
                        "format": "svg",
                        "path": "assets/icon/icon/blueprint-732c2ce454/blueprint-732c2ce454.svg",
                        "objectKey": f"objects/sha256/aa/{digest}.svg",
                        "legacyPath": "assets/icon/icon/blueprint-732c2ce454/blueprint-732c2ce454.svg",
                        "mimeType": "image/svg+xml",
                        "bytes": 1,
                        "sha256": digest,
                    }
                ],
            }
        ],
    }
    release = {
        "schemaVersion": 1,
        "releaseId": "runtime-2026.08.30.1",
        "predecessorReleaseId": "",
        "gitCommit": "c" * 40,
        "manifestSha256": {"assets.json": "D" * 64},
        "objectSha256": ["A" * 64],
        "candidateIdentity": f"sha256:{'e' * 64}",
        "publisherIdentity": "NL Asset Runtime Publisher",
        "rollbackReceiptIdentity": f"sha256:{'f' * 64}",
        "createdAt": "2026-08-30T20:00:00Z",
    }
    validate(load("asset-registry-v2.schema.json"), registry)
    validate(load("runtime-release-v1.schema.json"), release)
    print("Immutable identity contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
