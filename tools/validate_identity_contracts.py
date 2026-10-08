#!/usr/bin/env python3
"""Validate immutable-identity schemas and representative contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from validate_runtime_release import expected_consumer_asset_version

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
        "releaseId": "runtime-v1-2026.08.30.1",
        "predecessorReleaseId": "",
        "consumerCatalog": {
            "schemaVersion": "1.0.0",
            "path": "manifests/releases/runtime-v1-2026.08.30.1/consumer-catalog.json",
            "sha256": "d" * 64,
        },
        "objects": [
            {
                "objectKey": f"objects/sha256/aa/{digest}.svg",
                "url": f"https://cdn.nlightlabs.com/objects/sha256/aa/{digest}.svg",
                "sha256": digest,
                "bytes": 1,
            }
        ],
        "candidateIdentity": f"sha256:{'e' * 64}",
        "publisherIdentity": "NL Asset Runtime Publisher",
        "publicationAuthorizationIdentity": f"sha256:{'c' * 64}",
        "transactionRecoveryAuthorizationIdentity": f"sha256:{'f' * 64}",
        "createdAt": "2026-08-30T20:00:00Z",
    }
    pointer = {
        "schemaVersion": 1,
        "releaseId": "runtime-v1-2026.08.30.1",
        "predecessorReleaseId": "",
        "releaseArtifactCommit": "c" * 40,
        "catalogPath": "manifests/releases/runtime-v1-2026.08.30.1/consumer-catalog.json",
        "catalogSha256": "d" * 64,
        "catalogSchemaVersion": "1.0.0",
        "publicationAuthorizationIdentity": f"sha256:{'c' * 64}",
    }
    consumer_catalog = {
        "schemaVersion": "1.0.0",
        "releaseId": "runtime-v1-2026.08.30.1",
        "generatedAt": "2026-08-30T20:00:00Z",
        "assetCount": 1,
        "assets": [
            {
                "assetId": "fixture-asset",
                "assetVersion": "sha256:5fda50d42d908671b9e8dfb9eeebc0af3a7a7e311fdafb8996ae2a799beb54f9",
                "releaseId": "runtime-v1-2026.08.30.1",
                "displayName": "Fixture Asset",
                "type": "illustration",
                "subtype": None,
                "tags": ["fixture"],
                "themes": [],
                "subjects": [],
                "styles": [],
                "useCases": [],
                "accessibility": {"role": "decorative", "alt": ""},
                "publicCredit": None,
                "readinessStatus": "READY",
                "deprecated": False,
                "fallbackAssetId": None,
                "sanitizedProvenance": {"sourceLabel": "Non-sensitive test fixture"},
                "variants": [
                    {
                        "format": "webp",
                        "objectKey": f"objects/sha256/aa/{digest}.webp",
                        "url": f"https://cdn.nlightlabs.com/objects/sha256/aa/{digest}.webp",
                        "mimeType": "image/webp",
                        "bytes": 12,
                        "width": 1,
                        "height": 1,
                        "sha256": digest,
                    }
                ],
            }
        ],
    }
    validate(load("asset-registry-v2.schema.json"), registry)
    validate(load("nl-asset-consumer-catalog-v1.schema.json"), consumer_catalog)
    expected_version = expected_consumer_asset_version(consumer_catalog["assets"][0])
    if consumer_catalog["assets"][0]["assetVersion"] != expected_version:
        raise RuntimeError("Shared NLAssetConsumerAssetVersionMaterialV1 fixture hash drifted.")
    validate(load("runtime-release-v1.schema.json"), release)
    validate(load("runtime-current-pointer-v1.schema.json"), pointer)
    date_time_probe = {
        "type": "object",
        "required": ["createdAt"],
        "properties": {"createdAt": {"type": "string", "format": "date-time"}},
    }
    if not list(
        Draft202012Validator(
            date_time_probe, format_checker=FormatChecker()
        ).iter_errors({"createdAt": "definitely-not-a-date"})
    ):
        raise RuntimeError("RFC 3339 date-time format validation dependency is unavailable.")
    print("Immutable identity contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
