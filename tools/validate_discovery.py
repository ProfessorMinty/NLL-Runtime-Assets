#!/usr/bin/env python3
"""Validate public discovery against the exact READY + ELIGIBLE root set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from generate_discovery import REQUIRED_SLOTS, discovery_asset

MAX_PAGE_ASSETS = 100
MAX_DISCOVERY_JSON_BYTES = 180 * 1024
FORBIDDEN_ASSET_KEYS = {
    "path",
    "objectKey",
    "legacyPath",
    "rights",
    "sourcePath",
    "archivePath",
    "extractedPath",
    "packSha256",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args()


def load_json(path: Path, root: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        try:
            label = path.relative_to(root)
        except ValueError:
            label = path
        errors.append(f"cannot read {label}: {exc}")
        return {}


def record_forbidden_keys(value: Any, context: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_ASSET_KEYS:
                errors.append(f"{context}: private/internal key '{key}' entered discovery")
            record_forbidden_keys(child, context, errors)
    elif isinstance(value, list):
        for child in value:
            record_forbidden_keys(child, context, errors)


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    manifests = root / "manifests"
    discovery = manifests / "discovery"
    errors: list[str] = []

    assets_doc = load_json(manifests / "assets.json", root, errors)
    collections_doc = load_json(manifests / "collections.json", root, errors)
    themes_doc = load_json(manifests / "themes.json", root, errors)
    manifest_index = load_json(manifests / "index.json", root, errors)
    index = load_json(discovery / "index.json", root, errors)
    base_url = str(manifest_index.get("runtimeBaseUrl", ""))

    eligible = {
        asset["id"]: asset
        for asset in assets_doc.get("assets", [])
        if asset.get("runtimeStatus") == "READY"
        and asset.get("automaticSelection") == "ELIGIBLE"
    }
    authoritative_collections = {
        collection["id"]: collection for collection in collections_doc.get("collections", [])
    }
    authoritative_themes = {theme["id"]: theme for theme in themes_doc.get("themes", [])}

    if index.get("runtimeBaseUrl") != base_url:
        errors.append("discovery runtimeBaseUrl differs from manifest index")
    if index.get("eligibleAssetCount") != len(eligible):
        errors.append(f"eligibleAssetCount is {index.get('eligibleAssetCount')}, expected {len(eligible)}")
    if index.get("collectionCount") != len(authoritative_collections):
        errors.append("collection count does not match authoritative collections")
    if index.get("themeCount") != len(authoritative_themes):
        errors.append("theme count does not match authoritative themes")
    if index.get("policy") != {"runtimeStatus": "READY", "automaticSelection": "ELIGIBLE"}:
        errors.append("discovery policy is not exactly READY + ELIGIBLE")

    indexed_collection_ids = [item.get("id") for item in index.get("collections", [])]
    if indexed_collection_ids != sorted(authoritative_collections):
        errors.append("discovery collections are missing, extra, or non-deterministically ordered")

    discovery_union: set[str] = set()
    for collection_entry in index.get("collections", []):
        collection_id = collection_entry.get("id")
        source = authoritative_collections.get(collection_id)
        if source is None:
            errors.append(f"unknown discovery collection: {collection_id}")
            continue

        expected_ids = sorted(asset_id for asset_id in source.get("assetIds", []) if asset_id in eligible)
        pages = collection_entry.get("pages", [])
        expected_pages = [
            f"discovery/collections/{collection_id}/page-{number:03d}.json"
            for number in range(1, (len(expected_ids) + MAX_PAGE_ASSETS - 1) // MAX_PAGE_ASSETS + 1)
        ]
        if pages != expected_pages:
            errors.append(f"{collection_id}: page paths differ from deterministic sharding")
        if collection_entry.get("assetCount") != len(expected_ids):
            errors.append(f"{collection_id}: assetCount differs from candidate set")
        if collection_entry.get("pageCount") != len(expected_pages):
            errors.append(f"{collection_id}: pageCount differs from candidate set")

        actual_ids: list[str] = []
        for page_number, relative in enumerate(pages, start=1):
            path = manifests / relative
            if not path.exists():
                errors.append(f"{collection_id}: missing page {relative}")
                continue
            if path.stat().st_size > MAX_DISCOVERY_JSON_BYTES:
                errors.append(f"{relative}: exceeds {MAX_DISCOVERY_JSON_BYTES // 1024} KiB")
            page = load_json(path, root, errors)
            records = page.get("assets", [])
            if page.get("collection", {}).get("id") != collection_id:
                errors.append(f"{relative}: collection identity mismatch")
            if page.get("page") != page_number:
                errors.append(f"{relative}: page number mismatch")
            if page.get("assetCount") != len(records):
                errors.append(f"{relative}: assetCount mismatch")
            if page.get("totalAssetCount") != len(expected_ids):
                errors.append(f"{relative}: totalAssetCount mismatch")
            for record in records:
                asset_id = record.get("id")
                actual_ids.append(asset_id)
                discovery_union.add(asset_id)
                source_asset = eligible.get(asset_id)
                if source_asset is None:
                    errors.append(f"{relative}: non-eligible asset {asset_id}")
                    continue
                expected_record = discovery_asset(source_asset, base_url)
                if record != expected_record:
                    errors.append(f"{relative}: URL/hash/version or metadata mismatch for {asset_id}")
                record_forbidden_keys(record, f"{relative}/{asset_id}", errors)
        if actual_ids != expected_ids:
            errors.append(f"{collection_id}: discovery IDs do not exactly match candidate collection")

    if discovery_union != set(eligible):
        missing = sorted(set(eligible) - discovery_union)
        extra = sorted(discovery_union - set(eligible))
        errors.append(
            "discovery ID union does not equal READY + ELIGIBLE set "
            f"(missing={len(missing)}, extra={len(extra)})"
        )

    indexed_theme_ids = [item.get("id") for item in index.get("themes", [])]
    if indexed_theme_ids != sorted(authoritative_themes):
        errors.append("discovery themes are missing, extra, or non-deterministically ordered")

    incomplete_count = 0
    for theme_entry in index.get("themes", []):
        theme_id = theme_entry.get("id")
        source = authoritative_themes.get(theme_id)
        if source is None:
            errors.append(f"unknown discovery theme: {theme_id}")
            continue
        expected_relative = f"discovery/themes/{theme_id}.json"
        if theme_entry.get("path") != expected_relative:
            errors.append(f"{theme_id}: non-deterministic theme path")
            continue
        path = manifests / expected_relative
        if not path.exists():
            errors.append(f"{theme_id}: missing theme shard")
            continue
        if path.stat().st_size > MAX_DISCOVERY_JSON_BYTES:
            errors.append(f"{expected_relative}: exceeds {MAX_DISCOVERY_JSON_BYTES // 1024} KiB")
        document = load_json(path, root, errors)
        slots = document.get("assetSlots", {})
        if tuple(slots) != REQUIRED_SLOTS:
            errors.append(f"{theme_id}: required eight slots are absent or out of order")

        expected_slots = {
            slot: [asset_id for asset_id in source.get("assetSlots", {}).get(slot, []) if asset_id in eligible]
            for slot in REQUIRED_SLOTS
        }
        if slots != expected_slots:
            errors.append(f"{theme_id}: slot IDs differ from the candidate set")
        missing_slots = [slot for slot in REQUIRED_SLOTS if not expected_slots[slot]]
        status = "INCOMPLETE" if missing_slots else "COMPLETE"
        if missing_slots:
            incomplete_count += 1
        if document.get("theme", {}).get("suggestionStatus") != status:
            errors.append(f"{theme_id}: suggestionStatus does not reflect recipe completeness")
        if document.get("theme", {}).get("missingSlots") != missing_slots:
            errors.append(f"{theme_id}: missingSlots does not reflect recipe completeness")
        if theme_entry.get("suggestionStatus") != status or theme_entry.get("missingSlots") != missing_slots:
            errors.append(f"{theme_id}: theme index completeness metadata mismatch")

        expected_ids: list[str] = []
        used: set[str] = set()
        for slot in REQUIRED_SLOTS:
            for asset_id in expected_slots[slot]:
                if asset_id not in used:
                    used.add(asset_id)
                    expected_ids.append(asset_id)
        records = document.get("assets", [])
        if [record.get("id") for record in records] != expected_ids:
            errors.append(f"{theme_id}: embedded assets do not exactly match ordered slot IDs")
        if document.get("assetCount") != len(records):
            errors.append(f"{theme_id}: assetCount mismatch")
        for record in records:
            asset_id = record.get("id")
            source_asset = eligible.get(asset_id)
            if source_asset is None or record != discovery_asset(source_asset, base_url):
                errors.append(f"{expected_relative}: URL/hash/version or metadata mismatch for {asset_id}")
            record_forbidden_keys(record, f"{expected_relative}/{asset_id}", errors)

    if index.get("incompleteThemeCount") != incomplete_count:
        errors.append("incompleteThemeCount does not match honest recipe completeness")

    if errors:
        print(f"NL Asset discovery validation FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    page_count = sum(item.get("pageCount", 0) for item in index.get("collections", []))
    print("NL Asset discovery validation passed.")
    print(f"Eligible assets:   {len(eligible):,}")
    print(f"Collections:       {len(authoritative_collections):,}")
    print(f"Collection pages:  {page_count:,}")
    print(f"Themes:            {len(authoritative_themes):,}")
    print(f"Incomplete themes: {incomplete_count:,}")
    print("Exact set:         discovery union == READY + ELIGIBLE")
    print("Integrity:         preferred URL/hash/version agree with root manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
