#!/usr/bin/env python3
"""Validate NLL runtime manifests, schemas, references, and published derivatives."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "manifests"
SCHEMA_DIR = ROOT / "schemas"

MANIFESTS = {
    "index": (MANIFEST_DIR / "index.json", SCHEMA_DIR / "manifest-index.schema.json"),
    "assets": (MANIFEST_DIR / "assets.json", SCHEMA_DIR / "asset-registry.schema.json"),
    "collections": (MANIFEST_DIR / "collections.json", SCHEMA_DIR / "collections.schema.json"),
    "themes": (MANIFEST_DIR / "themes.json", SCHEMA_DIR / "themes.schema.json"),
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_schema(name: str, manifest: dict, schema: dict, errors: list[str]) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(manifest), key=lambda e: list(e.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{name}: schema error at {location}: {error.message}")


def require_unique(items: list[dict], key: str, label: str, errors: list[str]) -> set[str]:
    seen: set[str] = set()
    for item in items:
        value = item.get(key)
        if value in seen:
            errors.append(f"{label}: duplicate {key} '{value}'")
        seen.add(value)
    return seen


def require_sorted(ids: list[str], label: str, errors: list[str]) -> None:
    if ids != sorted(ids):
        errors.append(f"{label}: records must be sorted by stable ID for deterministic output")


def validate_relative_path(relative: str, label: str, errors: list[str]) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        errors.append(f"{label}: invalid runtime path '{relative}'")
        return None
    return ROOT / candidate


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    errors: list[str] = []
    loaded: dict[str, dict] = {}

    for name, (manifest_path, schema_path) in MANIFESTS.items():
        try:
            manifest = load_json(manifest_path)
            schema = load_json(schema_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: unable to load JSON: {exc}")
            continue

        loaded[name] = manifest
        validate_schema(name, manifest, schema, errors)

    if set(loaded) != set(MANIFESTS):
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    index = loaded["index"]
    assets_manifest = loaded["assets"]
    collections_manifest = loaded["collections"]
    themes_manifest = loaded["themes"]

    # Manifest index must point to real files inside manifests/.
    for key, relative in index["manifests"].items():
        target = MANIFEST_DIR / relative
        if not target.is_file():
            errors.append(f"index: {key} manifest target does not exist: manifests/{relative}")

    assets = assets_manifest["assets"]
    collections = collections_manifest["collections"]
    themes = themes_manifest["themes"]

    if assets_manifest["assetCount"] != len(assets):
        errors.append("assets: assetCount does not match assets array length")
    if collections_manifest["collectionCount"] != len(collections):
        errors.append("collections: collectionCount does not match collections array length")
    if themes_manifest["themeCount"] != len(themes):
        errors.append("themes: themeCount does not match themes array length")

    asset_ids = require_unique(assets, "id", "assets", errors)
    collection_ids = require_unique(collections, "id", "collections", errors)
    require_unique(themes, "id", "themes", errors)

    require_sorted([item["id"] for item in assets], "assets", errors)
    require_sorted([item["id"] for item in collections], "collections", errors)
    require_sorted([item["id"] for item in themes], "themes", errors)

    if assets and assets_manifest["generatedAt"] is None:
        errors.append("assets: generatedAt must be populated when published assets exist")

    # Verify every published derivative exists and matches its integrity metadata.
    published_paths: set[str] = set()
    for asset in assets:
        for variant in asset["variants"]:
            relative = variant["path"]
            if relative in published_paths:
                errors.append(f"assets: duplicate derivative path '{relative}'")
            published_paths.add(relative)

            runtime_path = validate_relative_path(relative, f"asset {asset['id']}", errors)
            if runtime_path is None:
                continue
            if not runtime_path.is_file():
                errors.append(f"asset {asset['id']}: derivative missing: {relative}")
                continue

            actual_bytes = runtime_path.stat().st_size
            if actual_bytes != variant["bytes"]:
                errors.append(
                    f"asset {asset['id']}: byte count mismatch for {relative}: "
                    f"manifest={variant['bytes']} actual={actual_bytes}"
                )

            actual_sha = hash_file(runtime_path)
            if actual_sha.lower() != variant["sha256"].lower():
                errors.append(f"asset {asset['id']}: SHA-256 mismatch for {relative}")

    # Collections may only reference published asset IDs.
    for collection in collections:
        for asset_id in collection["assetIds"]:
            if asset_id not in asset_ids:
                errors.append(
                    f"collection {collection['id']}: unknown asset ID '{asset_id}'"
                )

    # Themes may only reference published collections/assets.
    for theme in themes:
        for collection_id in theme.get("collectionIds", []):
            if collection_id not in collection_ids:
                errors.append(
                    f"theme {theme['id']}: unknown collection ID '{collection_id}'"
                )

        for slot, value in theme["assetSlots"].items():
            values = value if isinstance(value, list) else [value]
            for asset_id in values:
                if asset_id not in asset_ids:
                    errors.append(
                        f"theme {theme['id']} slot {slot}: unknown asset ID '{asset_id}'"
                    )

    if errors:
        print(f"NLL Runtime validation FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        "NLL Runtime validation passed: "
        f"{len(assets)} asset(s), {len(collections)} collection(s), "
        f"{len(themes)} theme(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
