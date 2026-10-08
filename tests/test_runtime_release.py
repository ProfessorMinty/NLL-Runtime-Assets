from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "runtime-release"
sys.path.insert(0, str(TOOLS))

from validate_runtime_release import (  # noqa: E402
    CURRENT_POINTER_PATH,
    EVOLVABLE_V1_EXECUTION_PATHS,
    IMMUTABLE_V1_AUTHORITY_PATHS,
    IMMUTABLE_V1_WHEEL_PATHS,
    ReleaseValidationError,
    artifact_operation_identity,
    canonical_json_bytes,
    consumer_catalog_path,
    execution_migration_identity,
    expected_consumer_asset_version,
    load_json_bytes,
    normalize_repo_path,
    pointer_operation_identity,
    reject_private_strings,
    require_release_id,
    release_directory_path,
    release_document_path,
    validate_pointer,
    validate_pull_request,
    validate_release_directory,
    validate_release_graph,
    validate_repository,
    validate_global_tag_namespace,
    validate_schema,
    validate_tag,
    validate_unreferenced_tag_object,
)
from validate_runtime_release_v1 import (  # noqa: E402
    _validate_fallback_graph,
    validate_repository as validate_v1_repository,
    validate_unreferenced_tag_object as validate_v1_unreferenced_tag_object,
)


RELEASE_ONE = "runtime-v1-2026.09.01.1"
RELEASE_TWO = "runtime-v1-2026.09.01.2"
RELEASE_THREE = "runtime-v1-2026.09.01.3"
OBJECT_SHA = "a" * 64
OBJECT_KEY = f"objects/sha256/aa/{OBJECT_SHA}.webp"


class RuntimeReleaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "schemas").mkdir(parents=True)
        for name in ("runtime-release-v1.schema.json", "runtime-current-pointer-v1.schema.json"):
            shutil.copy2(ROOT / "schemas" / name, self.root / "schemas" / name)
        shutil.copy2(
            ROOT / "schemas" / "nl-asset-consumer-catalog-v1.schema.json",
            self.root / "schemas" / "nl-asset-consumer-catalog-v1.schema.json",
        )
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Runtime Fixture")
        self.git("config", "user.email", "runtime-fixture@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.eol", "lf")
        for relative in (
            ".gitattributes",
            "requirements-ci.txt",
            "tools/verify_v1_wheelhouse.py",
            *sorted(IMMUTABLE_V1_WHEEL_PATHS),
            *sorted(EVOLVABLE_V1_EXECUTION_PATHS),
        ):
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.write_json("fixture-root.json", {"fixture": True})
        self.commit("Create fixture repository")
        self.base = self.sha()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            input=input_bytes,
            capture_output=True,
            check=False,
        )
        if check and result.returncode:
            self.fail(result.stderr.decode("utf-8", errors="replace"))
        return result

    def sha(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", message)
        return self.sha()

    def replace_index_blob(self, relative: str, data: bytes) -> None:
        object_id = self.git(
            "hash-object", "-w", "--stdin", input_bytes=data
        ).stdout.decode().strip()
        self.git("update-index", "--cacheinfo", f"100644,{object_id},{relative}")

    def write_json(self, relative: str, value: object) -> None:
        path = self.root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(value))

    def catalog(self) -> dict:
        return json.loads((FIXTURES / "consumer-catalog.json").read_text(encoding="utf-8"))

    def add_release(self, release_id: str, predecessor: str = "") -> dict:
        catalog = self.catalog()
        release_date = release_id.removeprefix("runtime-v1-").rsplit(".", 1)[0].replace(".", "-")
        timestamp = f"{release_date}T12:00:00Z"
        catalog["releaseId"] = release_id
        catalog["generatedAt"] = timestamp
        for asset in catalog["assets"]:
            asset["releaseId"] = release_id
        catalog_bytes = canonical_json_bytes(catalog)
        self.write_json(consumer_catalog_path(release_id).as_posix(), catalog)
        release = {
            "candidateIdentity": f"sha256:{'c' * 64}",
            "consumerCatalog": {
                "path": consumer_catalog_path(release_id).as_posix(),
                "schemaVersion": "1.0.0",
                "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
            },
            "createdAt": timestamp,
            "objects": [
                {
                    "bytes": 12,
                    "objectKey": OBJECT_KEY,
                    "sha256": OBJECT_SHA,
                    "url": f"https://cdn.nlightlabs.com/{OBJECT_KEY}",
                }
            ],
            "predecessorReleaseId": predecessor,
            "publicationAuthorizationIdentity": f"sha256:{'d' * 64}",
            "publisherIdentity": "NL Asset Runtime Publisher",
            "releaseId": release_id,
            "transactionRecoveryAuthorizationIdentity": f"sha256:{'e' * 64}",
            "schemaVersion": 1,
        }
        self.write_json(release_document_path(release_id).as_posix(), release)
        return release

    def pointer(self, release: dict, commit: str) -> dict:
        catalog = release["consumerCatalog"]
        return {
            "catalogPath": catalog["path"],
            "catalogSchemaVersion": catalog["schemaVersion"],
            "catalogSha256": catalog["sha256"],
            "predecessorReleaseId": release["predecessorReleaseId"],
            "publicationAuthorizationIdentity": release["publicationAuthorizationIdentity"],
            "releaseArtifactCommit": commit,
            "releaseId": release["releaseId"],
            "schemaVersion": 1,
        }

    def annotated_tag(
        self,
        tag: str,
        commit: str,
        message: bytes,
        internal_tag: str | None = None,
        tagger_identity: str | None = None,
        create_ref: bool = True,
    ) -> str:
        identity = tagger_identity or (
            "NL Asset Runtime Publisher "
            "<nl-asset-runtime-publisher[bot]@users.noreply.github.com>"
        )
        tag_object = (
            f"object {commit}\ntype commit\ntag {internal_tag or tag}\n"
            f"tagger {identity} 1788264000 +0000\n\n"
        ).encode() + message
        tag_sha = self.git("mktag", input_bytes=tag_object).stdout.decode().strip()
        if create_ref:
            self.git("update-ref", f"refs/tags/{tag}", tag_sha)
        return tag_sha

    def merge_release(self, release_id: str, predecessor: str = "") -> tuple[dict, str]:
        base_branch = self.git("branch", "--show-current").stdout.decode().strip()
        base_commit = self.sha()
        release = self.add_release(release_id, predecessor)
        branch = self.artifact_branch(release_id, base_commit)
        self.git("switch", "-c", branch)
        purpose_head = self.commit(f"Add {release_id}")
        self.git("switch", base_branch)
        self.git("merge", "--no-ff", purpose_head, "-m", f"Merge {release_id}")
        return release, self.sha()

    def artifact_branch(self, release_id: str, base: str) -> str:
        release_bytes = (self.root / release_document_path(release_id)).read_bytes()
        catalog_bytes = (self.root / consumer_catalog_path(release_id)).read_bytes()
        release = json.loads(release_bytes)
        source = release["predecessorReleaseId"] or "none"
        operation_id = artifact_operation_identity(
            release_id, source, base, release_bytes, catalog_bytes
        )
        return f"publish/artifacts/{release_id}/from/{source}/{operation_id}"

    def pointer_branch(
        self, operation: str, pointer: dict, source: str, base: str | None = None
    ) -> str:
        target = pointer["releaseId"]
        pointer_bytes = canonical_json_bytes(pointer)
        operation_id = pointer_operation_identity(
            operation, target, source, base or self.sha(), pointer_bytes
        )
        return f"publish/pointer/{operation}/{target}/from/{source}/{operation_id}"

    def prepare_tagged_release(self, release_id: str = RELEASE_ONE, predecessor: str = "") -> tuple[dict, dict, str]:
        release, commit = self.merge_release(release_id, predecessor)
        pointer = self.pointer(release, commit)
        self.annotated_tag(release_id, commit, canonical_json_bytes(pointer))
        return release, pointer, commit

    def merge_pointer(
        self, operation: str, pointer: dict, source: str
    ) -> tuple[str, str]:
        base_branch = self.git("branch", "--show-current").stdout.decode().strip()
        base_commit = self.sha()
        branch = self.pointer_branch(operation, pointer, source, base_commit)
        self.git("switch", "-c", branch)
        self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
        purpose_head = self.commit(f"Prepare {operation} pointer")
        self.git("switch", base_branch)
        self.git("merge", "--no-ff", purpose_head, "-m", f"Merge {operation} pointer")
        return purpose_head, self.sha()

    def test_infrastructure_tree_without_release_or_catalog_contract_passes(self) -> None:
        (self.root / "schemas" / "nl-asset-consumer-catalog-v1.schema.json").unlink()
        validate_repository(self.root, self.sha())

    def test_repository_requires_exact_release_and_pointer_merge_provenance(self) -> None:
        self.add_release(RELEASE_ONE)
        direct_release = self.commit("Bypass artifact purpose merge")
        with self.assertRaisesRegex(
            ReleaseValidationError, "two-parent|merge provenance"
        ):
            validate_repository(self.root, direct_release)
        validate_repository(
            self.root, direct_release, allow_unmerged_tip=True
        )

        self.git("reset", "--hard", self.base)
        release, pointer, artifact_commit = self.prepare_tagged_release()
        self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
        direct_pointer = self.commit("Bypass pointer purpose merge")
        with self.assertRaisesRegex(ReleaseValidationError, "two-parent"):
            validate_repository(self.root, direct_pointer)

        self.git("reset", "--hard", artifact_commit)
        _purpose_head, pointer_merge = self.merge_pointer("select", pointer, "none")
        validate_repository(self.root, pointer_merge)
        self.assertEqual(release["releaseId"], RELEASE_ONE)

    def test_repository_rejects_missing_retained_purpose_ref(self) -> None:
        _release, artifact_commit = self.merge_release(RELEASE_ONE)
        branch = self.git("for-each-ref", "--format=%(refname:short)", "refs/heads/publish/artifacts").stdout.decode().strip()
        self.assertTrue(branch.startswith("publish/artifacts/"))
        self.git("branch", "-D", branch)
        with self.assertRaisesRegex(ReleaseValidationError, "retained purpose branch"):
            validate_repository(self.root, artifact_commit)

    def test_nested_runtime_prefixed_tag_is_enumerated_and_rejected(self) -> None:
        self.git("update-ref", f"refs/tags/{RELEASE_ONE}/evil", self.sha())
        with self.assertRaisesRegex(ReleaseValidationError, "release tag"):
            validate_v1_repository(self.root, self.sha())

    def test_global_dispatcher_rejects_packed_nonruntime_tag_but_retained_v1_ignores_it(self) -> None:
        self.git("update-ref", "refs/tags/unreviewed-maintenance-tag", self.sha())
        self.git("pack-refs", "--all")
        validate_v1_repository(self.root, self.sha())
        with self.assertRaisesRegex(ReleaseValidationError, "recognized runtime namespace"):
            validate_global_tag_namespace(self.root)

    def test_dispatcher_cli_loads_retained_authority_under_python_safe_path(self) -> None:
        validator = str(ROOT / "tools" / "validate_runtime_release.py")
        result = subprocess.run(
            [
                sys.executable,
                "-P",
                validator,
                "--root",
                str(self.root),
                "--repository",
                "--main",
                self.sha(),
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            (result.stdout + result.stderr).decode("utf-8", errors="replace"),
        )

        self.git("update-ref", "refs/tags/unreviewed-maintenance-tag", self.sha())
        rejected = subprocess.run(result.args, cwd=self.root, capture_output=True, check=False)
        self.assertNotEqual(rejected.returncode, 0)
        output = (rejected.stdout + rejected.stderr).decode("utf-8", errors="replace")
        self.assertNotIn("unreviewed-maintenance-tag", output)
        self.assertNotIn(str(self.root), output)

    def test_repository_mode_rejects_non_object_runtime_tag_receipt(self) -> None:
        self.annotated_tag(RELEASE_ONE, self.sha(), b"[]\n")
        with self.assertRaisesRegex(ReleaseValidationError, "JSON object"):
            validate_repository(self.root, self.sha())

    def test_cross_language_canonical_json_sensitive_fixture(self) -> None:
        fixture = json.loads(
            (FIXTURES / "canonical-json-sensitive.json").read_text(encoding="utf-8")
        )
        value = fixture["value"]
        value["escapes"] = "".join(
            chr(codepoint) for codepoint in fixture["escapesCodePoints"]
        )
        canonical = canonical_json_bytes(value)
        self.assertEqual(canonical, base64.b64decode(fixture["canonicalUtf8Base64"]))
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), fixture["canonicalSha256"])

    def test_canonical_json_rejects_unpaired_utf16_surrogates(self) -> None:
        with self.assertRaisesRegex(ReleaseValidationError, "unpaired UTF-16"):
            canonical_json_bytes({"value": "\ud800"})

    def test_json_loader_rejects_nonstandard_numeric_constants_without_echo(self) -> None:
        for token in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(
                    ReleaseValidationError, "not valid strict JSON"
                ) as captured:
                    load_json_bytes(b'{"value":' + token + b'}\n', "numeric fixture")
                self.assertNotIn(token.decode("ascii"), str(captured.exception))

    def test_json_depth_bound_is_explicit_for_loading_and_canonicalization(self) -> None:
        depth_64 = b"[" * 64 + b"0" + b"]" * 64
        loaded = load_json_bytes(depth_64, "bounded JSON fixture")
        canonical_json_bytes(loaded)

        secret = "ghp_" + "A" * 24
        depth_65 = b"[" * 65 + ('"' + secret + '"').encode() + b"]" * 65
        with self.assertRaisesRegex(ReleaseValidationError, "maximum reviewed nesting") as captured:
            load_json_bytes(depth_65, "deep JSON fixture")
        self.assertNotIn(secret, str(captured.exception))

        value: object = 0
        for _ in range(65):
            value = [value]
        with self.assertRaisesRegex(ReleaseValidationError, "maximum reviewed nesting"):
            canonical_json_bytes(value)

    def test_runtime_path_normalization_rejects_control_text_without_echo(self) -> None:
        hostile = "manifests/releases/a\n::warning::spoof.json"
        with self.assertRaises(ReleaseValidationError) as captured:
            normalize_repo_path(hostile, "Git tree path")
        self.assertIn("control or bidirectional-format", str(captured.exception))
        self.assertNotIn("::warning::spoof", str(captured.exception))

    def test_cli_never_echoes_untrusted_release_namespace_paths(self) -> None:
        self.add_release(RELEASE_ONE)
        base = self.commit("Add reviewed release fixture")
        credential = "ghp_" + "A" * 24
        cases = (
            f"manifests/releases/{RELEASE_ONE}/{credential}.json",
            f"manifests/releases/{credential}/unexpected.json",
        )
        for relative in cases:
            with self.subTest(relative=relative):
                self.git("reset", "--hard", base)
                self.git("clean", "-fd")
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
                head = self.commit("Add unsafe release namespace path")
                result = subprocess.run(
                    [
                        sys.executable,
                        "-P",
                        str(ROOT / "tools" / "validate_runtime_release_v1.py"),
                        "--root",
                        str(self.root),
                        "--repository",
                        "--main",
                        head,
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                output = (result.stdout + result.stderr).decode(
                    "utf-8", errors="replace"
                )
                self.assertNotIn(credential, output)
                self.assertNotIn(str(self.root), output)

    def test_cli_restricts_schema_root_and_requires_exact_repository_revision(self) -> None:
        validator = str(ROOT / "tools" / "validate_runtime_release_v1.py")
        restricted_modes = (
            ("--repository", "--main", self.base),
            ("--tag", RELEASE_ONE, "--main", self.base),
            (
                "--tag-object",
                "a" * 40,
                "--tag-name",
                RELEASE_ONE,
                "--main",
                self.base,
            ),
        )
        for mode_arguments in restricted_modes:
            with self.subTest(mode=mode_arguments[0]):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-P",
                        validator,
                        "--root",
                        str(self.root),
                        "--schema-root",
                        str(self.root),
                        *mode_arguments,
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(
                    str(self.root),
                    (result.stdout + result.stderr).decode("utf-8", errors="replace"),
                )

        for main_arguments in ((), ("--main", "HEAD")):
            with self.subTest(main=main_arguments):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-P",
                        validator,
                        "--root",
                        str(self.root),
                        "--repository",
                        *main_arguments,
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_cli_pull_request_binds_schema_authority_to_clean_exact_base(self) -> None:
        self.git("switch", "-c", "feature/cli-trusted-base")
        self.write_json("fixture-root.json", {"fixture": True, "reviewed": True})
        head = self.commit("Add ordinary reviewed fixture change")
        with tempfile.TemporaryDirectory() as trusted_parent:
            trusted = Path(trusted_parent) / "trusted"
            self.git("worktree", "add", "--detach", str(trusted), self.base)
            result = subprocess.run(
                [
                    sys.executable,
                    "-P",
                    str(ROOT / "tools" / "validate_runtime_release_v1.py"),
                    "--root",
                    str(self.root),
                    "--schema-root",
                    str(trusted),
                    "--pull-request",
                    "--base",
                    self.base,
                    "--head",
                    head,
                    "--branch",
                    "feature/cli-trusted-base",
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                (result.stdout + result.stderr).decode("utf-8", errors="replace"),
            )
            trusted_schema = trusted / "schemas" / "runtime-release-v1.schema.json"
            trusted_schema.write_bytes(trusted_schema.read_bytes() + b"dirty\n")
            dirty_result = subprocess.run(result.args, capture_output=True, check=False)
            self.assertNotEqual(dirty_result.returncode, 0)

    def test_release_sequence_uses_the_owning_int32_bound(self) -> None:
        require_release_id("runtime-v1-2026.09.01.2147483647")
        with self.assertRaisesRegex(ReleaseValidationError, "Int32"):
            require_release_id("runtime-v1-2026.09.01.2147483648")

    def test_catalog_and_release_schemas_share_the_full_int32_release_id_bound(self) -> None:
        release_id = "runtime-v1-2026.09.01.2147483647"
        release = self.add_release(release_id)
        validate_release_directory(self.root, release_id)
        self.assertEqual(release["releaseId"], release_id)

    def test_public_numeric_and_delivery_bounds_match_the_owning_dotnet_contract(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        variant = catalog["assets"][0]["variants"][0]
        variant["bytes"] = 16_777_216
        variant["width"] = 2_147_483_647
        variant["height"] = 2_147_483_647
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["objects"][0]["bytes"] = 16_777_216
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

        for label, field, value in (
            ("bytes", "bytes", 16_777_217),
            ("width", "width", 2_147_483_648),
            ("height", "height", 2_147_483_648),
        ):
            with self.subTest(label=label):
                catalog["assets"][0]["variants"][0][field] = value
                catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                    catalog["assets"][0]
                )
                self.write_json(catalog_path, catalog)
                release["objects"][0]["bytes"] = catalog["assets"][0]["variants"][0]["bytes"]
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
                    validate_release_directory(self.root, RELEASE_ONE)
                catalog["assets"][0]["variants"][0][field] = (
                    16_777_216 if field == "bytes" else 2_147_483_647
                )

    def test_runtime_object_set_has_per_object_and_aggregate_delivery_bounds(self) -> None:
        from validate_runtime_release import _validate_runtime_objects

        def runtime_object(index: int, size: int) -> dict:
            digest = f"{index:064x}"
            key = f"objects/sha256/{digest[:2]}/{digest}.glb"
            return {
                "bytes": size,
                "objectKey": key,
                "sha256": digest,
                "url": f"https://cdn.nlightlabs.com/{key}",
            }

        _validate_runtime_objects([runtime_object(1, 67_108_864)])
        with self.assertRaisesRegex(ReleaseValidationError, "object exceeds"):
            _validate_runtime_objects([runtime_object(1, 67_108_865)])
        with self.assertRaisesRegex(ReleaseValidationError, "aggregate"):
            _validate_runtime_objects(
                [runtime_object(index, 67_108_864) for index in range(1, 130)]
            )

    def test_raster_variants_require_positive_known_dimensions(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        variant = catalog["assets"][0]["variants"][0]
        variant["width"] = None
        variant["height"] = None
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)

        with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_date_time_schema_format_is_actually_enforced(self) -> None:
        schema = {"type": "string", "format": "date-time"}
        validate_schema("2026-09-01T12:00:00Z", schema, "valid date-time")
        with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
            validate_schema("definitely-not-a-date", schema, "invalid date-time")

    def test_asset_id_length_bounds_match_the_owning_contract(self) -> None:
        for asset_id, valid in (
            ("abc", True),
            ("a" * 160, True),
            ("ab", False),
            ("a" * 161, False),
        ):
            with self.subTest(length=len(asset_id), valid=valid):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fd")
                release = self.add_release(RELEASE_ONE)
                catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
                catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
                catalog["assets"][0]["assetId"] = asset_id
                catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                    catalog["assets"][0]
                )
                self.write_json(catalog_path, catalog)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                if valid:
                    validate_release_directory(self.root, RELEASE_ONE)
                else:
                    with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
                        validate_release_directory(self.root, RELEASE_ONE)

    def test_v1_collection_bounds_are_explicit_and_fail_closed(self) -> None:
        catalog_schema = json.loads(
            (ROOT / "schemas" / "nl-asset-consumer-catalog-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        release_schema = json.loads(
            (ROOT / "schemas" / "runtime-release-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(catalog_schema["properties"]["assetCount"]["maximum"], 25_000)
        self.assertEqual(catalog_schema["properties"]["assets"]["maxItems"], 25_000)
        self.assertEqual(
            catalog_schema["$defs"]["asset"]["properties"]["variants"]["maxItems"], 7
        )
        self.assertEqual(release_schema["properties"]["objects"]["maxItems"], 65_000)
        self.assertEqual(
            catalog_schema["$defs"]["variant"]["properties"]["bytes"]["maximum"],
            67_108_864,
        )
        self.assertEqual(
            release_schema["$defs"]["runtimeObject"]["properties"]["bytes"]["maximum"],
            67_108_864,
        )

        catalog = self.catalog()
        catalog["assetCount"] = 25_001
        with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
            validate_schema(catalog, catalog_schema, "oversized asset count")

        catalog = self.catalog()
        catalog["assets"][0]["variants"] *= 8
        with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
            validate_schema(catalog, catalog_schema, "oversized variant set")

        base_variant = self.catalog()["assets"][0]["variants"][0]
        variant_schema = copy.deepcopy(catalog_schema["$defs"]["variant"])
        variant_schema["$defs"] = {"sha256": catalog_schema["$defs"]["sha256"]}
        for asset_format, maximum in (
            ("svg", 2_097_152),
            ("webp", 16_777_216),
            ("png", 16_777_216),
            ("jpg", 16_777_216),
            ("jpeg", 16_777_216),
            ("gltf", 8_388_608),
            ("glb", 67_108_864),
        ):
            with self.subTest(asset_format=asset_format):
                variant = copy.deepcopy(base_variant)
                variant["format"] = asset_format
                variant["bytes"] = maximum
                validate_schema(variant, variant_schema, "bounded variant")
                variant["bytes"] = maximum + 1
                with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
                    validate_schema(variant, variant_schema, "oversized variant")

    def test_private_text_detection_covers_exporter_delimiters_and_key_headers(self) -> None:
        safe = "https://cdn.nlightlabs.com/objects/sha256/aa/public.webp"
        reject_private_strings({"url": safe}, "fixture")
        unc_path = "\\" * 2 + "server" + "\\share\\x"
        unix_path = "/" + "home/user/master"
        for value in (
            "source=" + "X:" + "\\synthetic-private-root\\private.ai",
            "source=`" + "X:" + "\\synthetic-private-root\\private.ai`",
            "path=" + unc_path,
            "path=`" + unc_path + "`",
            "origin=" + unix_path,
            "origin=`" + unix_path + "`",
            "/" + "opt/nll/runtime/source-master.ai",
            "source:" + "/" + "srv/asset-library/master.psd",
            "path:" + "/" + "tmp/private-export.zip",
            "/" + "workspace/internal/source.ai",
            "~" + "/" + "Documents/runtime-masters/source.ai",
            "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----",
            "-----BEGIN DSA " + "PRIVATE KEY-----",
            "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----",
            "ASIA" + "A" * 16,
        ):
            with self.subTest(value=value[:20]):
                with self.assertRaisesRegex(ReleaseValidationError, "prohibited"):
                    reject_private_strings({"displayName": value}, "fixture")

        with self.assertRaisesRegex(ReleaseValidationError, "prohibited"):
            load_json_bytes(b'{"source":"source:\\/srv/library/master.psd"}', "fixture")
        reject_private_strings(
            {"url": "https://cdn.nlightlabs.com/objects/sha256/aa/public.webp"},
            "fixture",
        )

    def test_labeled_provider_credentials_fail_closed_without_echo(self) -> None:
        safe_placeholders = (
            "CLOUDFLARE_API_TOKEN=<stored-secret>",
            "CF_ACCESS_CLIENT_SECRET=<stored-secret>",
            "CLOUDFLARE_ACCESS_CLIENT_SECRET=${CF_ACCESS_CLIENT_SECRET}",
            "X-Amz-Credential=<redacted>",
            "X-Amz-Security-Token=${R2_SESSION_TOKEN}",
            "X-Amz-Signature=<stored-secret>",
            "Authorization: Bearer <redacted>",
            "api_key=${RUNTIME_API_KEY}",
            "AWS_SECRET_ACCESS_KEY=<stored-secret>",
            "AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN}",
            "R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY}",
            "R2_ACCESS_KEY_ID=<redacted>",
            "GOOGLE_API_KEY=${GOOGLE_API_KEY}",
            "GOOGLE_CLIENT_SECRET=<stored-secret>",
            '"client_secret":"<redacted>"',
        )
        for value in safe_placeholders:
            with self.subTest(safe=value):
                reject_private_strings({"documentation": value}, "fixture")

        credentials = (
            "CLOUDFLARE_API_TOKEN=" + "A" * 40,
            "CF_ACCESS_CLIENT_" + "SECRET=" + "a" * 64,
            "CLOUDFLARE_ACCESS_CLIENT_" + "SECRET=" + "b" * 64,
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
            "Authorization: Bearer " + "B" * 40,
            "api_key=" + "C" * 40,
            "AWS_SECRET_" + "ACCESS_KEY=" + "D" * 40,
            "AWS_SESSION_" + "TOKEN=" + "H" * 64,
            "R2_SECRET_" + "ACCESS_KEY=" + "E" * 40,
            "R2_ACCESS_" + "KEY_ID=" + "F" * 32,
            "GOOGLE_API_" + "KEY=" + "AIza" + "G" * 35,
            "GOOGLE_CLIENT_" + "SECRET=" + "GOCSPX-" + "I" * 28,
            '"client_' + 'secret":"GOCSPX-' + "J" * 28 + '"',
        )
        for credential in credentials:
            with self.subTest(kind=credential.split("=", 1)[0].split(":", 1)[0]):
                with self.assertRaises(ReleaseValidationError) as captured:
                    reject_private_strings({"documentation": credential}, "fixture")
                self.assertNotIn(credential, str(captured.exception))

    def test_decoded_json_key_value_credentials_fail_closed_with_safe_placeholders(self) -> None:
        cases = (
            (
                b'{"cloudflare_api\\u005ftoken":"' + b"A" * 24 + b'"}\n',
                "A" * 24,
            ),
            (
                b'{"aws_secret\\u005faccess_key":"' + b"B" * 40 + b'"}\n',
                "B" * 40,
            ),
            (
                b'{"r2_access_key\\u005fid":"' + b"C" * 32 + b'"}\n',
                "C" * 32,
            ),
            (
                b'{"aws_session\\u005ftoken":"' + b"D" * 64 + b'"}\n',
                "D" * 64,
            ),
            (
                b'{"google_client\\u005fsecret":"GOCSPX-' + b"E" * 28 + b'"}\n',
                "GOCSPX-" + "E" * 28,
            ),
            (
                b'{"cf_access_client\\u005fsecret":"' + b"a1" * 32 + b'"}\n',
                "a1" * 32,
            ),
            (
                b'{"X-Amz\\u002dSignature":"' + b"f2" * 32 + b'"}\n',
                "f2" * 32,
            ),
            (b'{"AccessKey\\u0049d":"' + b"Z" * 20 + b'"}\n', "Z" * 20),
            (b'{"SecretAccessKey":"' + b"S" * 40 + b'"}\n', "S" * 40),
            (b'{"SessionToken":"' + b"T" * 64 + b'"}\n', "T" * 64),
            (
                b'{"cloudflareApi\\u0054oken":"' + b"U" * 24 + b'"}\n',
                "U" * 24,
            ),
            (b'{"api\\u005ftoken":"' + b"V" * 24 + b'"}\n', "V" * 24),
        )
        for raw, credential in cases:
            with self.subTest(label=raw.split(b'"', 2)[1]):
                with self.assertRaises(ReleaseValidationError) as captured:
                    load_json_bytes(raw, "escaped labeled credential fixture")
                self.assertNotIn(credential, str(captured.exception))

        placeholders = (
            b'{"cloudflare_api\\u005ftoken":"<stored-secret>"}\n',
            b'{"aws_secret\\u005faccess_key":"${AWS_SECRET_ACCESS_KEY}"}\n',
            b'{"google_client\\u005fsecret":"<redacted>"}\n',
            b'{"X-Amz\\u002dSignature":"${R2_SIGNATURE}"}\n',
        )
        for raw in placeholders:
            with self.subTest(placeholder=raw):
                load_json_bytes(raw, "escaped placeholder fixture")

        nested_cases = (
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
        for raw, credential in nested_cases:
            with self.subTest(nested=raw[:32]):
                with self.assertRaises(ReleaseValidationError) as captured:
                    load_json_bytes(raw, "nested labeled credential fixture")
                self.assertNotIn(credential, str(captured.exception))
        load_json_bytes(
            b'{"cloudflare_api\\u005ftoken":{"metadata":["<stored-secret>"]}}\n',
            "nested placeholder fixture",
        )

    def test_public_text_rejects_controls_and_bidirectional_spoofing(self) -> None:
        for value in ("Visible\u0000Name", "Visible\u0085Name", "Visible\u202eName"):
            with self.subTest(codepoint=hex(ord(value[7]))):
                with self.assertRaisesRegex(
                    ReleaseValidationError, "control or bidirectional-format"
                ):
                    reject_private_strings({"displayName": value}, "fixture")

                release = self.add_release(RELEASE_ONE)
                catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
                catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
                catalog["assets"][0]["displayName"] = value
                catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                    catalog["assets"][0]
                )
                self.write_json(catalog_path, catalog)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaisesRegex(
                    ReleaseValidationError, "control or bidirectional-format"
                ):
                    validate_release_directory(self.root, RELEASE_ONE)
                shutil.rmtree(self.root / release_document_path(RELEASE_ONE).parent)

    def test_pointer_operation_identity_has_a_fixed_cross_language_vector(self) -> None:
        self.assertEqual(
            pointer_operation_identity(
                "rollback",
                "runtime-v1-2026.09.01.1",
                "runtime-v1-2026.09.01.2",
                "0123456789abcdef0123456789abcdef01234567",
                b"{}\n",
            ),
            "b59ee22125fd61e6efefb57ae96e56155b25a19abe9ae38262729ce957cc9fe7",
        )

    def test_artifact_operation_identity_has_a_fixed_cross_language_vector(self) -> None:
        self.assertEqual(
            artifact_operation_identity(
                RELEASE_ONE,
                "none",
                "b" * 40,
                b"release-fixture\n",
                b"catalog-fixture\n",
            ),
            "50b553b2e9ba5d8a31cc0a2da56bdf3dfd82de35c89851123d7f5f5ba749b0d6",
        )

    def test_taxonomy_sort_uses_dotnet_ordinal_utf16_order(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["tags"] = ["\U0001f600", "\ue000"]
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

        catalog["assets"][0]["tags"] = ["\ue000", "\U0001f600"]
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(ReleaseValidationError, "ordinal UTF-16"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_catalog_text_and_taxonomy_bounds_match_the_public_contract(self) -> None:
        for label, mutate in (
            ("blank taxonomy", lambda asset: asset.update(tags=[" "])),
            (
                "too many taxonomy values",
                lambda asset: asset.update(tags=[f"tag-{index:03d}" for index in range(101)]),
            ),
            (
                "overlong provenance",
                lambda asset: asset.update(sanitizedProvenance={"sourceLabel": "x" * 201}),
            ),
        ):
            with self.subTest(label=label):
                release = self.add_release(RELEASE_ONE)
                catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
                catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
                mutate(catalog["assets"][0])
                catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                    catalog["assets"][0]
                )
                self.write_json(catalog_path, catalog)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
                    validate_release_directory(self.root, RELEASE_ONE)

        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["sanitizedProvenance"] = {"sourceLabel": "x" * 200}
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

    def test_release_requires_owning_catalog_schema(self) -> None:
        self.add_release(RELEASE_ONE)
        (self.root / "schemas" / "nl-asset-consumer-catalog-v1.schema.json").unlink()
        with self.assertRaisesRegex(ReleaseValidationError, "publication remains blocked"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_valid_release_and_exact_artifact_lane_pass(self) -> None:
        self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, self.base)
        self.git("switch", "-c", branch)
        head = self.commit("Add immutable fixture release")
        validate_pull_request(self.root, self.base, head, branch)

    def test_repository_and_artifact_lane_reject_raw_crlf_git_blobs(self) -> None:
        self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, self.base)
        release_path = release_document_path(RELEASE_ONE).as_posix()
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        self.git("switch", "-c", branch)
        self.git("add", "--all")
        for relative in (release_path, catalog_path):
            canonical = (self.root / relative).read_bytes()
            self.replace_index_blob(relative, canonical.replace(b"\n", b"\r\n"))
        self.git("commit", "-m", "Commit noncanonical raw release blobs")
        head = self.sha()

        # The eol=lf checkout filter leaves canonical-looking worktree files.
        validate_release_directory(self.root, RELEASE_ONE)
        self.assertNotEqual(
            self.git("show", f"{head}:{release_path}").stdout,
            (self.root / release_path).read_bytes(),
        )
        with self.assertRaisesRegex(ReleaseValidationError, "canonical"):
            validate_repository(self.root, head)
        with self.assertRaisesRegex(ReleaseValidationError, "canonical"):
            validate_pull_request(self.root, self.base, head, branch)

    def test_repository_and_artifact_lane_ignore_worktree_encoding_filter(self) -> None:
        attributes = self.root / ".gitattributes"
        attributes.write_text(
            attributes.read_text(encoding="utf-8")
            + "manifests/releases/** working-tree-encoding=UTF-16LE\n",
            encoding="utf-8",
        )
        reviewed_base = self.commit("Configure fixture working-tree encoding")
        self.add_release(RELEASE_ONE)
        release_path = release_document_path(RELEASE_ONE).as_posix()
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        release_bytes = (self.root / release_path).read_bytes()
        catalog_bytes = (self.root / catalog_path).read_bytes()
        operation_id = artifact_operation_identity(
            RELEASE_ONE,
            "none",
            reviewed_base,
            release_bytes,
            catalog_bytes,
        )
        branch = (
            f"publish/artifacts/{RELEASE_ONE}/from/none/{operation_id}"
        )
        for relative in (release_path, catalog_path):
            text = (self.root / relative).read_text(encoding="utf-8")
            (self.root / relative).write_bytes(text.encode("utf-16-le"))
        self.git("switch", "-c", branch)
        head = self.commit("Add release through a working-tree encoding filter")

        self.assertEqual(self.git("show", f"{head}:{release_path}").stdout, release_bytes)
        self.assertNotEqual((self.root / release_path).read_bytes(), release_bytes)
        with self.assertRaises(ReleaseValidationError):
            validate_release_directory(self.root, RELEASE_ONE)
        validate_repository(self.root, head, allow_unmerged_tip=True)
        validate_pull_request(self.root, reviewed_base, head, branch)

    def test_purpose_lane_rejects_hidden_intermediate_commit_blobs(self) -> None:
        self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, self.base)
        shutil.rmtree(self.root / release_directory_path(RELEASE_ONE))
        self.git("switch", "-c", branch)
        private_blob = self.root / "private-source.pem"
        private_blob.write_text("not a real credential\n", encoding="utf-8")
        hidden_commit = self.commit("Add forbidden intermediate blob")
        private_blob.unlink()
        self.add_release(RELEASE_ONE)
        head = self.commit("Hide blob and add release")

        self.assertEqual(
            self.git("cat-file", "-t", f"{hidden_commit}:private-source.pem").stdout.decode().strip(),
            "blob",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "sole parent"):
            validate_pull_request(self.root, self.base, head, branch)

    def test_purpose_lane_rejects_redundant_merge_commit_shape(self) -> None:
        (self.root / "README.md").write_text("# Reviewed base advanced\n", encoding="utf-8")
        reviewed_base = self.commit("Advance reviewed base")
        release = self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, reviewed_base)
        self.git("switch", "-c", branch, reviewed_base)
        self.git("add", "--all")
        tree = self.git("write-tree").stdout.decode().strip()
        redundant_merge = self.git(
            "commit-tree",
            tree,
            "-p",
            reviewed_base,
            "-p",
            self.base,
            input_bytes=b"Redundant merge-shaped purpose commit\n",
        ).stdout.decode().strip()
        self.git("update-ref", f"refs/heads/{branch}", redundant_merge)

        with self.assertRaisesRegex(ReleaseValidationError, "sole parent"):
            validate_pull_request(self.root, reviewed_base, redundant_merge, branch)

        release_merge = self.git(
            "commit-tree",
            tree,
            "-p",
            reviewed_base,
            "-p",
            redundant_merge,
            input_bytes=b"Merge redundant purpose commit\n",
        ).stdout.decode().strip()
        pointer = self.pointer(release, release_merge)
        self.annotated_tag(RELEASE_ONE, release_merge, canonical_json_bytes(pointer))
        with self.assertRaisesRegex(ReleaseValidationError, "sole parent"):
            validate_tag(self.root, RELEASE_ONE, release_merge)

    def test_release_merge_must_preserve_reviewed_purpose_artifact_bytes(self) -> None:
        release = self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, self.base)
        self.git("switch", "-c", branch, self.base)
        purpose_head = self.commit("Add reviewed release candidate")

        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["displayName"] = "Changed After Review"
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        self.git("add", "--all")
        changed_tree = self.git("write-tree").stdout.decode().strip()
        forged_merge = self.git(
            "commit-tree",
            changed_tree,
            "-p",
            self.base,
            "-p",
            purpose_head,
            input_bytes=b"Forge different release bytes during merge\n",
        ).stdout.decode().strip()
        pointer = self.pointer(release, forged_merge)
        self.annotated_tag(RELEASE_ONE, forged_merge, canonical_json_bytes(pointer))

        with self.assertRaisesRegex(ReleaseValidationError, "differ from the exact reviewed"):
            validate_tag(self.root, RELEASE_ONE, forged_merge)

    def test_artifact_lane_rejects_wrong_path_status_or_existing_release(self) -> None:
        cases = (
            ("extra path", "README.md", "extra"),
            ("root manifest", "manifests/assets.json", "{}"),
            ("workflow", ".github/workflows/unsafe.yml", "name: unsafe"),
            ("current pointer", CURRENT_POINTER_PATH.as_posix(), "{}"),
        )
        for label, path, content in cases:
            with self.subTest(label=label):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fd")
                self.add_release(RELEASE_ONE)
                branch = self.artifact_branch(RELEASE_ONE, self.base)
                self.git("switch", "-C", branch, self.base)
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                head = self.commit(label)
                with self.assertRaises(ReleaseValidationError):
                    validate_pull_request(self.root, self.base, head, branch)

    def test_nonpublisher_and_malformed_publisher_branches_cannot_change_release_paths(self) -> None:
        self.git("switch", "-c", "feature/not-a-publisher")
        self.add_release(RELEASE_ONE)
        head = self.commit("Attempt protected release write")
        for branch in ("feature/not-a-publisher", "publish/artifacts/not-valid"):
            with self.subTest(branch=branch):
                with self.assertRaises(ReleaseValidationError):
                    validate_pull_request(self.root, self.base, head, branch)

    def test_pull_request_branch_metadata_is_public_safe_and_never_echoed(self) -> None:
        credential = "ghp_" + "A" * 24
        for branch in (
            "",
            "feature/caf\u00e9",
            "feature/review-\u202etxt.exe",
            f"feature/{credential}",
            "feature/" + "C:" + "/" + "Users/private",
            "feature/" + "~" + "/" + "private",
            "feature/." + "ssh/private-key",
        ):
            with self.subTest(branch=branch.encode("unicode_escape").decode("ascii")):
                with self.assertRaisesRegex(
                    ReleaseValidationError,
                    "^Pull-request branch name is not public-safe\\.$",
                ) as captured:
                    validate_pull_request(self.root, self.base, self.base, branch)
                if branch:
                    self.assertNotIn(branch, str(captured.exception))
                self.assertNotIn(credential, str(captured.exception))

    def test_git_preflight_rejects_grafts_shallow_and_alternate_object_stores(self) -> None:
        tree = self.git("rev-parse", f"{self.base}^{{tree}}").stdout.decode().strip()
        unrelated = self.git(
            "commit-tree", tree, input_bytes=b"Unrelated candidate commit\n"
        ).stdout.decode().strip()
        common_directory = Path(
            self.git(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).stdout.decode().strip()
        )
        metadata_cases = (
            ("info/grafts", f"{unrelated} {self.base}\n"),
            ("shallow", f"{unrelated}\n"),
            ("objects/info/alternates", "candidate-object-store\n"),
        )
        for relative, content in metadata_cases:
            with self.subTest(relative=relative):
                metadata = common_directory / relative
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_text(content, encoding="ascii")
                try:
                    with self.assertRaisesRegex(
                        ReleaseValidationError,
                        "graft, shallow, and alternate object-store metadata",
                    ):
                        validate_pull_request(
                            self.root, self.base, unrelated, "feature/graph-override"
                        )
                finally:
                    metadata.unlink(missing_ok=True)

    def test_raw_commit_parents_reject_late_and_duplicate_headers(self) -> None:
        tree = self.git("rev-parse", f"{self.base}^{{tree}}").stdout.decode().strip()
        identity_headers = (
            "author Runtime Fixture <runtime-fixture@example.invalid> 1788264000 +0000\n"
            "committer Runtime Fixture <runtime-fixture@example.invalid> 1788264000 +0000\n"
        )
        malformed_objects = (
            (
                "late",
                f"tree {tree}\n{identity_headers}parent {self.base}\n\nLate parent\n",
            ),
            (
                "duplicate",
                f"tree {tree}\nparent {self.base}\nparent {self.base}\n"
                f"{identity_headers}\nDuplicate parent\n",
            ),
        )
        for label, raw in malformed_objects:
            with self.subTest(label=label):
                commit = self.git(
                    "hash-object",
                    "--literally",
                    "-t",
                    "commit",
                    "-w",
                    "--stdin",
                    input_bytes=raw.encode("ascii"),
                ).stdout.decode().strip()
                with self.assertRaisesRegex(ReleaseValidationError, "parent"):
                    validate_repository(self.root, commit)
                with self.assertRaisesRegex(ReleaseValidationError, "parent"):
                    validate_pull_request(
                        self.root, self.base, commit, f"feature/{label}-parent-header"
                    )

    def test_git_preflight_rejects_environment_object_store_override_without_echo(self) -> None:
        object_directory = str(
            Path(
                self.git("rev-parse", "--git-path", "objects").stdout.decode().strip()
            ).resolve()
        )
        with mock.patch.dict(
            os.environ, {"GIT_OBJECT_DIRECTORY": object_directory}, clear=False
        ):
            with self.assertRaisesRegex(
                ReleaseValidationError, "environment overrides"
            ) as captured:
                validate_pull_request(
                    self.root, self.base, self.base, "feature/object-store-override"
                )
        self.assertNotIn(object_directory, str(captured.exception))

    def test_git_subprocesses_sanitize_benign_inherited_config_environment(self) -> None:
        injected = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(self.root),
            "GIT_CONFIG_KEY_1": "core.autocrlf",
            "GIT_CONFIG_VALUE_1": "false",
        }
        with mock.patch.dict(os.environ, injected, clear=False):
            validate_pull_request(
                self.root, self.base, self.base, "feature/sanitized-host-config"
            )

    def test_nonpublisher_branch_cannot_change_frozen_legacy_or_discovery_manifests(self) -> None:
        cases = (
            ("manifests/assets.json", {"schemaVersion": "fixture"}),
            (
                "manifests/discovery/collections/fixture/page-001.json",
                {"schemaVersion": 1},
            ),
        )
        for path, value in cases:
            with self.subTest(path=path):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fd")
                self.git("switch", "-C", "feature/legacy-manifest-change", self.base)
                self.write_json(path, value)
                head = self.commit("Attempt frozen manifest change")
                with self.assertRaisesRegex(ReleaseValidationError, "runtime manifest"):
                    validate_pull_request(
                        self.root, self.base, head, "feature/legacy-manifest-change"
                    )

    def test_nonpublisher_branch_cannot_hide_release_changes_in_intermediate_commits(self) -> None:
        self.git("switch", "-c", "feature/hidden-release-history")
        self.add_release(RELEASE_ONE)
        hidden_commit = self.commit("Add hidden release artifacts")
        shutil.rmtree(self.root / release_document_path(RELEASE_ONE).parent)
        (self.root / "fixture-root.json").write_bytes(canonical_json_bytes({"fixture": "safe"}))
        head = self.commit("Restore final tree to ordinary content")

        self.assertEqual(
            self.git(
                "cat-file", "-t", f"{hidden_commit}:{release_document_path(RELEASE_ONE).as_posix()}"
            ).stdout.decode().strip(),
            "blob",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "reachable candidate history"):
            validate_pull_request(self.root, self.base, head, "feature/hidden-release-history")

    def test_long_lived_feature_may_merge_reviewed_main_without_owning_its_manifests(self) -> None:
        self.git("switch", "-c", "feature/long-lived", self.base)
        (self.root / "fixture-root.json").write_bytes(canonical_json_bytes({"fixture": "feature"}))
        self.commit("Add ordinary feature work")

        self.git("switch", "-C", "main", self.base)
        self.prepare_tagged_release()
        reviewed_base = self.sha()

        self.git("switch", "feature/long-lived")
        self.git("merge", "--no-ff", reviewed_base, "-m", "Merge reviewed main")
        head = self.sha()
        validate_pull_request(self.root, reviewed_base, head, "feature/long-lived")

    def test_nonpublisher_cannot_replay_then_hide_an_old_protected_tree_through_merges(self) -> None:
        self.write_json("manifests/assets.json", {"generation": "old"})
        old_commit = self.commit("Record old protected manifest")
        old_tree = self.git("rev-parse", f"{old_commit}^{{tree}}").stdout.decode().strip()

        self.write_json("manifests/assets.json", {"generation": "reviewed"})
        reviewed_base = self.commit("Advance reviewed protected manifest")
        reviewed_tree = self.git(
            "rev-parse", f"{reviewed_base}^{{tree}}"
        ).stdout.decode().strip()

        replay_merge = self.git(
            "commit-tree",
            old_tree,
            "-p",
            reviewed_base,
            "-p",
            old_commit,
            input_bytes=b"Replay an old protected tree\n",
        ).stdout.decode().strip()
        hidden_head = self.git(
            "commit-tree",
            reviewed_tree,
            "-p",
            replay_merge,
            "-p",
            reviewed_base,
            input_bytes=b"Hide the replay in final tree state\n",
        ).stdout.decode().strip()

        self.assertFalse(
            self.git("diff", "--quiet", reviewed_base, hidden_head, check=False).returncode
        )
        with self.assertRaisesRegex(ReleaseValidationError, "reachable candidate history"):
            validate_pull_request(
                self.root, reviewed_base, hidden_head, "feature/protected-tree-replay"
            )

    def test_candidate_validator_or_workflow_edits_cannot_bypass_trusted_release_lane(self) -> None:
        self.git("switch", "-c", "feature/replace-policy")
        self.add_release(RELEASE_ONE)
        for relative in (
            "tools/validate_runtime_release.py",
            ".github/workflows/validate-runtime.yml",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# candidate-controlled no-op\n", encoding="utf-8")
        head = self.commit("Try to replace release policy with candidate code")
        with self.assertRaisesRegex(ReleaseValidationError, "execution-closure"):
            validate_pull_request(self.root, self.base, head, "feature/replace-policy")

    def test_safeguard_activation_locks_authority_before_first_release(self) -> None:
        expected_wheels = {
            "ci/wheelhouse/attrs-26.1.0-py3-none-any.whl",
            "ci/wheelhouse/jsonschema-4.26.0-py3-none-any.whl",
            "ci/wheelhouse/jsonschema_specifications-2025.9.1-py3-none-any.whl",
            "ci/wheelhouse/referencing-0.37.0-py3-none-any.whl",
            "ci/wheelhouse/rfc3339_validator-0.1.4-py2.py3-none-any.whl",
            "ci/wheelhouse/rpds_py-2026.6.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            "ci/wheelhouse/six-1.17.0-py2.py3-none-any.whl",
            "ci/wheelhouse/typing_extensions-4.16.0-py3-none-any.whl",
        }
        self.assertEqual(IMMUTABLE_V1_WHEEL_PATHS, expected_wheels)

        self.assertIn("tools/verify_v1_wheelhouse.py", IMMUTABLE_V1_AUTHORITY_PATHS)

        for index, (relative, action) in enumerate(
            (
                ("requirements-ci.txt", "modify"),
                ("tools/verify_v1_wheelhouse.py", "modify"),
                ("tools/verify_v1_wheelhouse.py", "delete"),
                (next(iter(sorted(IMMUTABLE_V1_WHEEL_PATHS))), "modify"),
                ("ci/wheelhouse/unreviewed-extra.whl", "modify"),
                (".github/workflows/release-policy.yml", "modify"),
            )
        ):
            with self.subTest(relative=relative, action=action):
                self.git("switch", "-C", f"feature/pre-release-authority-{index}", self.base)
                path = self.root / relative
                if action == "delete":
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    original = path.read_bytes() if path.exists() else b""
                    path.write_bytes(original + b"candidate drift\n")
                head = self.commit("Attempt post-activation pre-release drift")
                with self.assertRaises(ReleaseValidationError):
                    validate_pull_request(
                        self.root,
                        self.base,
                        head,
                        f"feature/pre-release-authority-{index}",
                    )

    def test_execution_migration_is_available_after_activation_before_first_release(self) -> None:
        relative = "tools/validate_public_boundary.py"
        self.git("switch", "-c", "feature/pre-release-execution-migration")
        path = self.root / relative
        path.write_text(
            path.read_text(encoding="utf-8") + "# reviewed migration fixture\n",
            encoding="utf-8",
        )
        head = self.commit("Update activated V1 execution closure")
        operation_id = execution_migration_identity(self.root, self.base, head)
        validate_pull_request(
            self.root,
            self.base,
            head,
            f"infrastructure/runtime-v1-execution/{operation_id}",
        )

    def test_published_v1_schemas_are_immutable_after_the_first_release(self) -> None:
        self.prepare_tagged_release()
        reviewed_base = self.sha()
        self.git("switch", "-c", "feature/rewrite-published-v1-schema")
        schema_path = self.root / "schemas" / "runtime-release-v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["description"] = "Attempt to reinterpret published V1"
        self.write_json("schemas/runtime-release-v1.schema.json", schema)
        head = self.commit("Attempt in-place V1 schema rewrite")

        with self.assertRaisesRegex(ReleaseValidationError, "immutable in place"):
            validate_pull_request(
                self.root, reviewed_base, head, "feature/rewrite-published-v1-schema"
            )

    def test_changed_path_lane_rejects_remote_schema_before_schema_evaluation(self) -> None:
        self.git("switch", "-c", "feature/remote-schema-ref")
        self.write_json(
            "schemas/runtime-release-v1.schema.json",
            {"$ref": "https://example.invalid/candidate-controlled-schema.json"},
        )
        head = self.commit("Attempt candidate-controlled remote schema")
        with self.assertRaisesRegex(ReleaseValidationError, "immutable in place"):
            validate_pull_request(
                self.root, self.base, head, "feature/remote-schema-ref"
            )

    def test_v1_semantic_validator_freezes_after_first_release(self) -> None:
        self.prepare_tagged_release()
        reviewed_base = self.sha()
        for index, relative in enumerate(
            (
                ".gitattributes",
                "requirements-ci.txt",
                "tools/validate_runtime_release_v1.py",
            )
        ):
            with self.subTest(relative=relative):
                branch = f"feature/rewrite-v1-authority-{index}"
                self.git("switch", "-C", branch, reviewed_base)
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("candidate reinterpretation\n", encoding="utf-8")
                head = self.commit("Attempt V1 authority rewrite")
                with self.assertRaisesRegex(ReleaseValidationError, "immutable in place"):
                    validate_pull_request(self.root, reviewed_base, head, branch)

    def test_v1_execution_closure_requires_an_exact_bound_migration_lane(self) -> None:
        self.prepare_tagged_release()
        reviewed_base = self.sha()
        for index, relative in enumerate(sorted(EVOLVABLE_V1_EXECUTION_PATHS)):
            with self.subTest(relative=relative):
                self.git("switch", "-C", f"feature/execution-change-{index}", reviewed_base)
                path = self.root / relative
                original = path.read_text(encoding="utf-8")
                if relative.endswith(".yml"):
                    migrated, replacements = re.subn(
                        r"(?<=@sha256:)[a-f0-9]{64}", "e" * 64, original, count=1
                    )
                    self.assertEqual(replacements, 1)
                else:
                    migrated = original + "\n# reviewed migration fixture\n"
                path.write_text(migrated, encoding="utf-8", newline="\n")
                head = self.commit("Change V1 execution closure")
                with self.assertRaisesRegex(ReleaseValidationError, "execution-closure"):
                    validate_pull_request(
                        self.root,
                        reviewed_base,
                        head,
                        f"feature/execution-change-{index}",
                    )

                operation_id = execution_migration_identity(
                    self.root, reviewed_base, head
                )
                branch = f"infrastructure/runtime-v1-execution/{operation_id}"
                validate_pull_request(self.root, reviewed_base, head, branch)
                with self.assertRaisesRegex(ReleaseValidationError, "exact reviewed intent"):
                    validate_pull_request(
                        self.root,
                        reviewed_base,
                        head,
                        "infrastructure/runtime-v1-execution/" + "0" * 64,
                    )

    def test_execution_migration_allows_scalar_rotation_but_rejects_step_or_trust_drift(self) -> None:
        self.prepare_tagged_release()
        reviewed_base = self.sha()
        workflow = self.root / ".github" / "workflows" / "release-policy.yml"
        original = workflow.read_text(encoding="utf-8")

        self.git("switch", "-c", "feature/rotate-v1-image")
        rotated, replacements = re.subn(
            r"(?<=@sha256:)[a-f0-9]{64}", "f" * 64, original, count=1
        )
        self.assertEqual(replacements, 1)
        rotated = rotated.replace("runs-on: ubuntu-24.04", "runs-on: ubuntu-26.04", 1)
        rotated = rotated.replace("timeout-minutes: 30", "timeout-minutes: 45", 1)
        workflow.write_text(rotated, encoding="utf-8", newline="\n")
        head = self.commit("Rotate the reviewed V1 execution image")
        operation_id = execution_migration_identity(self.root, reviewed_base, head)
        validate_pull_request(
            self.root,
            reviewed_base,
            head,
            f"infrastructure/runtime-v1-execution/{operation_id}",
        )

        def reorder_bootstrap_steps(value: str) -> str:
            first_marker = "      - name: Verify immutable execution environment and same-repository head\n"
            second_marker = "      - name: Materialize exact trusted base and candidate as data\n"
            third_marker = "      - name: Verify immutable trusted wheelhouse before dependency install\n"
            first = value.index(first_marker)
            second = value.index(second_marker)
            third = value.index(third_marker)
            return value[:first] + value[second:third] + value[first:second] + value[third:]

        unsafe_mutations = (
            ("write permission", lambda value: value.replace("contents: read", "contents: write")),
            ("floating runner", lambda value: value.replace("ubuntu-24.04", "ubuntu-latest")),
            ("unpinned image", lambda value: re.sub(r"@sha256:[a-f0-9]{64}", "", value, count=1)),
            (
                "external action",
                lambda value: value.replace(
                    "    steps:\n",
                    "    steps:\n      - uses: actions/checkout@" + "a" * 40 + "\n",
                    1,
                ),
            ),
            (
                "secret context",
                lambda value: value.replace(
                    "    steps:\n",
                    "    steps:\n      - run: echo '${{ secrets.RUNTIME_TOKEN }}'\n",
                    1,
                ),
            ),
            (
                "broadened trigger",
                lambda value: value.replace("branches: [main]", "branches: ['*']", 1),
            ),
            (
                "network dependency install",
                lambda value: value.replace(
                    "--no-deps --no-index", "--no-deps --index-url https://pypi.org/simple", 1
                ),
            ),
            (
                "candidate validator execution",
                lambda value: value.replace(
                    "python -P trusted/tools/validate_runtime_release_v1.py",
                    "python -P candidate/tools/validate_runtime_release_v1.py",
                    1,
                ),
            ),
            (
                "removed wheelhouse bootstrap",
                lambda value: value.replace(
                    "      - name: Verify immutable trusted wheelhouse before dependency install\n"
                    "        run: python -P trusted/tools/verify_v1_wheelhouse.py --root trusted\n\n",
                    "",
                    1,
                ),
            ),
            ("reordered bootstrap steps", reorder_bootstrap_steps),
        )
        for index, (label, mutate) in enumerate(unsafe_mutations):
            with self.subTest(label=label):
                self.git("switch", "-C", f"feature/unsafe-v1-execution-{index}", reviewed_base)
                workflow.write_text(mutate(original), encoding="utf-8", newline="\n")
                unsafe_head = self.commit(f"Attempt unsafe execution migration: {label}")
                with self.assertRaises(ReleaseValidationError):
                    execution_migration_identity(self.root, reviewed_base, unsafe_head)

    def test_execution_migration_recovers_zero_tag_and_merged_untagged_states(self) -> None:
        dispatcher = self.root / "tools" / "validate_runtime_release.py"
        self.assertFalse(self.git("tag", "--list").stdout)

        self.git("switch", "-c", "feature/zero-tag-execution-recovery")
        dispatcher.write_text(
            dispatcher.read_text(encoding="utf-8") + "# zero-tag recovery\n",
            encoding="utf-8",
            newline="\n",
        )
        zero_tag_head = self.commit("Recover activated execution before first release")
        zero_tag_operation = execution_migration_identity(
            self.root, self.base, zero_tag_head
        )
        validate_pull_request(
            self.root,
            self.base,
            zero_tag_head,
            f"infrastructure/runtime-v1-execution/{zero_tag_operation}",
        )

        self.git("switch", "-C", "recovery/merged-untagged", self.base)
        self.merge_release(RELEASE_ONE)
        merged_untagged_base = self.sha()
        self.assertFalse(self.git("tag", "--list").stdout)
        self.git("switch", "-c", "feature/merged-untagged-execution-recovery")
        dispatcher.write_text(
            dispatcher.read_text(encoding="utf-8") + "# merged-untagged recovery\n",
            encoding="utf-8",
            newline="\n",
        )
        recovery_head = self.commit("Recover execution after untagged release merge")
        recovery_operation = execution_migration_identity(
            self.root, merged_untagged_base, recovery_head
        )
        validate_pull_request(
            self.root,
            merged_untagged_base,
            recovery_head,
            f"infrastructure/runtime-v1-execution/{recovery_operation}",
        )

    def test_v1_execution_migration_cannot_smuggle_manifest_or_authority_changes(self) -> None:
        self.prepare_tagged_release()
        reviewed_base = self.sha()
        self.git("switch", "-c", "feature/smuggle-v1-authority")
        requirements = self.root / "requirements-ci.txt"
        requirements.write_text(
            requirements.read_text(encoding="utf-8") + "# attempted migration\n",
            encoding="utf-8",
        )
        validator = self.root / "tools" / "validate_runtime_release_v1.py"
        validator.parent.mkdir(parents=True, exist_ok=True)
        validator.write_text("candidate reinterpretation\n", encoding="utf-8")
        head = self.commit("Try to smuggle V1 authority")
        with self.assertRaisesRegex(ReleaseValidationError, "established execution closure"):
            validate_pull_request(
                self.root,
                reviewed_base,
                head,
                "infrastructure/runtime-v1-execution/" + "0" * 64,
            )

    def test_catalog_hash_schema_object_and_extra_file_tamper_fail(self) -> None:
        release = self.add_release(RELEASE_ONE)
        mutations = []
        bad_hash = copy.deepcopy(release)
        bad_hash["consumerCatalog"]["sha256"] = "f" * 64
        mutations.append(("catalog SHA", bad_hash, None))
        bad_object = copy.deepcopy(release)
        bad_object["objects"][0]["url"] = "https://cdn.nlightlabs.com/objects/sha256/aa/wrong.webp"
        mutations.append(("object URL", bad_object, None))
        bad_predecessor = copy.deepcopy(release)
        bad_predecessor["predecessorReleaseId"] = "not-a-release"
        mutations.append(("predecessor", bad_predecessor, None))
        mutations.append(("extra file", release, "unexpected.json"))
        for label, value, extra in mutations:
            with self.subTest(label=label):
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), value)
                extra_path = self.root / "manifests" / "releases" / RELEASE_ONE / "unexpected.json"
                if extra:
                    extra_path.write_text("{}\n", encoding="utf-8")
                elif extra_path.exists():
                    extra_path.unlink()
                with self.assertRaises(ReleaseValidationError):
                    validate_release_directory(self.root, RELEASE_ONE)

    def test_consumer_catalog_rejects_private_fields_and_requires_exact_release_objects(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = self.catalog()
        catalog["assets"][0]["releaseId"] = RELEASE_ONE
        catalog["releaseId"] = RELEASE_ONE
        catalog["assets"][0]["sourcePath"] = (
            "X:" + "\\synthetic-private-root\\private-master.ai"
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(
            ReleaseValidationError, "prohibited Windows absolute path"
        ):
            validate_release_directory(self.root, RELEASE_ONE)

        catalog["assets"][0].pop("sourcePath")
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        release["objects"][0]["bytes"] = 13
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(ReleaseValidationError, "does not exactly match"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_consumer_catalog_rejects_github_credential_shapes(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["publicCredit"] = "ghs_" + "A" * 36
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(ReleaseValidationError, "GitHub credential"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_benign_security_ui_labels_are_not_misclassified_as_credentials(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["displayName"] = "Password and API Key Settings Icon"
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

    def test_consumer_catalog_rejects_release_drift_bad_fallback_and_unsorted_ids(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        base_catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        cases = []
        wrong_release = copy.deepcopy(base_catalog)
        wrong_release["assets"][0]["releaseId"] = RELEASE_TWO
        cases.append(("release drift", wrong_release))
        bad_fallback = copy.deepcopy(base_catalog)
        bad_fallback["assets"][0]["fallbackAssetId"] = "missing-asset"
        cases.append(("fallback", bad_fallback))
        unsorted = copy.deepcopy(base_catalog)
        second = copy.deepcopy(unsorted["assets"][0])
        second["assetId"] = "aaa-second"
        second["assetVersion"] = expected_consumer_asset_version(second)
        unsorted["assets"].append(second)
        unsorted["assetCount"] = 2
        cases.append(("sort", unsorted))
        for label, catalog in cases:
            with self.subTest(label=label):
                self.write_json(catalog_path, catalog)
                candidate = copy.deepcopy(release)
                candidate["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), candidate)
                with self.assertRaises(ReleaseValidationError):
                    validate_release_directory(self.root, RELEASE_ONE)

    def test_fallback_must_target_ready_nondeprecated_asset(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        deprecated_target = copy.deepcopy(catalog["assets"][0])
        deprecated_target["assetId"] = "target-deprecated"
        deprecated_target["deprecated"] = True
        deprecated_target["assetVersion"] = expected_consumer_asset_version(
            deprecated_target
        )
        catalog["assets"][0]["fallbackAssetId"] = deprecated_target["assetId"]
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        catalog["assets"].append(deprecated_target)
        catalog["assetCount"] = 2
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)

        with self.assertRaisesRegex(ReleaseValidationError, "READY, nondeprecated"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_maximum_fallback_chain_is_linear_and_cycle_safe(self) -> None:
        asset_ids = [f"asset-{index:05d}" for index in range(25_000)]
        fallbacks = {
            asset_id: asset_ids[index + 1] if index + 1 < len(asset_ids) else None
            for index, asset_id in enumerate(asset_ids)
        }
        _validate_fallback_graph(fallbacks)

        fallbacks[asset_ids[-1]] = asset_ids[0]
        with self.assertRaisesRegex(ReleaseValidationError, "fallback graph contains a cycle"):
            _validate_fallback_graph(fallbacks)

    def test_consumer_catalog_allows_assets_to_reuse_one_immutable_object(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        second = copy.deepcopy(catalog["assets"][0])
        second["assetId"] = "second-fixture-asset"
        second["assetVersion"] = expected_consumer_asset_version(second)
        catalog["assets"].append(second)
        catalog["assetCount"] = 2
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)

        validate_release_directory(self.root, RELEASE_ONE)

    def test_shared_object_remains_until_every_alias_is_tombstoned(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        second = copy.deepcopy(catalog["assets"][0])
        second["assetId"] = "second-fixture-asset"
        second["assetVersion"] = expected_consumer_asset_version(second)
        catalog["assets"].append(second)
        catalog["assetCount"] = 2

        first = catalog["assets"][0]
        first["readinessStatus"] = "UNAVAILABLE"
        first["deprecated"] = True
        first["variants"] = []
        first["assetVersion"] = expected_consumer_asset_version(first)
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)
        self.assertEqual(len(release["objects"]), 1)

        second["readinessStatus"] = "UNAVAILABLE"
        second["deprecated"] = True
        second["variants"] = []
        second["assetVersion"] = expected_consumer_asset_version(second)
        release["objects"] = []
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

    def test_unavailable_tombstone_preserves_id_without_runtime_object(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        asset = catalog["assets"][0]
        asset["readinessStatus"] = "UNAVAILABLE"
        asset["deprecated"] = True
        asset["variants"] = []
        asset["assetVersion"] = expected_consumer_asset_version(asset)
        self.write_json(catalog_path, catalog)
        release["objects"] = []
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

        for label, mutate in (
            ("not deprecated", lambda item: item.update(deprecated=False)),
            ("retained variant", lambda item: item.update(variants=self.catalog()["assets"][0]["variants"])),
        ):
            with self.subTest(label=label):
                invalid = copy.deepcopy(catalog)
                mutate(invalid["assets"][0])
                invalid["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                    invalid["assets"][0]
                )
                self.write_json(catalog_path, invalid)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(invalid)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaisesRegex(ReleaseValidationError, "schema validation"):
                    validate_release_directory(self.root, RELEASE_ONE)

    def test_consumer_catalog_rejects_conflicting_metadata_for_one_immutable_object(self) -> None:
        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        second = copy.deepcopy(catalog["assets"][0])
        second["assetId"] = "second-fixture-asset"
        second["variants"][0]["width"] = 2
        second["variants"][0]["height"] = 2
        second["assetVersion"] = expected_consumer_asset_version(second)
        catalog["assets"].append(second)
        catalog["assetCount"] = 2
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)

        with self.assertRaisesRegex(ReleaseValidationError, "variants disagree"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_release_object_order_and_duplicate_asset_variant_fail(self) -> None:
        release = self.add_release(RELEASE_ONE)
        second_sha = "b" * 64
        second_key = f"objects/sha256/bb/{second_sha}.webp"
        second_object = {
            "bytes": 9,
            "objectKey": second_key,
            "sha256": second_sha,
            "url": f"https://cdn.nlightlabs.com/{second_key}",
        }
        release["objects"] = [second_object, release["objects"][0]]
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(ReleaseValidationError, "sorted"):
            validate_release_directory(self.root, RELEASE_ONE)

        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        second_variant = copy.deepcopy(catalog["assets"][0]["variants"][0])
        second_variant.update(
            {
                "bytes": second_object["bytes"],
                "objectKey": second_object["objectKey"],
                "sha256": second_object["sha256"],
                "url": second_object["url"],
            }
        )
        catalog["assets"][0]["variants"].append(second_variant)
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        release["objects"].append(second_object)
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        validate_release_directory(self.root, RELEASE_ONE)

        release = self.add_release(RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        duplicate_object = copy.deepcopy(catalog["assets"][0]["variants"][0])
        duplicate_object["width"] += 1
        duplicate_object["height"] += 1
        catalog["assets"][0]["variants"].append(duplicate_object)
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(catalog["assets"][0])
        self.write_json(catalog_path, catalog)
        release["consumerCatalog"]["sha256"] = hashlib.sha256(canonical_json_bytes(catalog)).hexdigest()
        self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
        with self.assertRaisesRegex(ReleaseValidationError, "duplicate immutable variant object"):
            validate_release_directory(self.root, RELEASE_ONE)

    def test_forged_version_private_provenance_and_fallback_cycle_fail(self) -> None:
        for label in ("forged version", "private provenance", "fallback cycle"):
            with self.subTest(label=label):
                release = self.add_release(RELEASE_ONE)
                catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
                catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
                if label == "forged version":
                    catalog["assets"][0]["assetVersion"] = f"sha256:{'f' * 64}"
                elif label == "private provenance":
                    catalog["assets"][0]["sanitizedProvenance"]["sourceLabel"] = (
                        "X:" + "\\synthetic-private-root\\source-master.ai"
                    )
                    catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                        catalog["assets"][0]
                    )
                else:
                    second = copy.deepcopy(catalog["assets"][0])
                    second["assetId"] = "second-fixture-asset"
                    catalog["assets"][0]["fallbackAssetId"] = second["assetId"]
                    second["fallbackAssetId"] = catalog["assets"][0]["assetId"]
                    catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
                        catalog["assets"][0]
                    )
                    second["assetVersion"] = expected_consumer_asset_version(second)
                    catalog["assets"].append(second)
                    catalog["assetCount"] = 2
                self.write_json(catalog_path, catalog)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaises(ReleaseValidationError):
                    validate_release_directory(self.root, RELEASE_ONE)

    def test_release_timestamps_are_equal_canonical_and_match_release_date(self) -> None:
        for label, release_time, catalog_time in (
            ("offset", "2026-09-01T08:00:00-04:00", "2026-09-01T08:00:00-04:00"),
            ("different", "2026-09-01T12:00:00Z", "2026-09-01T12:00:01Z"),
            ("wrong date", "2026-08-31T12:00:00Z", "2026-08-31T12:00:00Z"),
        ):
            with self.subTest(label=label):
                release = self.add_release(RELEASE_ONE)
                catalog_path = consumer_catalog_path(RELEASE_ONE).as_posix()
                catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
                release["createdAt"] = release_time
                catalog["generatedAt"] = catalog_time
                self.write_json(catalog_path, catalog)
                release["consumerCatalog"]["sha256"] = hashlib.sha256(
                    canonical_json_bytes(catalog)
                ).hexdigest()
                self.write_json(release_document_path(RELEASE_ONE).as_posix(), release)
                with self.assertRaises(ReleaseValidationError):
                    validate_release_directory(self.root, RELEASE_ONE)

    def test_repository_graph_rejects_missing_predecessor_and_cycles(self) -> None:
        self.add_release(RELEASE_ONE, RELEASE_TWO)
        with self.assertRaisesRegex(ReleaseValidationError, "missing predecessor"):
            validate_release_graph(self.root)

        self.add_release(RELEASE_TWO, RELEASE_ONE)
        with self.assertRaisesRegex(ReleaseValidationError, "cycle"):
            validate_release_graph(self.root)

    def test_successor_release_must_retain_every_predecessor_stable_asset_id(self) -> None:
        self.add_release(RELEASE_ONE)
        successor = self.add_release(RELEASE_TWO, RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_TWO).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["assetId"] = "replacement-asset"
        catalog["assets"][0]["displayName"] = "Replacement Asset"
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        successor["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_TWO).as_posix(), successor)

        with self.assertRaisesRegex(ReleaseValidationError, "omits 1 stable asset ID"):
            validate_release_graph(self.root)

    def test_releases_must_agree_on_reused_immutable_object_evidence(self) -> None:
        self.add_release(RELEASE_ONE)
        successor = self.add_release(RELEASE_TWO, RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_TWO).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        catalog["assets"][0]["variants"][0]["width"] = 2
        catalog["assets"][0]["variants"][0]["height"] = 2
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        successor["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_TWO).as_posix(), successor)

        validate_release_directory(self.root, RELEASE_TWO)
        with self.assertRaisesRegex(ReleaseValidationError, "immutable object evidence"):
            validate_release_graph(self.root)

    def test_releases_cannot_alias_one_digest_to_multiple_runtime_identities(self) -> None:
        self.add_release(RELEASE_ONE)
        successor = self.add_release(RELEASE_TWO, RELEASE_ONE)
        catalog_path = consumer_catalog_path(RELEASE_TWO).as_posix()
        catalog = json.loads((self.root / catalog_path).read_text(encoding="utf-8"))
        variant = catalog["assets"][0]["variants"][0]
        png_key = f"objects/sha256/aa/{OBJECT_SHA}.png"
        variant["format"] = "png"
        variant["mimeType"] = "image/png"
        variant["objectKey"] = png_key
        variant["url"] = f"https://cdn.nlightlabs.com/{png_key}"
        catalog["assets"][0]["assetVersion"] = expected_consumer_asset_version(
            catalog["assets"][0]
        )
        self.write_json(catalog_path, catalog)
        successor["objects"][0]["objectKey"] = png_key
        successor["objects"][0]["url"] = f"https://cdn.nlightlabs.com/{png_key}"
        successor["consumerCatalog"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(catalog)
        ).hexdigest()
        self.write_json(release_document_path(RELEASE_TWO).as_posix(), successor)

        validate_release_directory(self.root, RELEASE_TWO)
        with self.assertRaisesRegex(ReleaseValidationError, "multiple identities"):
            validate_release_graph(self.root)

    def test_confusable_namespace_and_non_descendant_head_fail(self) -> None:
        self.git("switch", "-c", "feature/confusable")
        alias = self.root / "Manifests" / "Releases" / "lookalike.json"
        alias.parent.mkdir(parents=True)
        alias.write_text("{}\n", encoding="utf-8")
        alias_head = self.commit("Add confusable release path")
        with self.assertRaisesRegex(ReleaseValidationError, "Confusable"):
            validate_pull_request(self.root, self.base, alias_head, "feature/confusable")
        with self.assertRaisesRegex(ReleaseValidationError, "Confusable"):
            validate_repository(self.root, alias_head)

        self.git("switch", "-C", "main", self.base)
        (self.root / "fixture-root.json").write_bytes(canonical_json_bytes({"fixture": "advanced"}))
        advanced_base = self.commit("Advance reviewed base")
        self.add_release(RELEASE_ONE)
        branch = self.artifact_branch(RELEASE_ONE, self.base)
        self.git("switch", "-C", branch, self.base)
        stale_head = self.commit("Build from stale base")
        with self.assertRaisesRegex(ReleaseValidationError, "exact reviewed base"):
            validate_pull_request(self.root, advanced_base, stale_head, branch)

    def test_artifact_release_id_must_advance_past_every_base_release(self) -> None:
        release, pointer, _artifact_commit = self.prepare_tagged_release(RELEASE_TWO)
        self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
        reviewed_base = self.commit("Select later fixture release")
        self.add_release(RELEASE_ONE, release["releaseId"])
        branch = self.artifact_branch(RELEASE_ONE, reviewed_base)
        self.git("switch", "-c", branch)
        head = self.commit("Attempt backdated release")
        with self.assertRaisesRegex(ReleaseValidationError, "later than every"):
            validate_pull_request(self.root, reviewed_base, head, branch)

    def test_artifact_lane_rejects_new_release_while_newer_tip_is_unselected(self) -> None:
        first_release, first_pointer, _ = self.prepare_tagged_release()
        self.write_json(CURRENT_POINTER_PATH.as_posix(), first_pointer)
        self.commit("Select first release")

        self.add_release(RELEASE_TWO, first_release["releaseId"])
        unselected_tip = self.commit("Add second release without selecting it")

        self.add_release(RELEASE_THREE, first_release["releaseId"])
        branch = self.artifact_branch(RELEASE_THREE, unselected_tip)
        self.git("switch", "-c", branch, unselected_tip)
        head = self.commit("Attempt sibling release")

        with self.assertRaisesRegex(ReleaseValidationError, "linear"):
            validate_release_graph(self.root)
        with self.assertRaises(ReleaseValidationError):
            validate_pull_request(self.root, unselected_tip, head, branch)

        self.git("switch", "--detach", unselected_tip)
        self.add_release(RELEASE_THREE, RELEASE_TWO)
        direct_branch = self.artifact_branch(RELEASE_THREE, unselected_tip)
        self.git("switch", "-c", direct_branch)
        direct_successor = self.commit("Attempt direct successor of unselected release")
        validate_release_graph(self.root)
        with self.assertRaisesRegex(ReleaseValidationError, "reviewed current pointer"):
            validate_pull_request(self.root, unselected_tip, direct_successor, direct_branch)

    def test_annotated_tag_and_pointer_cutover_pass(self) -> None:
        release, pointer, artifact_commit = self.prepare_tagged_release()
        validate_tag(self.root, RELEASE_ONE, artifact_commit)
        branch = self.pointer_branch("select", pointer, "none")
        self.git("switch", "-c", branch)
        self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
        pointer_head = self.commit("Select immutable fixture release")
        validate_pull_request(self.root, artifact_commit, pointer_head, branch)

    def test_repository_and_pointer_lane_reject_raw_crlf_git_blob(self) -> None:
        _, pointer, artifact_commit = self.prepare_tagged_release()
        branch = self.pointer_branch("select", pointer, "none")
        pointer_path = CURRENT_POINTER_PATH.as_posix()
        self.git("switch", "-c", branch)
        self.write_json(pointer_path, pointer)
        canonical = (self.root / pointer_path).read_bytes()
        self.git("add", "--all")
        self.replace_index_blob(pointer_path, canonical.replace(b"\n", b"\r\n"))
        self.git("commit", "-m", "Commit noncanonical raw pointer blob")
        pointer_head = self.sha()

        self.assertEqual((self.root / pointer_path).read_bytes(), canonical)
        self.assertNotEqual(
            self.git("show", f"{pointer_head}:{pointer_path}").stdout,
            canonical,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "canonical"):
            validate_repository(self.root, pointer_head)
        with self.assertRaisesRegex(ReleaseValidationError, "canonical"):
            validate_pull_request(self.root, artifact_commit, pointer_head, branch)

    def test_tag_object_is_validated_before_immutable_ref_creation(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

        validate_unreferenced_tag_object(
            self.root, tag_object, RELEASE_ONE, artifact_commit
        )
        self.git("update-ref", f"refs/tags/{RELEASE_ONE}", tag_object)
        with self.assertRaisesRegex(ReleaseValidationError, "namespace to be unused"):
            validate_v1_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        validate_tag(self.root, RELEASE_ONE, artifact_commit)

        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        self.git("update-ref", f"refs/tags/{RELEASE_ONE}", artifact_commit)
        with self.assertRaisesRegex(ReleaseValidationError, "namespace to be unused"):
            validate_v1_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        invalid_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            internal_tag=RELEASE_TWO,
            create_ref=False,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "internal tag name"):
            validate_unreferenced_tag_object(
                self.root, invalid_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

    def test_tag_object_dispatcher_global_checks_before_retained_v1_delegation(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        self.git("update-ref", "refs/tags/unreviewed-maintenance-tag", artifact_commit)

        # Version-scoped authority ignores the unrelated namespace by design.
        validate_v1_unreferenced_tag_object(
            self.root, tag_object, RELEASE_ONE, artifact_commit
        )
        dispatcher_calls = (
            ("repository", lambda: validate_repository(self.root, artifact_commit)),
            ("tag", lambda: validate_tag(self.root, RELEASE_ONE, artifact_commit)),
            (
                "tag-object",
                lambda: validate_unreferenced_tag_object(
                    self.root, tag_object, RELEASE_ONE, artifact_commit
                ),
            ),
        )
        for mode, invoke in dispatcher_calls:
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(
                    ReleaseValidationError, "recognized runtime namespace"
                ):
                    invoke()
        result = subprocess.run(
            [
                sys.executable,
                "-P",
                str(ROOT / "tools" / "validate_runtime_release.py"),
                "--root",
                str(self.root),
                "--tag-object",
                tag_object,
                "--tag-name",
                RELEASE_ONE,
                "--main",
                artifact_commit,
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        self.assertNotIn("unreviewed-maintenance-tag", output)
        self.assertNotIn(str(self.root), output)

    def test_tag_object_preflight_rejects_descendant_release_tag_namespace(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        descendant_ref = f"refs/tags/{RELEASE_ONE}/evil"
        self.git("update-ref", descendant_ref, artifact_commit)

        with self.assertRaisesRegex(
            ReleaseValidationError, "recognized runtime namespace"
        ):
            validate_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )
        self.assertEqual(
            self.git("show-ref", "--verify", descendant_ref, check=False).returncode,
            0,
        )

    def test_tag_object_preflight_audits_all_existing_runtime_tag_refs(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        self.git("update-ref", "refs/tags/runtime-v1-malformed", artifact_commit)

        with self.assertRaisesRegex(ReleaseValidationError, "release tag"):
            validate_v1_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

    def test_tag_object_preflight_rejects_an_outer_tag_ref_reaching_the_candidate(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        outer_raw = (
            f"object {tag_object}\ntype tag\ntag outer-safe\n"
            "tagger Runtime Fixture <runtime-fixture@example.invalid> 1788264000 +0000\n\n"
            "Outer tag\n"
        ).encode("utf-8")
        outer_object = self.git("mktag", input_bytes=outer_raw).stdout.decode().strip()
        self.git("update-ref", "refs/tags/outer-safe", outer_object)

        with self.assertRaisesRegex(ReleaseValidationError, "no existing Git ref"):
            validate_v1_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

    def test_tag_object_preflight_requires_exact_clean_reviewed_checkout(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        tag_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        fixture_root = self.root / "fixture-root.json"
        original = fixture_root.read_bytes()
        fixture_root.write_bytes(original + b"dirty\n")
        with self.assertRaisesRegex(ReleaseValidationError, "clean index"):
            validate_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        fixture_root.write_bytes(original)
        self.assertFalse(self.git("status", "--porcelain").stdout)

        fixture_root.write_bytes(canonical_json_bytes({"fixture": "reviewed-successor"}))
        self.commit("Advance beyond reviewed release merge")
        with self.assertRaisesRegex(ReleaseValidationError, "exact reviewed main"):
            validate_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

    def test_tag_object_secret_and_duplicate_failures_never_echo_credentials(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        credentials = (
            "CLOUDFLARE_API_TOKEN=" + "A" * 40,
            "Authorization: Bearer " + "B" * 40,
            "api_key=" + "C" * 40,
        )
        for credential in credentials:
            with self.subTest(credential=credential[:12]):
                message = canonical_json_bytes({"receipt": pointer, "note": credential})
                tag_object = self.annotated_tag(
                    RELEASE_ONE, artifact_commit, message, create_ref=False
                )
                with self.assertRaises(ReleaseValidationError) as captured:
                    validate_unreferenced_tag_object(
                        self.root, tag_object, RELEASE_ONE, artifact_commit
                    )
                self.assertNotIn(credential, str(captured.exception))

        token = "ghp_" + "A" * 24
        escaped_key = "ghp_" + r"\u0041" * 24
        duplicate_message = (
            "{\"" + escaped_key + "\":1,\"" + escaped_key + "\":2}\n"
        ).encode("utf-8")
        duplicate_object = self.annotated_tag(
            RELEASE_ONE, artifact_commit, duplicate_message, create_ref=False
        )
        with self.assertRaisesRegex(ReleaseValidationError, "duplicate member") as captured:
            validate_unreferenced_tag_object(
                self.root, duplicate_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotIn(token, str(captured.exception))

        non_object = self.annotated_tag(
            RELEASE_ONE, artifact_commit, b"[]\n", create_ref=False
        )
        with self.assertRaisesRegex(ReleaseValidationError, "JSON object"):
            validate_unreferenced_tag_object(
                self.root, non_object, RELEASE_ONE, artifact_commit
            )

    def test_oversized_tag_object_is_rejected_before_message_loading(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        oversized = canonical_json_bytes(pointer) + b" " * (70 * 1024)
        tag_object = self.annotated_tag(
            RELEASE_ONE, artifact_commit, oversized, create_ref=False
        )
        with self.assertRaisesRegex(ReleaseValidationError, "65536-byte"):
            validate_unreferenced_tag_object(
                self.root, tag_object, RELEASE_ONE, artifact_commit
            )
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/tags/{RELEASE_ONE}", check=False).returncode,
            0,
        )

    def test_tag_object_validation_ignores_local_replace_refs(self) -> None:
        release, artifact_commit = self.merge_release(RELEASE_ONE)
        pointer = self.pointer(release, artifact_commit)
        valid_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            create_ref=False,
        )
        invalid_object = self.annotated_tag(
            RELEASE_ONE,
            artifact_commit,
            canonical_json_bytes(pointer),
            internal_tag=RELEASE_TWO,
            create_ref=False,
        )
        self.git("replace", invalid_object, valid_object)
        with self.assertRaisesRegex(ReleaseValidationError, "internal tag name"):
            validate_unreferenced_tag_object(
                self.root, invalid_object, RELEASE_ONE, artifact_commit
            )

    def test_duplicate_member_error_does_not_echo_a_decoded_secret_key(self) -> None:
        token = "ghp_" + "A" * 24
        escaped_key = "ghp_" + r"\u0041" * 24
        raw = ("{\"" + escaped_key + "\":1,\"" + escaped_key + "\":2}").encode()
        with self.assertRaisesRegex(ReleaseValidationError, "duplicate member") as captured:
            load_json_bytes(raw, "fixture")
        self.assertNotIn(token, str(captured.exception))

    def test_tag_requires_exact_release_merge_and_matching_internal_name(self) -> None:
        _, pointer, release_merge = self.prepare_tagged_release()
        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        (self.root / "README.md").write_text("# Advanced after release\n", encoding="utf-8")
        later_commit = self.commit("Advance main after release")
        wrong_pointer = copy.deepcopy(pointer)
        wrong_pointer["releaseArtifactCommit"] = later_commit
        self.annotated_tag(RELEASE_ONE, later_commit, canonical_json_bytes(wrong_pointer))
        with self.assertRaisesRegex(ReleaseValidationError, "exact merge|two-parent merge"):
            validate_tag(self.root, RELEASE_ONE, later_commit)

        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        self.annotated_tag(
            RELEASE_ONE,
            release_merge,
            canonical_json_bytes(pointer),
            internal_tag=RELEASE_TWO,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "internal tag name"):
            validate_tag(self.root, RELEASE_ONE, later_commit)

    def test_tag_rejects_private_or_unapproved_tagger_identity(self) -> None:
        _, pointer, release_merge = self.prepare_tagged_release()
        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        self.annotated_tag(
            RELEASE_ONE,
            release_merge,
            canonical_json_bytes(pointer),
            tagger_identity=(
                "NL Asset Runtime Publisher github_pat_" + "A" * 32
                + " <nl-asset-runtime-publisher[bot]@users.noreply.github.com>"
            ),
        )
        with self.assertRaisesRegex(ReleaseValidationError, "GitHub fine-grained credential"):
            validate_tag(self.root, RELEASE_ONE, release_merge)

        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        self.annotated_tag(
            RELEASE_ONE,
            release_merge,
            canonical_json_bytes(pointer),
            tagger_identity="Unapproved Publisher <unapproved@example.invalid>",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "exact runtime publisher"):
            validate_tag(self.root, RELEASE_ONE, release_merge)

    def test_pointer_rejects_extra_path_self_unmerged_lightweight_and_wrong_tag(self) -> None:
        release, pointer, artifact_commit = self.prepare_tagged_release()
        pointer_bytes = canonical_json_bytes(pointer)
        bad_self = copy.deepcopy(pointer)
        bad_self["releaseArtifactCommit"] = "f" * 40
        cases = []
        branch = self.pointer_branch("select", pointer, "none")
        self.git("switch", "-c", branch)
        self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
        (self.root / "extra.json").write_text("{}\n", encoding="utf-8")
        extra_head = self.commit("Pointer plus extra")
        cases.append(("extra path", lambda: validate_pull_request(
            self.root, artifact_commit, extra_head, branch
        )))
        cases.append(("unmerged/self commit", lambda: validate_pointer(
            self.root, bad_self, canonical_json_bytes(bad_self), artifact_commit, "f" * 40
        )))
        self.git("update-ref", "-d", f"refs/tags/{RELEASE_ONE}")
        self.git("tag", RELEASE_ONE, artifact_commit)
        cases.append(("lightweight tag", lambda: validate_pointer(
            self.root, pointer, pointer_bytes, artifact_commit, None
        )))
        for label, action in cases:
            with self.subTest(label=label):
                with self.assertRaises(ReleaseValidationError):
                    action()

    def test_pointer_rejects_catalog_tamper_and_extra_fields(self) -> None:
        _, pointer, artifact_commit = self.prepare_tagged_release()
        for label, mutate in (
            ("catalog hash", lambda item: item.update(catalogSha256="f" * 64)),
            ("catalog path", lambda item: item.update(catalogPath="manifests/releases/current.json")),
            ("extra field", lambda item: item.update(mutableBranch="main")),
        ):
            with self.subTest(label=label):
                candidate = copy.deepcopy(pointer)
                mutate(candidate)
                with self.assertRaises(ReleaseValidationError):
                    validate_pointer(
                        self.root, candidate, canonical_json_bytes(candidate), artifact_commit, None
                    )

    def test_pointer_branch_rejects_identity_source_and_graph_direction_drift(self) -> None:
        _, first_pointer, _first_commit = self.prepare_tagged_release()
        self.write_json(CURRENT_POINTER_PATH.as_posix(), first_pointer)
        self.commit("Select first release")
        second_release, second_commit = self.merge_release(RELEASE_TWO, RELEASE_ONE)
        second_pointer = self.pointer(second_release, second_commit)
        self.annotated_tag(RELEASE_TWO, second_commit, canonical_json_bytes(second_pointer))
        self.write_json(CURRENT_POINTER_PATH.as_posix(), second_pointer)
        reviewed_base = self.commit("Select second release")

        correct = self.pointer_branch("rollback", first_pointer, RELEASE_TWO)
        self.git("switch", "-c", correct)
        self.write_json(CURRENT_POINTER_PATH.as_posix(), first_pointer)
        head = self.commit("Prepare rollback pointer")
        wrong_identity = correct[:-1] + ("0" if correct[-1] != "0" else "1")
        cases = (
            ("operation identity", wrong_identity),
            ("source", self.pointer_branch("rollback", first_pointer, "none")),
            ("select direction", self.pointer_branch("select", first_pointer, RELEASE_TWO)),
            ("restore direction", self.pointer_branch("restore", first_pointer, RELEASE_TWO)),
        )
        for label, branch in cases:
            with self.subTest(label=label):
                with self.assertRaises(ReleaseValidationError):
                    validate_pull_request(self.root, reviewed_base, head, branch)

    def test_rollback_and_forward_restore_use_pointer_only_branches(self) -> None:
        first_release, first_pointer, first_commit = self.prepare_tagged_release()
        self.write_json(CURRENT_POINTER_PATH.as_posix(), first_pointer)
        first_pointer_commit = self.commit("Select first release")

        second_release, second_commit = self.merge_release(RELEASE_TWO, RELEASE_ONE)
        second_pointer = self.pointer(second_release, second_commit)
        self.annotated_tag(RELEASE_TWO, second_commit, canonical_json_bytes(second_pointer))
        self.write_json(CURRENT_POINTER_PATH.as_posix(), second_pointer)
        second_pointer_commit = self.commit("Select second release")

        active_base = second_pointer_commit
        branches: list[str] = []
        for operation, pointer, source in (
            ("rollback", first_pointer, RELEASE_TWO),
            ("restore", second_pointer, RELEASE_ONE),
            ("rollback", first_pointer, RELEASE_TWO),
        ):
            branch = self.pointer_branch(operation, pointer, source, active_base)
            branches.append(branch)
            with self.subTest(branch=branch):
                self.git("switch", "-C", branch, active_base)
                self.write_json(CURRENT_POINTER_PATH.as_posix(), pointer)
                head = self.commit(branch)
                validate_pull_request(self.root, active_base, head, branch)
                active_base = head
        self.assertNotEqual(branches[0], branches[2])
        self.assertEqual(first_release["releaseId"], RELEASE_ONE)
        self.assertTrue(first_pointer_commit)

    def test_duplicate_json_members_and_noncanonical_pointer_fail(self) -> None:
        _, pointer, artifact_commit = self.prepare_tagged_release()
        noncanonical = json.dumps(pointer).encode("utf-8")
        with self.assertRaisesRegex(ReleaseValidationError, "canonical"):
            validate_pointer(self.root, pointer, noncanonical, artifact_commit, None)


if __name__ == "__main__":
    unittest.main()
