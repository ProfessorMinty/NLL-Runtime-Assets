from __future__ import annotations

import hashlib
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_public_boundary import (  # noqa: E402
    PublicBoundaryError,
    REQUIRED_V1_AUTHORITY_PATHS,
    _normalized_path,
    validate_public_boundary,
    validate_public_boundary_range,
)


class PublicBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Boundary Fixture")
        self.git("config", "user.email", "boundary-fixture@example.invalid")
        (self.root / "README.md").write_text("# Public fixture\n", encoding="utf-8")
        self.commit("Create public fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(
        self, *arguments: str, input_bytes: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            input=input_bytes,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.fail(result.stderr.decode("utf-8", errors="replace"))
        return result

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def add(self, relative: str, data: bytes) -> str:
        path = self.root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.commit(relative)

    def raw_tree_commit(self, paths: dict[str, bytes]) -> str:
        tree: dict[str, object] = {}
        for relative, data in paths.items():
            node = tree
            components = relative.split("/")
            for component in components[:-1]:
                child = node.setdefault(component, {})
                self.assertIsInstance(child, dict)
                node = child  # type: ignore[assignment]
            node[components[-1]] = data

        def write_tree(node: dict[str, object]) -> str:
            records: list[tuple[bytes, bytes]] = []
            for name, value in node.items():
                encoded_name = name.encode("ascii")
                if isinstance(value, dict):
                    object_id = write_tree(value)
                    record = b"040000 tree " + object_id.encode("ascii") + b"\t" + encoded_name + b"\0"
                    sort_key = encoded_name + b"/"
                else:
                    self.assertIsInstance(value, bytes)
                    object_id = self.git(
                        "hash-object", "-w", "--stdin", input_bytes=value
                    ).stdout.decode().strip()
                    record = b"100644 blob " + object_id.encode("ascii") + b"\t" + encoded_name + b"\0"
                    sort_key = encoded_name
                records.append((sort_key, record))
            raw_tree = b"".join(record for _key, record in sorted(records))
            return self.git("mktree", "-z", input_bytes=raw_tree).stdout.decode().strip()

        tree_id = write_tree(tree)
        parent = self.git("rev-parse", "HEAD").stdout.decode().strip()
        return self.git(
            "commit-tree", tree_id, "-p", parent, input_bytes=b"Raw tree fixture\n"
        ).stdout.decode().strip()

    def activate_v1_authority(self) -> str:
        for relative in REQUIRED_V1_AUTHORITY_PATHS:
            source = ROOT / Path(relative)
            destination = self.root / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return self.commit("Activate reviewed V1 authority")

    def test_explicit_text_only_public_tree_passes(self) -> None:
        validate_public_boundary(self.root, "HEAD")

    def test_complete_candidate_source_tree_passes_its_self_scan(self) -> None:
        # Rebuild the candidate file set in an isolated repository using the
        # current index for membership and current source bytes for content.
        # This exercises the complete candidate even before its commit exists.
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
        for child in self.root.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for encoded in filter(None, listed.split(b"\0")):
            relative = encoded.decode("utf-8", errors="strict")
            source = ROOT / Path(relative)
            destination = self.root / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        candidate = self.commit("Assemble complete candidate source tree")
        validate_public_boundary(self.root, candidate)

    def test_tree_rejects_casefold_collisions_for_windows_recovery(self) -> None:
        revision = self.raw_tree_commit(
            {
                "README.md": b"# Public fixture\n",
                "docs/Foo.md": b"# One\n",
                "docs/foo.md": b"# Two\n",
            }
        )
        with self.assertRaisesRegex(PublicBoundaryError, "case-insensitive"):
            validate_public_boundary(self.root, revision)

    def test_tree_rejects_win32_reserved_and_trailing_dot_components(self) -> None:
        cases = (
            "docs/CON/readme.md",
            "docs/trailing./readme.md",
            "docs/NUL.txt",
        )
        for path in cases:
            with self.subTest(path=path):
                revision = self.raw_tree_commit(
                    {"README.md": b"# Public fixture\n", path: b"# Unsafe\n"}
                )
                with self.assertRaisesRegex(PublicBoundaryError, "Windows recovery"):
                    validate_public_boundary(self.root, revision)

    def test_tree_rejects_windows_component_longer_than_255_ascii_characters(self) -> None:
        revision = self.raw_tree_commit(
            {
                "README.md": b"# Public fixture\n",
                "docs/" + "a" * 256: b"# Unsafe\n",
            }
        )
        with self.assertRaisesRegex(PublicBoundaryError, "Windows recovery"):
            validate_public_boundary(self.root, revision)

    def test_nonportable_credential_shaped_tree_path_is_not_echoed(self) -> None:
        credential = "ghp_" + "A" * 24
        revision = self.raw_tree_commit(
            {
                "README.md": b"# Public fixture\n",
                f"docs/CON.{credential}.md": b"# Unsafe\n",
            }
        )
        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, revision)
        self.assertNotIn(credential, str(captured.exception))

    def test_only_the_two_reviewed_workflow_paths_are_allowed(self) -> None:
        self.add(
            ".github/workflows/spoof.yml",
            b"name: Spoof\non:\n  pull_request_target:\npermissions:\n  contents: read\n",
        )
        with self.assertRaisesRegex(PublicBoundaryError, "explicit public repository set"):
            validate_public_boundary(self.root, "HEAD")

    def test_known_workflow_rejects_write_permission_and_untrusted_event(self) -> None:
        image = (
            "python:3.12.11-bookworm@sha256:"
            "13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12"
        )
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        cases = (
            (
                b"name: Unsafe\non:\n  push:\n  pull_request:\n  schedule:\n"
                b"permissions:\n  contents: read\njobs:\n  validate:\n"
                b"    permissions: { contents: write }\n    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps: []\n".encode(),
                "write permission|override permissions",
            ),
            (
                b"name: Unsafe\non:\n  pull_request_target:\npermissions:\n"
                b"  contents: read\njobs:\n  validate:\n    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps: []\n".encode(),
                "event set",
            ),
            (
                b"name: &write write\non:\n  push:\n  pull_request:\n  schedule:\n"
                b"permissions:\n  contents: read\njobs:\n  validate:\n"
                b"    permissions: { contents: *write }\n    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps:\n".encode()
                + b"      - \"uses\": actions/checkout@0000000000000000000000000000000000000000\n",
                "anchors or aliases|quoted mapping keys",
            ),
            (
                b"name: Unsafe\non:\n  push:\n  pull_request:\n  schedule:\n"
                b"permissions:\n  contents: read\njobs:\n  validate:\n"
                b"    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps: []\n".encode()
                + b"  second-job:\n    runs-on: windows-2025\n    steps: []\n",
                "job set",
            ),
            (
                b"name: Unsafe\non:\n  push:\n  pull_request:\n  schedule:\n"
                b"permissions:\n  contents: read\njobs:\n  validate:\n"
                b"    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps:\n".encode()
                + b"      - run: printf '%s' \"#${{ secrets.X }}\"\n",
                "comments or hash text",
            ),
            (
                b"name: Unsafe\non:\n  push:\n  pull_request:\n  schedule:\n"
                b"permissions:\n  contents: read\njobs:\n  validate:\n"
                b"    runs-on: ubuntu-24.04\n"
                + f"    container:\n      image: {image}\n    steps:\n".encode()
                + b"      - {name: \"#hidden\", \"uses\": attacker/action@v1}\n",
                "comments or hash text",
            ),
        )
        for data, message in cases:
            with self.subTest(message=message):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(".github/workflows/validate-runtime.yml", data)
                with self.assertRaises(PublicBoundaryError):
                    validate_public_boundary(self.root, "HEAD")

    def test_workflow_commands_conditions_and_services_are_exact(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        reviewed = (ROOT / ".github" / "workflows" / "validate-runtime.yml").read_text(
            encoding="utf-8"
        )
        cases = (
            reviewed.replace(
                "python -P tools/validate_runtime_release.py --repository",
                "true",
                1,
            ),
            reviewed.replace(
                "    steps:\n",
                "    steps:\n      - run: true\n",
                1,
            ),
            reviewed.replace(
                "    container:\n      image:",
                "    container:\n      env:\n        PYTHONPATH: candidate/tools\n      image:",
                1,
            ),
            reviewed.replace(
                "      - name: Verify immutable execution environment\n",
                "      - name: Verify immutable execution environment\n"
                "        continue-on-error: true\n",
                1,
            ),
            reviewed.replace(
                "    runs-on: ubuntu-24.04\n",
                "    services:\n      helper:\n        image: attacker/example@sha256:"
                + "0" * 64
                + "\n    runs-on: ubuntu-24.04\n",
                1,
            ),
            reviewed.replace(
                "        run: test \"$(python -c 'import sys; print(\".\".join(map(str, sys.version_info[:3])))')\" = \"3.12.11\"",
                "        run: |\n          value='open\n          #${{ secrets.X }}\n          printf '%s' \"$value\"",
                1,
            ),
        )
        for index, text in enumerate(cases):
            with self.subTest(index=index):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(".github/workflows/validate-runtime.yml", text.encode("utf-8"))
                with self.assertRaises(PublicBoundaryError):
                    validate_public_boundary(self.root, "HEAD")

    def test_activated_v1_authority_rejects_every_required_path_deletion(self) -> None:
        original = self.git("rev-parse", "HEAD").stdout.decode().strip()
        activated = self.activate_v1_authority()
        validate_public_boundary_range(self.root, original, activated)

        for relative in sorted(REQUIRED_V1_AUTHORITY_PATHS):
            with self.subTest(relative=relative):
                self.git("reset", "--hard", activated)
                self.git("clean", "-fd")
                (self.root / Path(relative)).unlink()
                head = self.commit("Remove required V1 authority")
                with self.assertRaisesRegex(PublicBoundaryError, "missing required V1"):
                    validate_public_boundary_range(self.root, activated, head)

    def test_exact_execution_migration_rotates_environment_but_not_steps(self) -> None:
        activated = self.activate_v1_authority()
        relative = ".github/workflows/release-policy.yml"
        path = self.root / Path(relative)
        text = path.read_text(encoding="utf-8")
        changed = (
            text.replace("runs-on: ubuntu-24.04", "runs-on: ubuntu-26.04", 1)
            .replace("timeout-minutes: 30", "timeout-minutes: 45", 1)
            .replace(
                "python:3.12.11-bookworm@sha256:"
                "13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12",
                "registry.nlightlabs.com/nl-assets/python-v1@sha256:" + "a" * 64,
                1,
            )
        )
        self.assertNotEqual(changed, text)
        path.write_text(changed, encoding="utf-8", newline="\n")
        blob_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        material = (
            "runtime-v1-execution-migration-v1\n"
            f"{activated}\n"
            f"M\n{relative}\n{blob_sha256}\n"
        ).encode("utf-8")
        operation_id = hashlib.sha256(material).hexdigest()
        head = self.commit("Rotate reviewed execution environment")
        branch = f"infrastructure/runtime-v1-execution/{operation_id}"

        with self.assertRaisesRegex(
            PublicBoundaryError, "bounded contract|dated Ubuntu|digest-pinned"
        ):
            validate_public_boundary_range(self.root, activated, head)
        validate_public_boundary_range(self.root, activated, head, branch)

        self.git("reset", "--hard", activated)
        self.git("clean", "-fd")
        text = path.read_text(encoding="utf-8")
        changed = text.replace(
            "          printf '%s\\n' \"$BASE_REPOSITORY\" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'",
            "          printf '%s\\n' \"$BASE_REPOSITORY\" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'\n"
            "          test -n \"$GITHUB_SERVER_URL\"",
            1,
        )
        path.write_text(changed, encoding="utf-8", newline="\n")
        blob_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        material = (
            "runtime-v1-execution-migration-v1\n"
            f"{activated}\n"
            f"M\n{relative}\n{blob_sha256}\n"
        ).encode("utf-8")
        operation_id = hashlib.sha256(material).hexdigest()
        head = self.commit("Attempt reviewed command migration")
        branch = f"infrastructure/runtime-v1-execution/{operation_id}"

        with self.assertRaisesRegex(PublicBoundaryError, "step order or command"):
            validate_public_boundary_range(self.root, activated, head, branch)

    def test_exact_required_gitignore_root_patterns_are_not_private_paths(self) -> None:
        self.add(
            ".gitignore",
            b"/" + b"assets/*\n!/" + b"assets/.gitkeep\n",
        )
        validate_public_boundary(self.root, "HEAD")

    def test_gitignore_path_comments_and_variants_remain_fail_closed(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        cases = (
            b"# absolute path " + b"/" + b"opt/private-master\n",
            b"/" + b"assets/**\n",
        )
        for data in cases:
            with self.subTest(data=data):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(".gitignore", data)
                with self.assertRaisesRegex(PublicBoundaryError, "absolute/private path"):
                    validate_public_boundary(self.root, "HEAD")

    def test_objects_assets_binaries_private_paths_and_secrets_fail(self) -> None:
        json_unc = b"\\" * 4 + b"server" + b"\\" * 2 + b"share" + b"\\" * 2 + b"x"
        json_unix = b"/" + b"home/user/master"
        json_etc = b"/" + b"etc/private-config"
        json_var = b"/" + b"var/lib/private-state"
        cases = (
            ("objects/sha256/aa/private-master.ai", b"private source"),
            ("assets/fixture.webp", b"RIFF-not-public"),
            ("assets/.gitkeep", b"armored-or-text-payload"),
            ("docs/preview.png", b"not-text"),
            (
                "manifests/private.json",
                b'{"path":"' + b"X:" + b'\\\\synthetic-private-root\\\\private-master.ai"}\n',
            ),
            ("README.md", b"ghp_" + b"A" * 24 + b"\n"),
            ("README.md", b"ghs_" + b"A" * 36 + b"\n"),
            ("README.md", b"-----BEGIN ENCRYPTED " + b"PRIVATE KEY-----\n"),
            ("README.md", b"-----BEGIN DSA " + b"PRIVATE KEY-----\n"),
            ("README.md", b"-----BEGIN PGP " + b"PRIVATE KEY BLOCK-----\n"),
            ("README.md", b"ASIA" + b"A" * 16 + b"\n"),
            (
                "manifests/private.json",
                b'{"source":"source=' + b"X:" + b'\\\\synthetic-private-root\\\\private.ai"}\n',
            ),
            (
                "manifests/private.json",
                b'{"source":"`' + b"X:" + b'\\\\synthetic-private-root\\\\private.ai`"}\n',
            ),
            ("manifests/private.json", b'{"source":"path=' + json_unc + b'"}\n'),
            ("manifests/private.json", b'{"source":"path=`' + json_unc + b'`"}\n'),
            ("manifests/private.json", b'{"source":"origin=' + json_unix + b'"}\n'),
            ("manifests/private.json", b'{"source":"origin=`' + json_unix + b'`"}\n'),
            ("manifests/private.json", b'{"source":"origin=' + json_etc + b'"}\n'),
            ("manifests/private.json", b'{"source":"origin=`' + json_var + b'`"}\n'),
            ("README.md", b"/" + b"opt/nll/runtime/source-master.ai\n"),
            ("README.md", b"source:" + b"/" + b"srv/asset-library/master.psd\n"),
            ("README.md", b"path:" + b"/" + b"tmp/private-export.zip\n"),
            ("README.md", b"/" + b"workspace/internal/source.ai\n"),
            (
                "README.md",
                b"~" + b"/" + b"Documents/runtime-masters/source.ai\n",
            ),
            ("manifests/private.json", b'{"source":"source:\\/srv/library/master.psd"}\n'),
        )
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        for relative, data in cases:
            with self.subTest(relative=relative):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(relative, data)
                with self.assertRaises(PublicBoundaryError):
                    validate_public_boundary(self.root, "HEAD")

    def test_https_cdn_url_is_not_misclassified_as_a_unc_path(self) -> None:
        self.add(
            "manifests/assets.json",
            b'{"url":"https://cdn.nlightlabs.com/objects/sha256/aa/public.webp"}\n',
        )
        validate_public_boundary(self.root, "HEAD")

    def test_credential_shaped_tracked_path_is_rejected_without_echoing_it(self) -> None:
        credential = "ghp_" + "A" * 24
        self.add(f"docs/{credential}.md", b"# Innocent contents\n")

        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertIn("credential-shaped content", str(captured.exception))
        self.assertNotIn(credential, str(captured.exception))

    def test_private_vault_path_component_is_rejected_without_echo(self) -> None:
        separator = "/"
        relative = "docs/" + "vault" + separator + "key.md"
        self.add(relative, b"# Innocent contents\n")
        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertIn("private or credential-shaped", str(captured.exception))
        self.assertNotIn(relative, str(captured.exception))

    def test_labeled_provider_credentials_are_rejected_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        credentials = (
            "CLOUDFLARE_API_TOKEN=" + "A" * 40,
            "Authorization: Bearer " + "B" * 40,
            "api_key=" + "C" * 40,
            "AWS_" + "SECRET_ACCESS_KEY=" + "D" * 40,
            "R2_" + "SECRET_ACCESS_KEY=" + "E" * 40,
            "R2_" + "ACCESS_KEY_ID=" + "F" * 32,
            "GOOGLE_" + "API_KEY=" + "AIza" + "G" * 35,
            "AWS_" + "SESSION_TOKEN=" + "H" * 80,
            "GOOGLE_" + "CLIENT_SECRET=" + "GOCSPX-" + "I" * 24,
            '"client_' + 'secret":"GOCSPX-' + "J" * 24 + '"',
            "CF_" + "ACCESS_CLIENT_SECRET=" + "a1" * 32,
            "CLOUDFLARE_" + "ACCESS_CLIENT_SECRET=" + "b2" * 32,
            "https://r2.example.invalid/object?X-Amz-Credential="
            + "1a" * 16
            + "%2F20260901%2Fauto%2Fs3%2Faws4_request",
            "X-Amz-Security-" + "Token=" + "K" * 80,
            "X-Amz-" + "Signature%3D" + "c3" * 32,
            "X-Amz-"
            + "Credential: "
            + "2b" * 16
            + "/"
            + "20260901/auto/s3/aws4_request",
            "https://r2.example.invalid/object?X%2dAmz%2dCredential="
            + "3c" * 16
            + "%2F20260901%2Fauto%2Fs3%2Faws4_request",
            "https://r2.example.invalid/object?X%2D%41mz%2DSecurity%2DToken="
            + "Q" * 80,
            "https://r2.example.invalid/object?%58-Amz-%53ignature="
            + "d4" * 32,
        )
        for credential in credentials:
            with self.subTest(kind=credential[:12]):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add("README.md", ("# Public fixture\n" + credential + "\n").encode())
                with self.assertRaises(PublicBoundaryError) as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn(credential, str(captured.exception))

        self.git("reset", "--hard", base)
        self.git("clean", "-fd")
        self.add(
            "README.md",
            b"# Configuration labels\n"
            b"CLOUDFLARE_API_TOKEN=<stored-secret>\n"
            b"Authorization: Bearer <redacted>\n"
            b"api_key=${RUNTIME_API_KEY}\n"
            b"AWS_SECRET_ACCESS_KEY=<stored-secret>\n"
            b"R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID}\n"
            b"GOOGLE_API_KEY=<redacted>\n"
            b"AWS_SESSION_TOKEN=<stored-secret>\n"
            b"GOOGLE_CLIENT_SECRET=<redacted>\n"
            b'"client_secret":"<stored-secret>"\n'
            b"CF_ACCESS_CLIENT_SECRET=<stored-secret>\n"
            b"CLOUDFLARE_ACCESS_CLIENT_SECRET=${CF_ACCESS_CLIENT_SECRET}\n"
            b"X-Amz-Credential=<redacted>\n"
            b"X-Amz-Security-Token=${R2_SESSION_TOKEN}\n"
            b"X-Amz-Signature=<stored-secret>\n",
        )
        validate_public_boundary(self.root, "HEAD")

    def test_r2_sigv4_presigned_url_is_rejected_without_echo(self) -> None:
        access_key = "3d" * 16
        signature = "4e" * 32
        token = "T" * 80
        presigned = (
            "https://r2.example.invalid/private-object?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Credential={access_key}%2F20260901%2Fauto%2Fs3%2Faws4_request"
            f"&X-Amz-Security-Token={token}&X-Amz-Signature={signature}"
        )
        self.add("README.md", ("# Accidental URL\n" + presigned + "\n").encode())
        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertNotIn(access_key, str(captured.exception))
        self.assertNotIn(signature, str(captured.exception))
        self.assertNotIn(token, str(captured.exception))

    def test_publishing_contract_is_v1_only_until_global_tag_dispatch_migrates(self) -> None:
        contract = (ROOT / "docs" / "PUBLISHING-CONTRACT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("exhaustively enumerates every flat, nested, loose, or packed tag ref", contract)
        self.assertIn("current global dispatcher is deliberately V1-only", contract)
        self.assertRegex(
            contract,
            r"semantically validates\s+only every `runtime-v1-`-prefixed ref",
        )
        self.assertRegex(
            contract,
            r"No\s+V2\s+tag\s+or\s+artifact\s+may\s+be\s+introduced",
        )
        self.assertIn("never a relaxation of V1", contract)
        self.assertIn("validate_runtime_release.py --tag-object", contract)
        self.assertIn("must not be merged to `main`", contract)
        self.assertIn("ownership topology before activation", contract)
        self.assertIn("may not edit the locked schema IDs or rely on redirects", contract)
        self.assertIn("Before the activation-marker merge", contract)
        self.assertRegex(
            contract, r"private\s+gateway/provider\s+reconciliation\s+rechecks"
        )
        self.assertRegex(
            contract,
            r"public\s+validator\s+generic-scans\s+the\s+complete\s+raw\s+commit\s+bytes",
        )
        self.assertLess(
            contract.index("must not be merged to `main`"),
            contract.index("### GitHub enforcement"),
        )
        validation = (ROOT / "docs" / "VALIDATION_AND_DISCOVERY.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            validation,
            r"prove\s+that\s+every\s+immutable\s+candidate\s+schema\s+path\s+has\s+identical",
        )
        self.assertRegex(
            validation,
            r"evaluate\s+the\s+candidate-tree\s+schema\s+copies",
        )

    def test_json_escaped_credentials_and_duplicate_keys_fail_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        token = "ghp_" + "A" * 24
        escaped = b"ghp_" + b"\\u0041" * 24
        escaped_etc = b"\\/" + b"etc\\/private-config"
        escaped_vault = b"relative\\/" + b"vault\\/master.ai"
        cases = (
            b'{"note":"' + escaped + b'"}\n',
            b'{"' + escaped + b'":1,"' + escaped + b'":2}\n',
            b'{"path":"' + escaped_etc + b'"}\n',
            b'{"path":"' + escaped_vault + b'"}\n',
        )
        for data in cases:
            with self.subTest(data=data[:12]):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add("tests/fixtures/escaped-secret.json", data)
                with self.assertRaises(PublicBoundaryError) as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn(token, str(captured.exception))

    def test_json_escaped_labeled_credentials_are_scanned_as_decoded_relationships(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        cases = (
            (b'cloudflare_api\\u005ftoken', b"A" * 24),
            (b'aws_secret\\u005faccess_key', b"B" * 40),
            (b'r2_access_key\\u005fid', b"C" * 32),
            (b'aws_session\\u005ftoken', b"D" * 64),
            (b'google_client\\u005fsecret', b"GOCSPX-" + b"E" * 28),
            (b'cf_access_client\\u005fsecret', b"a1" * 32),
            (b'X-Amz\\u002dSignature', b"f2" * 32),
            (b'AccessKey\\u0049d', b"Z" * 20),
            (b'SecretAccessKey', b"S" * 40),
            (b'SessionToken', b"T" * 64),
            (b'cloudflareApi\\u0054oken', b"U" * 24),
            (b'api\\u005ftoken', b"V" * 24),
        )
        for encoded_key, credential in cases:
            with self.subTest(key=encoded_key):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                data = b'{"' + encoded_key + b'":"' + credential + b'"}\n'
                self.add("tests/fixtures/escaped-labeled-secret.json", data)
                with self.assertRaises(PublicBoundaryError) as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn(credential.decode("ascii"), str(captured.exception))

        self.git("reset", "--hard", base)
        self.git("clean", "-fd")
        self.add(
            "tests/fixtures/escaped-labeled-placeholders.json",
            b'{"cloudflare_api\\u005ftoken":"<stored-secret>",'
            b'"aws_secret\\u005faccess_key":"${AWS_SECRET_ACCESS_KEY}",'
            b'"google_client\\u005fsecret":"<redacted>",'
            b'"X-Amz\\u002dSignature":"${R2_SIGNATURE}"}\n',
        )
        validate_public_boundary(self.root, "HEAD")

    def test_nested_decoded_label_descendant_credentials_fail_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        cases = (
            (
                b'{"cloudflare_api\\u005ftoken":{"metadata":["'
                + b"N" * 24
                + b'"]}}\n',
                "N" * 24,
            ),
            (
                b'{"SecretAccessKey":[{"value":"' + b"P" * 40 + b'"}]}\n',
                "P" * 40,
            ),
            (
                b'{"%63loudflare%41pi%54oken":{"metadata":["'
                + b"W" * 24
                + b'"]}}\n',
                "W" * 24,
            ),
            (
                b'{"%41ccessKeyId":{"values":["' + b"X" * 20 + b'"]}}\n',
                "X" * 20,
            ),
        )
        for data, credential in cases:
            with self.subTest(data=data[:36]):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add("tests/fixtures/nested-labeled-secret.json", data)
                with self.assertRaises(PublicBoundaryError) as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn(credential, str(captured.exception))

        self.git("reset", "--hard", base)
        self.git("clean", "-fd")
        self.add(
            "tests/fixtures/nested-labeled-placeholder.json",
            b'{"cloudflare_api\\u005ftoken":{"metadata":["<stored-secret>"]}}\n',
        )
        validate_public_boundary(self.root, "HEAD")

    def test_public_json_depth_bound_accepts_64_and_rejects_65_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        depth_64 = b"[" * 64 + b"0" + b"]" * 64 + b"\n"
        self.add("tests/fixtures/depth.json", depth_64)
        validate_public_boundary(self.root, "HEAD")

        self.git("reset", "--hard", base)
        self.git("clean", "-fd")
        secret = "SENSITIVE-NESTED-MARKER"
        depth_65 = b"[" * 65 + ('"' + secret + '"').encode() + b"]" * 65 + b"\n"
        self.add("tests/fixtures/depth.json", depth_65)
        with self.assertRaisesRegex(PublicBoundaryError, "maximum reviewed nesting") as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertNotIn(secret, str(captured.exception))

    def test_json_escaped_utf16_surrogates_are_rejected_in_values_and_keys(self) -> None:
        for data in (
            b'{"value":"' + b"\\" + b"ud800" + b'"}\n',
            b'{"' + b"\\" + b'udfff":1}\n',
        ):
            with self.subTest(data=data):
                self.add("tests/fixtures/escaped-surrogate.json", data)
                with self.assertRaises(PublicBoundaryError) as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn("ud800", str(captured.exception).lower())
                self.assertNotIn("udfff", str(captured.exception).lower())

    def test_unsafe_or_nonregular_credential_paths_are_never_echoed(self) -> None:
        credential = "ghp_" + "A" * 24
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()

        unsafe = self.root / "docs" / f"{credential}-é.md"
        unsafe.parent.mkdir(parents=True, exist_ok=True)
        unsafe.write_text("# Innocent contents\n", encoding="utf-8")
        self.commit("Add unsafe public path")
        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertNotIn(credential, str(captured.exception))

        self.git("reset", "--hard", base)
        self.git("clean", "-fd")
        executable = self.root / "docs" / f"{credential}.md"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("# Innocent contents\n", encoding="utf-8")
        self.git("add", "--all")
        self.git("update-index", "--chmod=+x", f"docs/{credential}.md")
        self.git("commit", "-m", "Add non-regular public entry")
        with self.assertRaises(PublicBoundaryError) as captured:
            validate_public_boundary(self.root, "HEAD")
        self.assertNotIn(credential, str(captured.exception))

    def test_control_characters_in_tracked_paths_are_rejected_without_echo(self) -> None:
        relative = "docs/a\n::warning::spoof.md"
        with self.assertRaises(PublicBoundaryError) as captured:
            _normalized_path(relative)
        self.assertIn("prohibited control text", str(captured.exception))
        self.assertNotIn("::warning::spoof", str(captured.exception))

    def test_bidi_controls_fail_in_every_tracked_text_class_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        marker = "\u202e"
        workflow = (
            "name: Reviewed\n"
            "on:\n  push:\n  pull_request:\n  schedule:\n"
            "permissions:\n  contents: read\n"
            "jobs:\n  validate:\n    runs-on: ubuntu-24.04\n"
            "    container:\n"
            "      image: python:3.12.11-bookworm@sha256:"
            "13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12\n"
            f"    # {marker}\n    steps: []\n"
        ).encode("utf-8")
        cases = (
            ("README.md", f"# Review {marker}\n".encode("utf-8")),
            ("tools/reviewed.py", f"# Review {marker}\n".encode("utf-8")),
            (".github/workflows/validate-runtime.yml", workflow),
        )
        for relative, data in cases:
            with self.subTest(relative=relative):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(relative, data)
                with self.assertRaisesRegex(PublicBoundaryError, "prohibited control text") as captured:
                    validate_public_boundary(self.root, "HEAD")
                self.assertNotIn(marker, str(captured.exception))

    def test_unknown_manifest_and_git_lfs_transport_are_rejected(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        cases = (
            (
                "manifests/private-student-roster.json",
                b'{"studentName":"Alice Example"}\n',
                "explicit public repository set",
            ),
            (
                "manifests/assets.json",
                b"version https://git-lfs.github.com/spec/v1\n"
                b"oid sha256:" + b"a" * 64 + b"\nsize 123\n",
                "Git LFS pointers",
            ),
            (
                ".gitattributes",
                b"manifests/*.json filter=lfs diff=lfs merge=lfs -text\n",
                "Git LFS filters",
            ),
        )
        for relative, data, message in cases:
            with self.subTest(relative=relative):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                self.add(relative, data)
                with self.assertRaisesRegex(PublicBoundaryError, message):
                    validate_public_boundary(self.root, "HEAD")

    def test_commit_range_rejects_lfs_pointer_deleted_from_final_tree(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        pointer = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 123\n"
        )
        self.add("manifests/assets.json", pointer)
        (self.root / "manifests" / "assets.json").unlink()
        (self.root / "README.md").write_text("# Safe final tree\n", encoding="utf-8")
        head = self.commit("Remove LFS pointer")

        with self.assertRaisesRegex(PublicBoundaryError, "Git LFS pointers"):
            validate_public_boundary_range(self.root, base, head)

    def test_oversized_public_text_fails(self) -> None:
        self.add("README.md", b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(PublicBoundaryError, "exceeds"):
            validate_public_boundary(self.root, "HEAD")

    def test_commit_range_rejects_private_blob_deleted_from_final_tree(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        private_path = self.root / "private-source.pem"
        private_path.write_text("not a real credential\n", encoding="utf-8")
        hidden_commit = self.commit("Add private intermediate blob")
        private_path.unlink()
        (self.root / "README.md").write_text("# Safe final tree\n", encoding="utf-8")
        head = self.commit("Remove private blob")

        validate_public_boundary(self.root, head)
        self.assertEqual(
            self.git("cat-file", "-t", f"{hidden_commit}:private-source.pem").stdout.decode().strip(),
            "blob",
        )
        with self.assertRaisesRegex(PublicBoundaryError, "forbidden"):
            validate_public_boundary_range(self.root, base, head)

    def test_commit_range_rejects_relative_private_vault_path_deleted_later(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        private_component = "vault"
        self.add(
            "manifests/assets.json",
            ('{"source":"relative/' + private_component + '/' + 'master.ai"}\n').encode(),
        )
        (self.root / "manifests" / "assets.json").unlink()
        (self.root / "README.md").write_text("# Safe final tree\n", encoding="utf-8")
        head = self.commit("Remove private relative path")

        validate_public_boundary(self.root, head)
        with self.assertRaisesRegex(PublicBoundaryError, "absolute/private path"):
            validate_public_boundary_range(self.root, base, head)

    def test_commit_range_rejects_credential_shaped_commit_message(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        (self.root / "README.md").write_text("# Safe candidate tree\n", encoding="utf-8")
        head = self.commit("ghs_" + "A" * 36)

        with self.assertRaisesRegex(PublicBoundaryError, "metadata or message"):
            validate_public_boundary_range(self.root, base, head)

    def test_commit_range_rejects_credential_shaped_author_identity(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("config", "user.name", "ghs_" + "A" * 36)
        (self.root / "README.md").write_text("# Safe candidate tree\n", encoding="utf-8")
        head = self.commit("Safe-looking subject")

        with self.assertRaisesRegex(PublicBoundaryError, "metadata or message"):
            validate_public_boundary_range(self.root, base, head)

    def test_commit_range_rejects_bidi_commit_identity_without_echo(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        marker = "\u202e"
        self.git("config", "user.name", "Safe" + marker + "Review")
        (self.root / "README.md").write_text("# Safe candidate tree\n", encoding="utf-8")
        head = self.commit("Safe-looking subject")

        with self.assertRaisesRegex(PublicBoundaryError, "prohibited control text") as captured:
            validate_public_boundary_range(self.root, base, head)
        self.assertNotIn(marker, str(captured.exception))

    def test_public_entrypoint_rejects_late_and_duplicate_raw_parent_headers(self) -> None:
        parent = self.git("rev-parse", "HEAD").stdout.decode().strip()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.decode().strip()
        identity_headers = (
            "author Boundary Fixture <boundary-fixture@example.invalid> 1788264000 +0000\n"
            "committer Boundary Fixture <boundary-fixture@example.invalid> 1788264000 +0000\n"
        )
        malformed = (
            f"tree {tree}\n{identity_headers}parent {parent}\n\nLate parent\n",
            f"tree {tree}\nparent {parent}\nparent {parent}\n"
            f"{identity_headers}\nDuplicate parent\n",
        )
        for raw_commit in malformed:
            with self.subTest(kind="duplicate" if raw_commit.count("parent ") == 2 else "late"):
                revision = self.git(
                    "hash-object",
                    "--literally",
                    "-t",
                    "commit",
                    "-w",
                    "--stdin",
                    input_bytes=raw_commit.encode("ascii"),
                ).stdout.decode().strip()
                with self.assertRaisesRegex(PublicBoundaryError, "parent"):
                    validate_public_boundary(self.root, revision)

    def test_public_boundary_refuses_local_replace_refs(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.decode().strip()
        credential = "ghp_" + "A" * 24
        (self.root / "README.md").write_text(
            "# Unsafe original\n" + credential + "\n", encoding="utf-8"
        )
        unsafe = self.commit("Create unsafe original")

        self.git("switch", "-c", "safe-replacement", base)
        (self.root / "README.md").write_text("# Different safe tree\n", encoding="utf-8")
        replacement = self.commit("Create safe replacement")
        self.git("replace", unsafe, replacement)

        with self.assertRaisesRegex(PublicBoundaryError, "replacement-object refs") as captured:
            validate_public_boundary(self.root, unsafe)
        self.assertNotIn(credential, str(captured.exception))

    def test_public_boundary_refuses_legacy_grafts_and_shallow_history(self) -> None:
        head = self.git("rev-parse", "HEAD").stdout.decode().strip()
        for relative in ("info/grafts", "shallow"):
            raw = self.git(
                "rev-parse", "--path-format=absolute", "--git-path", relative
            ).stdout.decode().strip()
            path = Path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(head + "\n", encoding="ascii")
            expected = "legacy grafts" if relative == "info/grafts" else "shallow history"
            with self.assertRaisesRegex(PublicBoundaryError, expected):
                validate_public_boundary(self.root, "HEAD")
            path.unlink()

    def test_public_boundary_refuses_git_object_store_environment_override(self) -> None:
        with patch.dict(
            os.environ,
            {"GIT_OBJECT_DIRECTORY": str(self.root / "substituted-objects")},
        ):
            with self.assertRaisesRegex(PublicBoundaryError, "environment or object-store"):
                validate_public_boundary(self.root, "HEAD")

    def test_public_boundary_refuses_alternate_object_store_file(self) -> None:
        raw = self.git(
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "objects/info/alternates",
        ).stdout.decode().strip()
        alternate = self.root / "alternate-objects"
        alternate.mkdir()
        path = Path(raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(alternate.as_posix() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(PublicBoundaryError, "alternate object stores"):
            validate_public_boundary(self.root, "HEAD")


if __name__ == "__main__":
    unittest.main()
