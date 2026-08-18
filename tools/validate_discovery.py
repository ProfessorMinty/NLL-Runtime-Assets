import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAN = ROOT / "manifests"
DISC = MAN / "discovery"

REQUIRED_SLOTS = {
    "banner",
    "top-trim",
    "bottom-trim",
    "photo-frame",
    "corner-accent",
    "background",
    "divider",
    "decorations",
}

MAX_PAGE_ASSETS = 100
MAX_DISCOVERY_JSON_BYTES = 150 * 1024

errors = []

def fail(message):
    errors.append(message)

def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Cannot read {path.relative_to(ROOT)}: {exc}")
        return {}

assets_doc = load(MAN / "assets.json")
collections_doc = load(MAN / "collections.json")
themes_doc = load(MAN / "themes.json")
index = load(DISC / "index.json")

eligible = {
    a["id"]: a
    for a in assets_doc.get("assets", [])
    if a.get("runtimeStatus") == "READY"
    and a.get("automaticSelection") == "ELIGIBLE"
}

base = index.get("runtimeBaseUrl", "")

if index.get("eligibleAssetCount") != len(eligible):
    fail(
        f"eligibleAssetCount is {index.get('eligibleAssetCount')}, "
        f"expected {len(eligible)}"
    )

if index.get("collectionCount") != len(collections_doc.get("collections", [])):
    fail("Collection count does not match authoritative collections manifest.")

if index.get("themeCount") != len(themes_doc.get("themes", [])):
    fail("Theme count does not match authoritative themes manifest.")

policy = index.get("policy", {})
if policy.get("runtimeStatus") != "READY":
    fail("Discovery runtime policy is not READY.")
if policy.get("automaticSelection") != "ELIGIBLE":
    fail("Discovery automatic-selection policy is not ELIGIBLE.")

def check_asset(record, context):
    asset_id = record.get("id")

    if asset_id not in eligible:
        fail(f"{context}: non-eligible asset {asset_id}")
        return

    source = eligible[asset_id]

    if record.get("name") != source.get("name"):
        fail(f"{context}: name mismatch for {asset_id}")

    preferred = record.get("preferredVariant")
    if preferred:
        url = preferred.get("url", "")
        if not url.startswith(base):
            fail(f"{context}: invalid preferred URL for {asset_id}: {url}")

seen_collection_ids = set()

for collection in index.get("collections", []):
    cid = collection.get("id")

    if cid in seen_collection_ids:
        fail(f"Duplicate collection in discovery index: {cid}")
    seen_collection_ids.add(cid)

    pages = collection.get("pages", [])

    if collection.get("pageCount") != len(pages):
        fail(f"{cid}: pageCount mismatch")

    seen_assets = set()
    counted = 0

    for relative in pages:
        path = MAN / relative

        if not path.exists():
            fail(f"{cid}: missing page {relative}")
            continue

        if path.stat().st_size > MAX_DISCOVERY_JSON_BYTES:
            fail(
                f"{relative}: {path.stat().st_size / 1024:.1f} KiB "
                f"exceeds {MAX_DISCOVERY_JSON_BYTES / 1024:.0f} KiB"
            )

        doc = load(path)
        records = doc.get("assets", [])

        if doc.get("collection", {}).get("id") != cid:
            fail(f"{relative}: collection identity mismatch")

        if len(records) > MAX_PAGE_ASSETS:
            fail(f"{relative}: contains {len(records)} assets")

        if doc.get("assetCount") != len(records):
            fail(f"{relative}: assetCount mismatch")

        if doc.get("totalAssetCount") != collection.get("assetCount"):
            fail(f"{relative}: totalAssetCount mismatch")

        for record in records:
            aid = record.get("id")
            if aid in seen_assets:
                fail(f"{cid}: duplicate asset {aid}")
            seen_assets.add(aid)

            check_asset(record, relative)

        counted += len(records)

    if counted != collection.get("assetCount"):
        fail(
            f"{cid}: indexed assetCount {collection.get('assetCount')} "
            f"but pages contain {counted}"
        )

seen_theme_ids = set()

for theme in index.get("themes", []):
    tid = theme.get("id")

    if tid in seen_theme_ids:
        fail(f"Duplicate theme in discovery index: {tid}")
    seen_theme_ids.add(tid)

    relative = theme.get("path")
    path = MAN / relative

    if not path.exists():
        fail(f"{tid}: missing theme shard {relative}")
        continue

    if path.stat().st_size > MAX_DISCOVERY_JSON_BYTES:
        fail(
            f"{relative}: {path.stat().st_size / 1024:.1f} KiB "
            f"exceeds {MAX_DISCOVERY_JSON_BYTES / 1024:.0f} KiB"
        )

    doc = load(path)

    if doc.get("theme", {}).get("id") != tid:
        fail(f"{relative}: theme identity mismatch")

    slots = doc.get("assetSlots", {})

    if set(slots) != REQUIRED_SLOTS:
        fail(
            f"{tid}: theme slots differ from required eight-slot contract"
        )

    used = set()

    for slot, ids in slots.items():
        for aid in ids:
            if aid not in eligible:
                fail(f"{tid}/{slot}: non-eligible asset {aid}")
            used.add(aid)

    records = doc.get("assets", [])
    record_ids = {a.get("id") for a in records}

    if record_ids != used:
        fail(f"{tid}: embedded assets do not exactly match slot asset IDs")

    if doc.get("assetCount") != len(records):
        fail(f"{tid}: assetCount mismatch")

    for record in records:
        check_asset(record, relative)

if errors:
    print("NL Asset discovery validation FAILED")
    print()
    for error in errors:
        print(" -", error)
    sys.exit(1)

page_count = sum(
    c.get("pageCount", 0)
    for c in index.get("collections", [])
)

print("NL Asset discovery validation passed.")
print(f"Eligible assets:   {len(eligible):,}")
print(f"Collections:       {len(index.get('collections', []))}")
print(f"Collection pages:  {page_count:,}")
print(f"Themes:            {len(index.get('themes', []))}")
print("Safety policy:     READY + ELIGIBLE only")
print("Theme contract:    eight slots verified")
