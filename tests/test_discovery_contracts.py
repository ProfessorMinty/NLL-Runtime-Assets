from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from generate_discovery import build_discovery, compare_trees  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


class DiscoveryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        manifests = self.root / "manifests"
        eligible = {
            "id": "asset-eligible",
            "runtimeId": "asset-eligible",
            "assetVersion": f"sha256:{'b' * 64}",
            "name": "Eligible",
            "type": "illustration",
            "runtimeStatus": "READY",
            "automaticSelection": "ELIGIBLE",
            "tags": ["classroom"],
            "themes": ["learning"],
            "subjects": ["math"],
            "styles": ["line-art"],
            "useCases": ["page-decoration"],
            "variants": [
                {
                    "format": "svg",
                    "path": "assets/legacy/asset-eligible.svg",
                    "objectKey": f"objects/sha256/aa/{'a' * 64}.svg",
                    "legacyPath": "assets/legacy/asset-eligible.svg",
                    "mimeType": "image/svg+xml",
                    "bytes": 12,
                    "sha256": "a" * 64,
                }
            ],
        }
        ineligible = copy.deepcopy(eligible)
        ineligible.update(
            {
                "id": "asset-blocked",
                "runtimeId": "asset-blocked",
                "assetVersion": f"sha256:{'c' * 64}",
                "name": "Blocked",
                "automaticSelection": "INELIGIBLE",
            }
        )
        write_json(
            manifests / "index.json",
            {
                "runtimeBaseUrl": "https://cdn.nlightlabs.com/",
                "manifests": {
                    "assets": "assets.json",
                    "collections": "collections.json",
                    "themes": "themes.json",
                },
            },
        )
        write_json(manifests / "assets.json", {"assets": [eligible, ineligible]})
        write_json(
            manifests / "collections.json",
            {"collections": [{"id": "all", "name": "All", "assetIds": ["asset-blocked", "asset-eligible"]}]},
        )
        write_json(
            manifests / "themes.json",
            {
                "themes": [
                    {
                        "id": "learning",
                        "name": "Learning",
                        "assetSlots": {
                            "banner": ["asset-eligible"],
                            "top-trim": ["asset-eligible"],
                            "bottom-trim": ["asset-eligible"],
                            "photo-frame": ["asset-eligible"],
                            "corner-accent": ["asset-eligible"],
                            "background": ["asset-eligible"],
                            "divider": ["asset-eligible"],
                            "decorations": ["asset-eligible", "asset-blocked"],
                        },
                    }
                ]
            },
        )
        build_discovery(self.root, manifests / "discovery")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOLS / "validate_discovery.py"), "--root", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def page(self) -> Path:
        return self.root / "manifests/discovery/collections/all/page-001.json"

    def regenerate(self) -> None:
        discovery = self.root / "manifests/discovery"
        if discovery.exists():
            import shutil

            shutil.rmtree(discovery)
        build_discovery(self.root, discovery)

    def test_generation_is_byte_deterministic_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as second:
            second_path = Path(second) / "discovery"
            build_discovery(self.root, second_path)
            self.assertEqual([], compare_trees(second_path, self.root / "manifests/discovery"))
        result = self.validate()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_deleting_candidate_id_fails(self) -> None:
        page = json.loads(self.page().read_text(encoding="utf-8"))
        page["assets"] = []
        page["assetCount"] = 0
        write_json(self.page(), page)
        result = self.validate()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("do not exactly match", result.stdout)

    def test_url_hash_or_version_tamper_fails(self) -> None:
        for field, value in (("url", "https://example.invalid/tampered.svg"), ("sha256", "f" * 64)):
            with self.subTest(field=field):
                self.regenerate()
                page = json.loads(self.page().read_text(encoding="utf-8"))
                page["assets"][0]["preferredVariant"][field] = value
                write_json(self.page(), page)
                result = self.validate()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("URL/hash/version", result.stdout)
        self.regenerate()
        page = json.loads(self.page().read_text(encoding="utf-8"))
        page["assets"][0]["assetVersion"] = f"sha256:{'d' * 64}"
        write_json(self.page(), page)
        result = self.validate()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("URL/hash/version", result.stdout)

    def test_noneligible_asset_cannot_enter_discovery(self) -> None:
        page = json.loads(self.page().read_text(encoding="utf-8"))
        page["assets"].append({"id": "asset-blocked", "name": "Blocked", "availableFormats": []})
        page["assetCount"] = 2
        write_json(self.page(), page)
        result = self.validate()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("non-eligible asset", result.stdout)


if __name__ == "__main__":
    unittest.main()
