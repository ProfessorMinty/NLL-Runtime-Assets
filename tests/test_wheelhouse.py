from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_public_boundary import V1_WHEELHOUSE  # noqa: E402
from verify_v1_wheelhouse import (  # noqa: E402
    REQUIREMENTS_SHA256,
    REQUIREMENTS_SIZE,
    WHEELS,
    WheelhouseError,
    verify,
)


class WheelhouseTests(unittest.TestCase):
    def test_reviewed_wheelhouse_passes(self) -> None:
        verify(ROOT)

    def test_bootstrap_authorities_have_identical_wheel_identities(self) -> None:
        public_identities = {
            Path(path).name: identity for path, identity in V1_WHEELHOUSE.items()
        }
        self.assertEqual(public_identities, WHEELS)
        requirements = (ROOT / "requirements-ci.txt").read_bytes()
        self.assertEqual(len(requirements), REQUIREMENTS_SIZE)
        import hashlib

        self.assertEqual(hashlib.sha256(requirements).hexdigest(), REQUIREMENTS_SHA256)

    def test_tampered_or_extra_wheelhouse_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / "requirements-ci.txt", root / "requirements-ci.txt")
            (root / "ci").mkdir()
            shutil.copytree(ROOT / "ci" / "wheelhouse", root / "ci" / "wheelhouse")
            selected = next((root / "ci" / "wheelhouse").iterdir())
            selected.write_bytes(selected.read_bytes() + b"x")
            with self.assertRaises(WheelhouseError):
                verify(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / "requirements-ci.txt", root / "requirements-ci.txt")
            (root / "ci").mkdir()
            shutil.copytree(ROOT / "ci" / "wheelhouse", root / "ci" / "wheelhouse")
            (root / "ci" / "wheelhouse" / "unexpected.whl").write_bytes(b"not reviewed")
            with self.assertRaises(WheelhouseError):
                verify(root)

    def test_tampered_requirements_fails_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / "requirements-ci.txt", root / "requirements-ci.txt")
            (root / "requirements-ci.txt").write_bytes(
                (root / "requirements-ci.txt").read_bytes() + b"\n"
            )
            (root / "ci").mkdir()
            shutil.copytree(ROOT / "ci" / "wheelhouse", root / "ci" / "wheelhouse")
            with self.assertRaises(WheelhouseError):
                verify(root)

    def test_requirements_checkout_is_lf_even_with_autocrlf(self) -> None:
        attribute = subprocess.run(
            ["git", "check-attr", "eol", "--", "requirements-ci.txt"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(attribute, "requirements-ci.txt: eol: lf")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / ".gitattributes", root / ".gitattributes")
            expected = (ROOT / "requirements-ci.txt").read_bytes()
            (root / "requirements-ci.txt").write_bytes(expected)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "core.autocrlf=false", "add", ".gitattributes", "requirements-ci.txt"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Wheelhouse Test",
                    "-c",
                    "user.email=wheelhouse-test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "fixture",
                ],
                cwd=root,
                check=True,
            )
            (root / "requirements-ci.txt").unlink()
            subprocess.run(
                ["git", "-c", "core.autocrlf=true", "checkout", "--", "requirements-ci.txt"],
                cwd=root,
                check=True,
            )
            self.assertEqual((root / "requirements-ci.txt").read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
