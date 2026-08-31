#!/usr/bin/env python3
"""Shared semantic and byte-integrity validation for NL runtime assets."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


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
    return candidate


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_runtime(root: Path, verify_derivatives: bool) -> tuple[list[str], dict[str, int]]:
    """Validate public semantics and optionally verify every local derivative byte."""

    manifest_dir = root / "manifests"
    schema_dir = root / "schemas"
    manifest_paths = {
        "index": (manifest_dir / "index.json", schema_dir / "manifest-index.schema.json"),
        "assets": (manifest_dir / "assets.json", schema_dir / "asset-registry.schema.json"),
        "collections": (manifest_dir / "collections.json", schema_dir / "collections.schema.json"),
        "themes": (manifest_dir / "themes.json", schema_dir / "themes.schema.json"),
    }

    errors: list[str] = []
    loaded: dict[str, dict] = {}

    for name, (manifest_path, schema_path) in manifest_paths.items():
        try:
            manifest = load_json(manifest_path)
            schema = load_json(schema_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: unable to load JSON: {exc}")
            continue

        loaded[name] = manifest
        validate_schema(name, manifest, schema, errors)

    if set(loaded) != set(manifest_paths):
        return errors, {"assets": 0, "collections": 0, "themes": 0, "variants": 0}

    index = loaded["index"]
    assets_manifest = loaded["assets"]
    collections_manifest = loaded["collections"]
    themes_manifest = loaded["themes"]

    for key, relative in index["manifests"].items():
        target = manifest_dir / relative
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
    runtime_ids = require_unique(assets, "runtimeId", "assets", errors)
    collection_ids = require_unique(collections, "id", "collections", errors)
    require_unique(themes, "id", "themes", errors)

    require_sorted([item["id"] for item in assets], "assets", errors)
    require_sorted([item["id"] for item in collections], "collections", errors)
    require_sorted([item["id"] for item in themes], "themes", errors)

    if None in runtime_ids:
        errors.append("assets: every record must have a runtimeId")
    if assets and assets_manifest["generatedAt"] is None:
        errors.append("assets: generatedAt must be populated when published assets exist")

    published_paths: set[str] = set()
    variant_count = 0
    for asset in assets:
        if asset.get("id") != asset.get("runtimeId"):
            errors.append(f"asset {asset.get('id')}: id and runtimeId must agree")

        for variant in asset["variants"]:
            variant_count += 1
            legacy_path = variant["path"]
            if legacy_path in published_paths:
                errors.append(f"assets: duplicate derivative path '{legacy_path}'")
            published_paths.add(legacy_path)

            relative_path = validate_relative_path(legacy_path, f"asset {asset['id']}", errors)
            object_key = variant.get("objectKey")
            if object_key is not None:
                validate_relative_path(object_key, f"asset {asset['id']} objectKey", errors)
                if not object_key.startswith("objects/sha256/"):
                    errors.append(f"asset {asset['id']}: objectKey is not content-addressed")
                if variant.get("legacyPath") != legacy_path:
                    errors.append(f"asset {asset['id']}: legacyPath does not preserve path")

            if not SHA256_PATTERN.fullmatch(str(variant.get("sha256", ""))):
                errors.append(f"asset {asset['id']}: variant SHA-256 is invalid")
            if not isinstance(variant.get("bytes"), int) or variant["bytes"] < 0:
                errors.append(f"asset {asset['id']}: variant byte count is invalid")

            if not verify_derivatives or relative_path is None:
                continue

            runtime_path = root / relative_path
            if not runtime_path.is_file():
                errors.append(f"asset {asset['id']}: derivative missing: {legacy_path}")
                continue

            actual_bytes = runtime_path.stat().st_size
            if actual_bytes != variant["bytes"]:
                errors.append(
                    f"asset {asset['id']}: byte count mismatch for {legacy_path}: "
                    f"manifest={variant['bytes']} actual={actual_bytes}"
                )

            actual_sha = hash_file(runtime_path)
            if actual_sha.lower() != variant["sha256"].lower():
                errors.append(f"asset {asset['id']}: SHA-256 mismatch for {legacy_path}")

    for collection in collections:
        collection_asset_ids = collection["assetIds"]
        if collection_asset_ids != sorted(collection_asset_ids):
            errors.append(f"collection {collection['id']}: assetIds must be sorted")
        if len(collection_asset_ids) != len(set(collection_asset_ids)):
            errors.append(f"collection {collection['id']}: duplicate asset ID")
        for asset_id in collection_asset_ids:
            if asset_id not in asset_ids:
                errors.append(f"collection {collection['id']}: unknown asset ID '{asset_id}'")

    for theme in themes:
        for collection_id in theme.get("collectionIds", []):
            if collection_id not in collection_ids:
                errors.append(f"theme {theme['id']}: unknown collection ID '{collection_id}'")

        for slot, value in theme["assetSlots"].items():
            values = value if isinstance(value, list) else [value]
            if len(values) != len(set(values)):
                errors.append(f"theme {theme['id']} slot {slot}: duplicate asset ID")
            for asset_id in values:
                if asset_id not in asset_ids:
                    errors.append(f"theme {theme['id']} slot {slot}: unknown asset ID '{asset_id}'")

    return errors, {
        "assets": len(assets),
        "collections": len(collections),
        "themes": len(themes),
        "variants": variant_count,
    }
