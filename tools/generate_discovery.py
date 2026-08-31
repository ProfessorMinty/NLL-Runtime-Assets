#!/usr/bin/env python3
"""Deterministically generate public NL Asset discovery from runtime manifests."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

PAGE_SIZE = 100
REQUIRED_SLOTS = (
    "banner",
    "top-trim",
    "bottom-trim",
    "photo-frame",
    "corner-accent",
    "background",
    "divider",
    "decorations",
)
PREFERRED_FORMAT_ORDER = ("svg", "webp", "png", "jpg", "jpeg", "avif", "gif", "glb")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def public_url(base_url: str, variant: dict[str, Any]) -> str:
    key = str(variant.get("objectKey") or variant["path"])
    return base_url.rstrip("/") + "/" + key.replace("\\", "/").lstrip("/")


def choose_preferred_variant(asset: dict[str, Any]) -> dict[str, Any] | None:
    variants = [variant for variant in asset.get("variants", []) if variant.get("path")]
    if not variants:
        return None

    indexed = {str(variant.get("format", "")).lower(): variant for variant in variants}
    for format_name in PREFERRED_FORMAT_ORDER:
        if format_name in indexed:
            return indexed[format_name]
    return variants[0]


def discovery_asset(asset: dict[str, Any], base_url: str) -> dict[str, Any]:
    formats = sorted({str(v["format"]) for v in asset.get("variants", []) if v.get("format")})
    record: dict[str, Any] = {
        "id": asset["id"],
        "name": asset.get("name", asset["id"]),
        "type": asset.get("type"),
        "tags": asset.get("tags", []),
        "themes": asset.get("themes", []),
        "subjects": asset.get("subjects", []),
        "styles": asset.get("styles", []),
        "useCases": asset.get("useCases", []),
        "availableFormats": formats,
    }
    if asset.get("assetVersion"):
        record["assetVersion"] = asset["assetVersion"]

    selected = choose_preferred_variant(asset)
    if selected is not None:
        preferred: dict[str, Any] = {
            "format": selected.get("format"),
            "url": public_url(base_url, selected),
            "mimeType": selected.get("mimeType"),
            "bytes": selected.get("bytes"),
            "sha256": selected.get("sha256"),
        }
        if selected.get("width") is not None:
            preferred["width"] = selected["width"]
        if selected.get("height") is not None:
            preferred["height"] = selected["height"]
        record["preferredVariant"] = preferred

    return record


def build_discovery(root: Path, output: Path) -> dict[str, int]:
    manifests = root / "manifests"
    assets_doc = load_json(manifests / "assets.json")
    collections_doc = load_json(manifests / "collections.json")
    themes_doc = load_json(manifests / "themes.json")
    index_doc = load_json(manifests / "index.json")
    base_url = str(index_doc["runtimeBaseUrl"])

    eligible_assets = sorted(
        (
            asset
            for asset in assets_doc.get("assets", [])
            if asset.get("runtimeStatus") == "READY"
            and asset.get("automaticSelection") == "ELIGIBLE"
        ),
        key=lambda asset: asset["id"],
    )
    eligible_by_id = {asset["id"]: asset for asset in eligible_assets}

    collection_index: list[dict[str, Any]] = []
    page_count = 0
    for collection in sorted(collections_doc.get("collections", []), key=lambda item: item["id"]):
        collection_id = collection["id"]
        ids = sorted(asset_id for asset_id in collection.get("assetIds", []) if asset_id in eligible_by_id)
        page_paths: list[str] = []
        for start in range(0, len(ids), PAGE_SIZE):
            page_number = start // PAGE_SIZE + 1
            page_ids = ids[start : start + PAGE_SIZE]
            relative = f"collections/{collection_id}/page-{page_number:03d}.json"
            write_json(
                output / relative,
                {
                    "schemaVersion": 1,
                    "collection": {"id": collection_id, "name": collection.get("name", collection_id)},
                    "page": page_number,
                    "pageSize": PAGE_SIZE,
                    "assetCount": len(page_ids),
                    "totalAssetCount": len(ids),
                    "assets": [discovery_asset(eligible_by_id[asset_id], base_url) for asset_id in page_ids],
                },
            )
            page_paths.append(f"discovery/{relative}")

        collection_index.append(
            {
                "id": collection_id,
                "name": collection.get("name", collection_id),
                "description": collection.get("description", ""),
                "tags": collection.get("tags", []),
                "assetCount": len(ids),
                "pageSize": PAGE_SIZE,
                "pageCount": len(page_paths),
                "pages": page_paths,
            }
        )
        page_count += len(page_paths)

    theme_index: list[dict[str, Any]] = []
    incomplete_theme_count = 0
    for theme in sorted(themes_doc.get("themes", []), key=lambda item: item["id"]):
        theme_id = theme["id"]
        source_slots = theme.get("assetSlots", {})
        slots: dict[str, list[str]] = {}
        ordered_ids: list[str] = []
        used: set[str] = set()
        for slot in REQUIRED_SLOTS:
            slot_ids = [asset_id for asset_id in source_slots.get(slot, []) if asset_id in eligible_by_id]
            slots[slot] = slot_ids
            for asset_id in slot_ids:
                if asset_id not in used:
                    used.add(asset_id)
                    ordered_ids.append(asset_id)

        missing_slots = [slot for slot in REQUIRED_SLOTS if not slots[slot]]
        suggestion_status = "INCOMPLETE" if missing_slots else "COMPLETE"
        if missing_slots:
            incomplete_theme_count += 1
        relative = f"themes/{theme_id}.json"
        write_json(
            output / relative,
            {
                "schemaVersion": 1,
                "theme": {
                    "id": theme_id,
                    "name": theme.get("name", theme_id),
                    "description": theme.get("description", ""),
                    "collectionIds": theme.get("collectionIds", []),
                    "suggestionStatus": suggestion_status,
                    "missingSlots": missing_slots,
                },
                "assetSlots": slots,
                "assetCount": len(ordered_ids),
                "assets": [discovery_asset(eligible_by_id[asset_id], base_url) for asset_id in ordered_ids],
            },
        )
        theme_index.append(
            {
                "id": theme_id,
                "name": theme.get("name", theme_id),
                "description": theme.get("description", ""),
                "path": f"discovery/{relative}",
                "suggestionStatus": suggestion_status,
                "missingSlots": missing_slots,
            }
        )

    write_json(
        output / "index.json",
        {
            "schemaVersion": 1,
            "runtimeBaseUrl": base_url,
            "policy": {"runtimeStatus": "READY", "automaticSelection": "ELIGIBLE"},
            "eligibleAssetCount": len(eligible_assets),
            "collectionCount": len(collection_index),
            "themeCount": len(theme_index),
            "incompleteThemeCount": incomplete_theme_count,
            "collections": collection_index,
            "themes": theme_index,
        },
    )
    return {
        "assets": len(eligible_assets),
        "collections": len(collection_index),
        "pages": page_count,
        "themes": len(theme_index),
        "incompleteThemes": incomplete_theme_count,
    }


def relative_files(path: Path) -> list[Path]:
    return sorted(item.relative_to(path) for item in path.rglob("*") if item.is_file())


def compare_trees(expected: Path, actual: Path) -> list[str]:
    errors: list[str] = []
    expected_files = relative_files(expected)
    actual_files = relative_files(actual) if actual.exists() else []
    expected_set = set(expected_files)
    actual_set = set(actual_files)
    for missing in sorted(expected_set - actual_set):
        errors.append(f"missing generated file: manifests/discovery/{missing.as_posix()}")
    for extra in sorted(actual_set - expected_set):
        errors.append(f"stale generated file: manifests/discovery/{extra.as_posix()}")
    for relative in sorted(expected_set & actual_set):
        if not filecmp.cmp(expected / relative, actual / relative, shallow=False):
            errors.append(f"generated file differs: manifests/discovery/{relative.as_posix()}")
    return errors


def synchronize_tree(source: Path, target: Path) -> None:
    """Replace files atomically without replacing the ACL-bearing root directory."""
    target.mkdir(parents=True, exist_ok=True)
    source_files = set(relative_files(source))
    target_files = set(relative_files(target))
    for relative in sorted(source_files):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        shutil.copyfile(source / relative, temporary)
        os.replace(temporary, destination)
    for relative in sorted(target_files - source_files, reverse=True):
        (target / relative).unlink()
    for directory in sorted(
        (item for item in target.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if not any(directory.iterdir()):
            directory.rmdir()


def install_tree(generated: Path, target: Path) -> None:
    backup = generated.parent / "discovery-backup"
    if target.exists():
        shutil.copytree(target, backup)
    try:
        synchronize_tree(generated, target)
    except Exception:
        if backup.exists():
            synchronize_tree(backup, target)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="fail if committed discovery is stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    target = root / "manifests" / "discovery"
    # Keep the candidate on the same volume and under the repository so the
    # final rename is atomic and inherits repository filesystem permissions.
    with tempfile.TemporaryDirectory(
        prefix=".nl-assets-discovery-", dir=root / "manifests"
    ) as temporary:
        generated = Path(temporary) / "discovery"
        counts = build_discovery(root, generated)
        if args.check:
            errors = compare_trees(generated, target)
            if errors:
                print("NL Asset discovery check FAILED:")
                for error in errors:
                    print(f"  - {error}")
                return 1
        else:
            install_tree(generated, target)

    action = "check passed" if args.check else "generation complete"
    print(f"NL Asset discovery {action}.")
    print(f"Eligible assets:   {counts['assets']:,}")
    print(f"Collections:       {counts['collections']:,}")
    print(f"Collection pages:  {counts['pages']:,}")
    print(f"Themes:            {counts['themes']:,}")
    print(f"Incomplete themes: {counts['incompleteThemes']:,}")
    print("Safety policy:     READY + ELIGIBLE only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
