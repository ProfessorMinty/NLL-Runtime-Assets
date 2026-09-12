#!/usr/bin/env python3
"""Fail closed on files that do not belong in the public runtime repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote_to_bytes


ROOT = Path(__file__).resolve().parents[1]
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_COMMIT_MESSAGE_BYTES = 64 * 1024
MAX_COMMIT_OBJECT_BYTES = 128 * 1024
PROHIBITED_GIT_ENVIRONMENT = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)
REJECTED_GIT_ENVIRONMENT = PROHIBITED_GIT_ENVIRONMENT - {
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_SYSTEM",
}

ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "AI-CONSUMER.md",
    "CONTRIBUTING.md",
    "README.md",
    "RIGHTS.md",
    "requirements-ci.txt",
}
ROOT_MANIFESTS = {
    "manifests/assets.json",
    "manifests/collections.json",
    "manifests/index.json",
    "manifests/themes.json",
}
WORKFLOW_FILES = frozenset(
    {
        ".github/workflows/release-policy.yml",
        ".github/workflows/validate-runtime.yml",
    }
)
WORKFLOW_EVENTS = {
    ".github/workflows/release-policy.yml": frozenset({"pull_request_target"}),
    ".github/workflows/validate-runtime.yml": frozenset(
        {"pull_request", "push", "schedule"}
    ),
}
WORKFLOW_TRIGGER_BLOCKS = {
    ".github/workflows/release-policy.yml": (
        "  pull_request_target:",
        "    branches: [main]",
        "    types: [opened, reopened, synchronize, ready_for_review]",
        "",
    ),
    ".github/workflows/validate-runtime.yml": (
        "  push:",
        "    branches: [main]",
        "    tags:",
        "      - 'runtime-v1-*'",
        "      - 'runtime-v1-*/**'",
        "  pull_request:",
        "    branches: [main]",
        "  schedule:",
        "    - cron: '17 * * * *'",
        "",
    ),
}
WORKFLOW_STEP_HASHES = {
    ".github/workflows/release-policy.yml": (
        ("Verify immutable execution environment and same-repository head", "9cf35220e7f356b3faefb4f45492760888752f68e0d6d4c0ac263d9c4e0c8f3c"),
        ("Materialize exact trusted base and candidate as data", "595a8c266910539967285038749cf2cedaa6ad6e61b0afbd0877d7bcb330565c"),
        ("Enforce tracked public repository boundary from trusted base", "82ce20bb9fea19520f69c3245f5e43faa50e2ffa6b105e63b7ad5c2f1ecdef62"),
        ("Verify immutable trusted wheelhouse before dependency install", "0139a84763984827cbd3e446dfef92704b7b768482fd47c8d8190e1629ce0138"),
        ("Install trusted validation dependency", "26a9f7517083b31b2a1171fb8e6da42a6015b214744945e4817c8484ac7f919a"),
        ("Enforce changed-path lane from trusted base", "6c751522fd633c577613a1b1841ead5c1ce33bbe87460c49717e535b33b956a6"),
        ("Enforce reviewed repository state from trusted base", "9419fb53183f15ee1df031de036045f0aa5ca8b56bcfdd3bf912e32d7d1ad32a"),
    ),
    ".github/workflows/validate-runtime.yml": (
        ("Verify immutable execution environment", "056746c36160b4f82e3897e3d95e4d9d26d420ec5fb7f7ac220be81993e6b21b"),
        ("Materialize exact repository revision", "d98f044847a054d546a4de346bbf672ea22449a466480df9e698dbc10327dc29"),
        ("Verify immutable wheelhouse before dependency install", "5145b5382035e9966748554eefab99fbfec190ca514527f1be0e9665be197892"),
        ("Install validation dependency", "d3bee1a8dde83b82e2df328dcfc22a6dd1bce1f169a0a6b0b01fed82716b1873"),
        ("Validate reviewed release repository state", "a1f806bd66b6d18d27aa3d2d27aa5456e39e6dddb9f767d1146a2cb74b6fc57d"),
        ("Validate reviewed release pull-request lane", "2d1c3eb5cc7b7c7b395a081572409ec1d236ef4ff3db6487fa16e31d30d36684"),
        ("Validate annotated runtime release tag", "1fbf79d9211e8455738ce173c3a73c80ec1d9ac02e4ee930cf03058eaeb91083"),
        ("Validate tracked public repository boundary", "88f5ed0b424fa12b11e2be73e0c347855a527e24ed35ac93f4da45afd934ec2b"),
        ("Validate immutable identity contracts", "18d64deae8e48ce62f2c15df1ac5530fef5a9ba4c41443e774e734a67122ae2f"),
        ("Validate public runtime semantics", "314c2c6c7394e35492e14b3a29b4339df2e700e1cfd68143f6525b23cb14923d"),
        ("Require deterministic discovery output", "b0c026040e2bb09d3d9e6c8ea058f501d1d3dbbe09a1f6ed668d65cf85163c21"),
        ("Validate discovery consistency", "072ae5d377db8f71797398d4f81bec04478983482149ed858a9b67656b54ff2d"),
        ("Run contract regression tests", "a18cff533b78a136164360e0efc498600acc7c630b1536c1a69794c34bd9334f"),
    ),
}
V1_EXECUTION_IMAGE = (
    "python:3.12.11-bookworm@"
    "sha256:13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12"
)
MAX_JSON_DEPTH = 64
V1_WHEELHOUSE = {
    "ci/wheelhouse/attrs-26.1.0-py3-none-any.whl": (
        67548,
        "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
    ),
    "ci/wheelhouse/jsonschema-4.26.0-py3-none-any.whl": (
        90630,
        "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
    ),
    "ci/wheelhouse/jsonschema_specifications-2025.9.1-py3-none-any.whl": (
        18437,
        "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
    ),
    "ci/wheelhouse/referencing-0.37.0-py3-none-any.whl": (
        26766,
        "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
    ),
    "ci/wheelhouse/rfc3339_validator-0.1.4-py2.py3-none-any.whl": (
        3490,
        "24f6ec1eda14ef823da9e36ec7113124b39c04d50a4d3d3a3c2859577e7791fa",
    ),
    "ci/wheelhouse/rpds_py-2026.6.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": (
        366189,
        "ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6",
    ),
    "ci/wheelhouse/six-1.17.0-py2.py3-none-any.whl": (
        11050,
        "4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274",
    ),
    "ci/wheelhouse/typing_extensions-4.16.0-py3-none-any.whl": (
        45571,
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    ),
}
REQUIRED_V1_AUTHORITY_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/release-policy.yml",
        ".github/workflows/validate-runtime.yml",
        "requirements-ci.txt",
        "schemas/nl-asset-consumer-catalog-v1.schema.json",
        "schemas/runtime-current-pointer-v1.schema.json",
        "schemas/runtime-release-v1.schema.json",
        "tools/validate_public_boundary.py",
        "tools/validate_runtime_release.py",
        "tools/validate_runtime_release_v1.py",
        "tools/verify_v1_wheelhouse.py",
        *V1_WHEELHOUSE,
    }
)
EVOLVABLE_V1_EXECUTION_PATHS = frozenset(
    {
        ".github/workflows/release-policy.yml",
        ".github/workflows/validate-runtime.yml",
        "tools/validate_public_boundary.py",
        "tools/validate_runtime_release.py",
    }
)
EXECUTION_MIGRATION_BRANCH_RE = re.compile(
    r"^infrastructure/runtime-v1-execution/(?P<operation_id>[a-f0-9]{64})$"
)
RELEASE_ID_PATH = r"runtime-v1-[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*"
DISCOVERY_ID_PATH = r"[a-z0-9]+(?:-[a-z0-9]+)*"
GIT_LFS_POINTER_RE = re.compile(
    br"\Aversion https://git-lfs\.github\.com/spec/v1\r?\n"
)
PROHIBITED_SUFFIXES = {
    ".7z", ".ai", ".bak", ".bin", ".db", ".env", ".eps", ".key", ".p12", ".pem",
    ".pfx", ".psd", ".rar", ".sqlite", ".sqlite3", ".tar", ".tif", ".tiff", ".zip",
}
SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:cloudflare_api_token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~-]{20,}"
    ),
    re.compile(
        r"(?i)\b(?:aws|r2)[_-]?secret[_-]?access[_-]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+]{40}"
    ),
    re.compile(
        r"(?i)\b(?:aws|r2)[_-]?access[_-]?key[_-]?id[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9]{16,64}"
    ),
    re.compile(
        r"(?i)\baws[_-]?session[_-]?token[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40,}"
    ),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(
        r"(?i)\b(?:google[_-]?)?client[_-]?secret[\"']?\s*[:=]\s*[\"']?GOCSPX-[A-Za-z0-9_-]{16,}"
    ),
    re.compile(
        r"(?i)\b(?:cf|cloudflare)[_-]?access[_-]?client[_-]?secret[\"']?\s*[:=]\s*[\"']?[a-f0-9]{32,128}"
    ),
    re.compile(
        r"(?i)\bx-amz-credential[\"']?\s*(?:=|%3d|:)\s*[\"']?"
        r"[a-z0-9]{16,64}(?:\x2f|%2f)"
    ),
    re.compile(
        r"(?i)\bx-amz-security-token[\"']?\s*(?:=|%3d|:)\s*[\"']?"
        r"[a-z0-9._~+/%=-]{20,}(?=$|[&\s\"'])"
    ),
    re.compile(
        r"(?i)\bx-amz-signature[\"']?\s*(?:=|%3d|:)\s*[\"']?"
        r"[a-f0-9]{64}(?=$|[&\s\"'])"
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
)

_SIGV4_QUERY_NAMES = frozenset(
    {"x-amz-credential", "x-amz-security-token", "x-amz-signature"}
)
_ENCODED_QUERY_PAIR_RE = re.compile(
    r"(?i)(?:^|[?&;\s])"
    r"(?P<name>(?:[a-z0-9_-]|%[a-f0-9]{2}){1,128}?)"
    r"(?:=|%3d)"
    r"(?P<value>[^&\s\"'<>]{1,4096})"
)


def _contains_encoded_sigv4_credential(text: str) -> bool:
    for match in _ENCODED_QUERY_PAIR_RE.finditer(text):
        try:
            name = unquote_to_bytes(match.group("name")).decode("ascii").casefold()
            value = unquote_to_bytes(match.group("value")).decode("ascii")
        except UnicodeDecodeError:
            continue
        if name not in _SIGV4_QUERY_NAMES:
            continue
        if name == "x-amz-credential" and re.match(
            r"(?i)^[a-z0-9]{16,64}/", value
        ):
            return True
        if name == "x-amz-security-token" and re.fullmatch(
            r"[A-Za-z0-9._~+/%=-]{20,}", value
        ):
            return True
        if name == "x-amz-signature" and re.fullmatch(r"(?i)[a-f0-9]{64}", value):
            return True
    return False


def _is_labeled_credential(label: str, value: str) -> bool:
    decoded_label = label
    if len(label) <= 512 and re.fullmatch(
        r"(?:[A-Za-z0-9_.-]|%[A-Fa-f0-9]{2})+", label
    ):
        try:
            decoded_label = unquote_to_bytes(label).decode("ascii", errors="strict")
        except UnicodeDecodeError:
            decoded_label = label
    normalized = re.sub(r"[^a-z0-9]", "", decoded_label.casefold())
    if normalized in {"cloudflareapitoken", "apitoken", "apikey", "googleapikey"}:
        return re.fullmatch(r"[A-Za-z0-9._~-]{20,}", value) is not None
    if normalized in {"awsaccesskeyid", "r2accesskeyid", "accesskeyid"}:
        return re.fullmatch(r"[A-Za-z0-9]{16,64}", value) is not None
    if normalized in {"awssecretaccesskey", "r2secretaccesskey", "secretaccesskey"}:
        return re.fullmatch(r"[A-Za-z0-9/+]{40,}", value) is not None
    if normalized in {"awssessiontoken", "sessiontoken"}:
        return re.fullmatch(r"[A-Za-z0-9._~+/%=-]{40,}", value) is not None
    if normalized in {"googleclientsecret", "clientsecret"}:
        return re.fullmatch(r"GOCSPX-[A-Za-z0-9_-]{16,}", value) is not None
    if normalized in {"cfaccessclientsecret", "cloudflareaccessclientsecret"}:
        return re.fullmatch(r"(?i)[a-f0-9]{64,128}", value) is not None
    if normalized == "xamzcredential":
        return re.match(r"(?i)^[a-z0-9]{16,64}/", value) is not None
    if normalized == "xamzsecuritytoken":
        return re.fullmatch(r"[A-Za-z0-9._~+/%=-]{20,}", value) is not None
    if normalized == "xamzsignature":
        return re.fullmatch(r"(?i)[a-f0-9]{64}", value) is not None
    return False
PRIVATE_TEXT_PATTERNS = (
    re.compile(r"(?i)(?:^|[\s\"'`()=:\[])(?:[a-z]:[\\/])"),
    re.compile(r"(?:^|[\s\"'`()=\[])(?:\\\\|//)[^\\/\s]+[\\/][^\\/\s]+"),
    re.compile(r"(?i)\bfile:(?://|\\\\)"),
    re.compile(r"(?:^|[\s\"'`()=:\[\{,;])\x2f(?!\x2f)[^\s\"'`()\]\},;]+"),
    re.compile(r"(?:^|[\s\"'`()=:\[\{,;])~[\\/][^\s\"'`()\]\},;]+"),
    re.compile(
        r"(?i)(?:^|[\\/])(?:\.ssh|\.aws|\.azure|appdata|secrets?|vault|credentials?|private[-_ ]?keys?)(?:[\\/]|$)"
    ),
)


class PublicBoundaryError(RuntimeError):
    """A tracked public-repository boundary violation."""


def _has_prohibited_text_codepoint(text: str, allow_layout_controls: bool) -> bool:
    allowed = {0x09, 0x0A, 0x0D} if allow_layout_controls else set()
    return any(
        (
            (ord(character) < 0x20 and ord(character) not in allowed)
            or 0x7F <= ord(character) <= 0x9F
            or ord(character) in {0x061C, 0x200E, 0x200F}
            or 0x202A <= ord(character) <= 0x202E
            or 0x2066 <= ord(character) <= 0x2069
            or 0xD800 <= ord(character) <= 0xDFFF
        )
        for character in text
    )


def _reject_duplicate_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PublicBoundaryError("Tracked public JSON contains a duplicate member name.")
        result[key] = value
    return result


def _reject_non_json_constant(_value: str) -> None:
    raise PublicBoundaryError("Tracked public JSON contains a non-JSON numeric constant.")


def _require_bounded_json_text_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise PublicBoundaryError(
                    "Tracked public JSON exceeds the maximum reviewed nesting depth."
                )
        elif character in "]}":
            depth -= 1


def _walk_json_strings(value: Any) -> list[str]:
    found: list[str] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            found.append(current)
        elif isinstance(current, dict):
            for key, child in reversed(list(current.items())):
                found.append(key)
                pending.append(child)
        elif isinstance(current, list):
            pending.extend(reversed(current))
    return found


def _walk_json_labeled_descendants(
    value: Any, ancestor_keys: tuple[str, ...] = ()
):
    pending: list[tuple[Any, tuple[str, ...]]] = [(value, ancestor_keys)]
    while pending:
        current, current_keys = pending.pop()
        if isinstance(current, str):
            for key in current_keys:
                yield key, current
        elif isinstance(current, dict):
            for key, child in reversed(list(current.items())):
                pending.append((child, (*current_keys, key)))
        elif isinstance(current, list):
            for child in reversed(current):
                pending.append((child, current_keys))


def _validate_decoded_public_json(text: str, path: str) -> None:
    _require_bounded_json_text_depth(text)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_members,
            parse_constant=_reject_non_json_constant,
        )
    except (json.JSONDecodeError, PublicBoundaryError) as exc:
        raise PublicBoundaryError(f"Tracked public JSON is not strict JSON: '{path}'.") from exc
    for item in _walk_json_strings(value):
        if _has_prohibited_text_codepoint(item, allow_layout_controls=False):
            raise PublicBoundaryError(
                f"Tracked public JSON contains prohibited control text: '{path}'."
            )
        if any(pattern.search(item) for pattern in (*SECRET_PATTERNS, *PRIVATE_TEXT_PATTERNS)):
            raise PublicBoundaryError(
                f"Tracked public JSON contains decoded private or credential-shaped content: '{path}'."
            )
        if _contains_encoded_sigv4_credential(item):
            raise PublicBoundaryError(
                f"Tracked public JSON contains a decoded encoded SigV4 credential: '{path}'."
            )
    decoded_relationships = json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    )
    if any(pattern.search(decoded_relationships) for pattern in SECRET_PATTERNS):
        raise PublicBoundaryError(
            f"Tracked public JSON contains a decoded labeled credential: '{path}'."
        )
    for key, descendant in _walk_json_labeled_descendants(value):
        if _is_labeled_credential(key, descendant):
            raise PublicBoundaryError(
                f"Tracked public JSON contains a decoded descendant credential relationship: '{path}'."
            )
        relationship = (
            json.dumps(key, ensure_ascii=False)
            + ":"
            + json.dumps(descendant, ensure_ascii=False)
        )
        if any(pattern.search(relationship) for pattern in SECRET_PATTERNS) or (
            _contains_encoded_sigv4_credential(relationship)
        ):
            raise PublicBoundaryError(
                f"Tracked public JSON contains a decoded descendant credential relationship: '{path}'."
            )


def _run_git(root: Path, *arguments: str) -> bytes:
    clean_environment = {
        name: value
        for name, value in os.environ.items()
        if name not in PROHIBITED_GIT_ENVIRONMENT
        and not name.startswith("GIT_CONFIG_KEY_")
        and not name.startswith("GIT_CONFIG_VALUE_")
    }
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            *arguments,
        ],
        capture_output=True,
        check=False,
        env=clean_environment,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise PublicBoundaryError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _require_unmodified_git_graph(root: Path) -> None:
    if any(os.environ.get(name) for name in REJECTED_GIT_ENVIRONMENT):
        raise PublicBoundaryError(
            "Public validation refuses Git environment or object-store overrides."
        )
    for relative, label in (
        ("info/grafts", "legacy grafts"),
        ("shallow", "shallow history"),
        ("objects/info/alternates", "alternate object stores"),
        ("objects/info/http-alternates", "alternate object stores"),
    ):
        raw_path = _run_git(root, "rev-parse", "--path-format=absolute", "--git-path", relative)
        try:
            path = Path(raw_path.decode("utf-8", errors="strict").strip())
        except UnicodeDecodeError as exc:
            raise PublicBoundaryError("Git returned an unreadable repository control path.") from exc
        try:
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise PublicBoundaryError("Git repository control state is not a normal file.")
            if path.is_file() and path.stat().st_size:
                raise PublicBoundaryError(f"Public validation refuses {label}.")
        except OSError as exc:
            raise PublicBoundaryError("Git repository control state is unreadable.") from exc
    if _run_git(root, "for-each-ref", "--format=%(refname)", "refs/replace").strip():
        raise PublicBoundaryError("Public validation refuses replacement-object refs.")


def _normalized_path(value: str) -> str:
    if any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise PublicBoundaryError("Tracked public path contains prohibited control text.")
    if any(
        pattern.search(value)
        for pattern in (*SECRET_PATTERNS, *PRIVATE_TEXT_PATTERNS)
    ):
        raise PublicBoundaryError(
            "Tracked public path contains private or credential-shaped content."
        )
    if not value or not value.isascii() or "\\" in value or value.startswith("/"):
        raise PublicBoundaryError("Tracked public path is non-ASCII or unsafe.")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in ("", ".", "..") for part in path.parts):
        raise PublicBoundaryError("Tracked public path is not normalized.")
    return value


_WINDOWS_RESERVED_COMPONENT_RE = re.compile(
    r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$"
)
_WINDOWS_INVALID_COMPONENT_CHARACTERS = frozenset('<>:"\\|?*')


def _require_windows_portable_path(value: str) -> None:
    for component in PurePosixPath(value).parts:
        if (
            len(component) > 255
            or
            component.endswith((".", " "))
            or _WINDOWS_RESERVED_COMPONENT_RE.fullmatch(component)
            or any(character in _WINDOWS_INVALID_COMPONENT_CHARACTERS for character in component)
        ):
            raise PublicBoundaryError(
                "Tracked public path is not portable to the required Windows recovery environment."
            )


def _allowed_path(path: str) -> bool:
    if path in ROOT_FILES or path == "assets/.gitkeep" or path in V1_WHEELHOUSE:
        return True
    if path in WORKFLOW_FILES:
        return True
    if re.fullmatch(r"docs/[A-Za-z0-9._/-]+\.md", path):
        return True
    if path in ROOT_MANIFESTS or path == "manifests/discovery/index.json":
        return True
    if re.fullmatch(
        rf"manifests/discovery/collections/{DISCOVERY_ID_PATH}/page-[0-9]{{3,6}}\.json",
        path,
    ):
        return True
    if re.fullmatch(rf"manifests/discovery/themes/{DISCOVERY_ID_PATH}\.json", path):
        return True
    if path == "manifests/releases/current.json":
        return True
    if re.fullmatch(
        rf"manifests/releases/{RELEASE_ID_PATH}/(?:release|consumer-catalog)\.json",
        path,
    ):
        return True
    if re.fullmatch(r"schemas/[a-z0-9][a-z0-9-]*\.schema\.json", path):
        return True
    if re.fullmatch(r"tools/[a-z0-9_]+\.py", path):
        return True
    if re.fullmatch(r"tests/[a-z0-9_]+\.py", path):
        return True
    if re.fullmatch(r"tests/fixtures/[A-Za-z0-9._/-]+\.json", path):
        return True
    return False


def _top_level_mapping_block(text: str, key: str, path: str) -> list[str]:
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line == f"{key}:"]
    if len(starts) != 1:
        raise PublicBoundaryError(
            f"Tracked workflow must contain exactly one explicit top-level {key} mapping: '{path}'."
        )
    block: list[str] = []
    for line in lines[starts[0] + 1:]:
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            break
        block.append(line)
    return block


def _direct_mapping_keys(lines: list[str], label: str, path: str) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        if indentation != 2:
            continue
        match = re.fullmatch(r"  ([a-z][a-z0-9_-]*):(?:\s+.*)?", line)
        if match is None or match.group(1) in keys:
            raise PublicBoundaryError(
                f"Tracked workflow has an ambiguous or duplicate {label} entry: '{path}'."
            )
        keys.add(match.group(1))
    return keys


def _validate_workflow(
    text: str, path: str, allow_reviewed_environment_migration: bool = False
) -> None:
    if re.search(r"(?i)\bsecrets\b|github\s*(?:\.\s*token|\[\s*[\"']token[\"']\s*\])", text):
        raise PublicBoundaryError(
            f"Tracked public validation workflow may not consume repository secrets or a provider token: '{path}'."
        )
    if "#" in text:
        raise PublicBoundaryError(
            f"Tracked workflow may not use ambiguous comments or hash text: '{path}'."
        )
    code_lines = text.splitlines()
    code_text = "\n".join(code_lines)
    if re.search(r"(?m)^[ \t]*[\"'][^\"']+[\"'][ \t]*:", code_text):
        raise PublicBoundaryError(
            f"Tracked workflow may not use quoted mapping keys: '{path}'."
        )
    if re.search(r"(?:^|\s)&[A-Za-z0-9_-]+|(?:^|\s)\*[A-Za-z0-9_-]+", code_text):
        raise PublicBoundaryError(
            f"Tracked workflow may not use YAML anchors or aliases: '{path}'."
        )
    if re.search(r"(?:^|\s)(?:!!|!<)", code_text):
        raise PublicBoundaryError(
            f"Tracked workflow may not use explicit YAML tags: '{path}'."
        )
    top_level: set[str] = set()
    for line in code_lines:
        if not line.strip() or line[0].isspace():
            continue
        match = re.fullmatch(r"([a-z][a-z0-9_-]*):(?:\s+.*)?", line)
        if match is None or match.group(1) in top_level:
            raise PublicBoundaryError(
                f"Tracked workflow has an ambiguous or duplicate top-level entry: '{path}'."
            )
        top_level.add(match.group(1))
    if top_level != {"name", "on", "permissions", "jobs"}:
        raise PublicBoundaryError(
            f"Tracked workflow top-level shape differs from its reviewed contract: '{path}'."
        )

    expected_events = WORKFLOW_EVENTS[path]
    events = _direct_mapping_keys(
        _top_level_mapping_block(text, "on", path), "event", path
    )
    if events != expected_events:
        raise PublicBoundaryError(
            f"Tracked workflow event set differs from its exact reviewed contract: '{path}'."
        )
    if tuple(_top_level_mapping_block(text, "on", path)) != WORKFLOW_TRIGGER_BLOCKS[path]:
        raise PublicBoundaryError(
            f"Tracked workflow trigger details differ from their exact reviewed contract: '{path}'."
        )

    permission_lines = _top_level_mapping_block(text, "permissions", path)
    permissions = _direct_mapping_keys(permission_lines, "permission", path)
    permission_text = "\n".join(permission_lines)
    if permissions != {"contents"} or not re.search(
        r"(?m)^  contents:\s+read\s*$", permission_text
    ):
        raise PublicBoundaryError(
            f"Tracked workflow must retain exact read-only top-level permissions: '{path}'."
        )

    if len(re.findall(r"(?m)^permissions:[ \t]*$", code_text)) != 1 or re.search(
        r"(?m)^[ \t]+permissions[ \t]*:", code_text
    ):
        raise PublicBoundaryError(
            f"Tracked workflow may not override permissions below the reviewed top level: '{path}'."
        )
    if re.search(r"(?i)(?:^|[\s{,])permissions\s*:\s*write-all(?:$|[\s},])", code_text):
        raise PublicBoundaryError(
            f"Tracked workflow requests write-all permission: '{path}'."
        )
    if re.search(
        r"(?i)(?:^|[\s{,])[\"']?(?:actions|attestations|checks|contents|deployments|"
        r"discussions|id-token|issues|models|packages|pages|pull-requests|security-events|"
        r"statuses)[\"']?\s*:\s*[\"']?write[\"']?(?:$|[\s},])",
        code_text,
    ):
        raise PublicBoundaryError(
            f"Tracked workflow requests a write permission: '{path}'."
        )
    if re.search(r"(?m)^[ \t]*(?:uses|[\"']uses[\"'])[ \t]*:", code_text):
        raise PublicBoundaryError(
            f"Tracked validation workflow may not execute an external or local action: '{path}'."
        )
    jobs = _direct_mapping_keys(
        _top_level_mapping_block(text, "jobs", path), "job", path
    )
    expected_jobs = {
        ".github/workflows/release-policy.yml": {"release-policy"},
        ".github/workflows/validate-runtime.yml": {"validate"},
    }[path]
    if jobs != expected_jobs:
        raise PublicBoundaryError(
            f"Tracked workflow job set differs from its reviewed contract: '{path}'."
        )
    job_keys: set[str] = set()
    for line in _top_level_mapping_block(text, "jobs", path):
        if not line.strip() or line.startswith("  ") and not line.startswith("    "):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        if indentation != 4:
            continue
        match = re.fullmatch(r"    ([a-z][a-z0-9_-]*):(?:\s+.*)?", line)
        if match is None or match.group(1) in job_keys:
            raise PublicBoundaryError(
                f"Tracked workflow has an ambiguous or duplicate job entry: '{path}'."
            )
        job_keys.add(match.group(1))
    if job_keys != {"container", "runs-on", "steps", "timeout-minutes"}:
        raise PublicBoundaryError(
            f"Tracked workflow job shape differs from its reviewed contract: '{path}'."
        )
    timeout_matches = re.findall(
        r"(?m)^ {4}timeout-minutes:[ \t]*([0-9]+)[ \t]*$", code_text
    )
    if len(timeout_matches) != 1 or (
        not allow_reviewed_environment_migration and timeout_matches[0] != "30"
    ) or (
        allow_reviewed_environment_migration
        and not 1 <= int(timeout_matches[0]) <= 60
    ):
        raise PublicBoundaryError(
            f"Tracked workflow timeout differs from its reviewed bounded contract: '{path}'."
        )
    runner_matches = re.findall(r"(?m)^ {4}runs-on:[ \t]*([^\s]+)[ \t]*$", code_text)
    runner_is_valid = (
        len(runner_matches) == 1
        and (
            runner_matches[0] == "ubuntu-24.04"
            if not allow_reviewed_environment_migration
            else re.fullmatch(r"ubuntu-[0-9]{2}\.[0-9]{2}", runner_matches[0])
            is not None
        )
    )
    if len(re.findall(r"(?m)^[ \t]+runs-on[ \t]*:", code_text)) != 1 or not runner_is_valid:
        raise PublicBoundaryError(
            f"Tracked workflow must use one reviewed dated Ubuntu runner label: '{path}'."
        )
    if len(re.findall(r"(?m)^[ \t]+container[ \t]*:", code_text)) != 1 or len(
        re.findall(r"(?m)^[ \t]+image[ \t]*:", code_text)
    ) != 1:
        raise PublicBoundaryError(
            f"Tracked workflow must define exactly one reviewed job container: '{path}'."
        )
    container_start = code_lines.index("    container:")
    container_keys: set[str] = set()
    for line in code_lines[container_start + 1:]:
        if line and len(line) - len(line.lstrip(" ")) <= 4:
            break
        indentation = len(line) - len(line.lstrip(" "))
        if indentation != 6 or not line.strip():
            continue
        match = re.fullmatch(r"      ([a-z][a-z0-9_-]*):(?:\s+.*)?", line)
        if match is None or match.group(1) in container_keys:
            raise PublicBoundaryError(
                f"Tracked workflow has an ambiguous or duplicate container entry: '{path}'."
            )
        container_keys.add(match.group(1))
    if container_keys != {"image"}:
        raise PublicBoundaryError(
            f"Tracked workflow container may contain only its reviewed image: '{path}'."
        )
    image_matches = re.findall(r"(?m)^ {6}image:[ \t]*([^\s]+)[ \t]*$", code_text)
    image_is_valid = (
        len(image_matches) == 1
        and (
            image_matches[0] == V1_EXECUTION_IMAGE
            if not allow_reviewed_environment_migration
            else len(image_matches[0]) <= 255
            and re.fullmatch(
                r"[a-z0-9](?:[a-z0-9._:-]*[a-z0-9])?"
                r"(?:\x2f[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)*"
                r"@sha256:[a-f0-9]{64}",
                image_matches[0],
            )
            is not None
        )
    )
    if not image_is_valid:
        raise PublicBoundaryError(
            f"Tracked workflow must use one reviewed digest-pinned execution image: '{path}'."
        )
    if "workflow_dispatch:" in code_text:
        raise PublicBoundaryError(
            f"Tracked validation workflow may not expose manual dispatch: '{path}'."
        )
    if path != ".github/workflows/release-policy.yml" and "pull_request_target:" in code_text:
        raise PublicBoundaryError(
            f"Only the reviewed release-policy workflow may use pull_request_target: '{path}'."
        )
    step_matches = list(
        re.finditer(
            r"(?ms)^      - name: ([^\n]+)\n.*?(?=^      - name: |\Z)",
            text,
        )
    )
    steps_start = code_lines.index("    steps:")
    steps_text = "\n".join(code_lines[steps_start + 1:])
    step_items = re.findall(r"(?m)^      -\s+", steps_text)
    if len(step_items) != len(step_matches):
        raise PublicBoundaryError(
            f"Tracked workflow contains an unnamed or unreviewed step item: '{path}'."
        )
    actual_steps = tuple(
        (
            match.group(1),
            hashlib.sha256((match.group(0).rstrip() + "\n").encode("utf-8")).hexdigest(),
        )
        for match in step_matches
    )
    if actual_steps != WORKFLOW_STEP_HASHES[path]:
        raise PublicBoundaryError(
            f"Tracked workflow step order or command contract differs from reviewed authority: '{path}'."
        )


def _execution_migration_allows_environment_rotation(
    root: Path, base: str, head: str, branch: str | None
) -> bool:
    if branch is None:
        return False
    _normalized_path(branch)
    match = EXECUTION_MIGRATION_BRANCH_RE.fullmatch(branch)
    if match is None:
        return False
    ancestry = _run_git(root, "rev-list", "--parents", "-n", "1", head).decode("ascii").split()
    if ancestry != [head, base]:
        raise PublicBoundaryError(
            "A reviewed execution migration must be one commit on the exact base."
        )
    raw = _run_git(root, "diff", "--name-status", "--no-renames", "-z", base, head)
    fields = [field for field in raw.split(b"\0") if field]
    if not fields or len(fields) % 2:
        raise PublicBoundaryError("Reviewed execution migration has an invalid changed-path set.")
    changes: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii", errors="strict")
            path = _normalized_path(fields[index + 1].decode("utf-8", errors="strict"))
        except UnicodeDecodeError as exc:
            raise PublicBoundaryError(
                "Reviewed execution migration contains an unreadable path."
            ) from exc
        if status != "M" or path not in EVOLVABLE_V1_EXECUTION_PATHS:
            raise PublicBoundaryError(
                "Reviewed execution migration may modify only its exact existing closure."
            )
        changes.append((status, path))
    material = ["runtime-v1-execution-migration-v1", base]
    for status, path in sorted(changes, key=lambda item: item[1]):
        blob = _run_git(root, "show", f"{head}:{path}")
        material.extend((status, path, hashlib.sha256(blob).hexdigest()))
    operation_id = hashlib.sha256(("\n".join(material) + "\n").encode("utf-8")).hexdigest()
    if match.group("operation_id") != operation_id:
        raise PublicBoundaryError(
            "Reviewed execution-migration branch identity differs from its exact bytes."
        )
    return any(path in WORKFLOW_FILES for _status, path in changes)


def _tree_entries(root: Path, revision: str) -> list[tuple[str, str, str, int]]:
    raw = _run_git(root, "ls-tree", "-r", "-l", "-z", revision)
    entries: list[tuple[str, str, str, int]] = []
    casefolded_prefixes: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id, raw_size = metadata.decode("ascii").split()
            path = _normalized_path(raw_path.decode("utf-8", errors="strict"))
            _require_windows_portable_path(path)
            size = int(raw_size)
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublicBoundaryError("Git tree contains an unreadable tracked entry.") from exc
        if kind != "blob" or mode != "100644":
            raise PublicBoundaryError("Tracked public entry must be a normal non-executable file.")
        prefix_parts: list[str] = []
        for component in PurePosixPath(path).parts:
            prefix_parts.append(component)
            prefix = "/".join(prefix_parts)
            folded = prefix.casefold()
            prior = casefolded_prefixes.setdefault(folded, prefix)
            if prior != prefix:
                raise PublicBoundaryError(
                    "Tracked public paths collide in the required case-insensitive recovery environment."
                )
        entries.append((path, mode, object_id, size))
    return entries


def _blob_bytes(root: Path, object_ids: list[str]) -> dict[str, bytes]:
    unique_ids = list(dict.fromkeys(object_ids))
    request = "".join(f"{object_id}\n" for object_id in unique_ids).encode("ascii")
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "cat-file",
            "--batch",
        ],
        input=request,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PublicBoundaryError(
            "git cat-file --batch failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    blobs: dict[str, bytes] = {}
    offset = 0
    for expected_id in unique_ids:
        newline = result.stdout.find(b"\n", offset)
        if newline < 0:
            raise PublicBoundaryError("git cat-file returned a truncated blob header.")
        header = result.stdout[offset:newline].decode("ascii").split()
        if len(header) != 3 or header[0] != expected_id or header[1] != "blob":
            raise PublicBoundaryError("git cat-file returned unexpected blob evidence.")
        size = int(header[2])
        start = newline + 1
        end = start + size
        if end >= len(result.stdout) or result.stdout[end:end + 1] != b"\n":
            raise PublicBoundaryError("git cat-file returned truncated blob bytes.")
        blobs[expected_id] = result.stdout[start:end]
        offset = end + 1
    if offset != len(result.stdout):
        raise PublicBoundaryError("git cat-file returned unexplained trailing output.")
    return blobs


def _validate_commit_message(root: Path, revision: str) -> None:
    if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise PublicBoundaryError("Candidate revision is not one lowercase full commit SHA.")
    try:
        object_size = int(_run_git(root, "cat-file", "-s", revision).decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PublicBoundaryError("Candidate commit object has an invalid size.") from exc
    if object_size > MAX_COMMIT_OBJECT_BYTES:
        raise PublicBoundaryError("Candidate commit object exceeds its public validation limit.")
    raw_commit = _run_git(root, "cat-file", "commit", revision)
    if len(raw_commit) != object_size:
        raise PublicBoundaryError("Git returned incomplete candidate commit evidence.")
    computed = hashlib.sha1(
        b"commit " + str(len(raw_commit)).encode("ascii") + b"\0" + raw_commit
    ).hexdigest()
    if computed != revision:
        raise PublicBoundaryError("Candidate commit bytes do not match their Git identity.")
    separator = raw_commit.find(b"\n\n")
    if separator < 0:
        raise PublicBoundaryError("Candidate commit object has no message body separator.")
    headers = raw_commit[:separator].split(b"\n")
    if not headers or re.fullmatch(br"tree [a-f0-9]{40}", headers[0]) is None:
        raise PublicBoundaryError("Candidate commit object has an invalid tree header.")
    parents: list[str] = []
    header_index = 1
    while header_index < len(headers) and headers[header_index].startswith(b"parent "):
        match = re.fullmatch(br"parent ([a-f0-9]{40})", headers[header_index])
        if match is None:
            raise PublicBoundaryError("Candidate commit object has an invalid parent header.")
        parents.append(match.group(1).decode("ascii"))
        header_index += 1
    if any(header.startswith(b"parent ") for header in headers[header_index:]):
        raise PublicBoundaryError(
            "Candidate commit parent headers are not in canonical position."
        )
    if len(parents) != len(set(parents)):
        raise PublicBoundaryError("Candidate commit object has duplicate parent headers.")
    git_parent_view = _run_git(
        root, "rev-list", "--parents", "-n", "1", revision
    ).decode("ascii").split()
    if git_parent_view != [revision, *parents]:
        raise PublicBoundaryError(
            "Candidate commit parent evidence disagrees with Git's no-replace view."
        )
    message = raw_commit[separator + 2:]
    if len(message) > MAX_COMMIT_MESSAGE_BYTES:
        raise PublicBoundaryError("Candidate commit message exceeds the 65536-byte public limit.")
    if b"\0" in message:
        raise PublicBoundaryError("Candidate commit message contains binary NUL bytes.")
    try:
        message.decode("utf-8", errors="strict")
        public_commit_text = raw_commit.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PublicBoundaryError("Candidate commit metadata or message is not UTF-8 text.") from exc
    if _has_prohibited_text_codepoint(public_commit_text, allow_layout_controls=True):
        raise PublicBoundaryError(
            "Candidate commit metadata or message contains prohibited control text."
        )
    for pattern in (*SECRET_PATTERNS, *PRIVATE_TEXT_PATTERNS):
        if pattern.search(public_commit_text):
            raise PublicBoundaryError(
                "Candidate commit metadata or message contains private or credential-shaped content."
            )


def validate_public_boundary(
    root: Path,
    revision: str,
    require_v1_authority: bool | None = None,
    allow_reviewed_environment_migration: bool = False,
) -> None:
    root = root.resolve()
    _require_unmodified_git_graph(root)
    selected = _run_git(
        root, "rev-parse", "--verify", f"{revision}^{{commit}}"
    ).decode("ascii").strip()
    _validate_commit_message(root, selected)

    entries = _tree_entries(root, selected)
    paths = {path for path, _mode, _object_id, _size in entries}
    authority_required = (
        ".github/workflows/release-policy.yml" in paths
        if require_v1_authority is None
        else require_v1_authority
    )
    if authority_required and not REQUIRED_V1_AUTHORITY_PATHS.issubset(paths):
        raise PublicBoundaryError(
            "Candidate tree is missing required V1 validation authority."
        )
    blobs = _blob_bytes(root, [object_id for _, _, object_id, _ in entries])
    for path, _mode, object_id, size in entries:
        lowered = path.casefold()
        if lowered == "objects" or lowered.startswith("objects/"):
            raise PublicBoundaryError("Content-addressed runtime object bytes belong in R2, not Git.")
        if path != "assets/.gitkeep" and (lowered == "assets" or lowered.startswith("assets/")):
            raise PublicBoundaryError("The public repository preserves only assets/.gitkeep; binary assets belong in R2.")
        if PurePosixPath(lowered).suffix in PROHIBITED_SUFFIXES:
            raise PublicBoundaryError(f"Private/source/master file format is forbidden: '{path}'.")
        if not _allowed_path(path):
            raise PublicBoundaryError(f"Tracked path is outside the explicit public repository set: '{path}'.")
        limit = MAX_JSON_BYTES if path.endswith(".json") else MAX_TEXT_BYTES
        if size > limit:
            raise PublicBoundaryError(f"Tracked public file exceeds its {limit}-byte limit: '{path}'.")

        data = blobs[object_id]
        if len(data) != size:
            raise PublicBoundaryError(f"Git blob size differs from the selected tree: '{path}'.")
        if path in V1_WHEELHOUSE:
            expected_size, expected_sha256 = V1_WHEELHOUSE[path]
            if size != expected_size or hashlib.sha256(data).hexdigest() != expected_sha256:
                raise PublicBoundaryError(
                    f"Immutable V1 wheelhouse artifact differs from its reviewed identity: '{path}'."
                )
            continue
        if path == "assets/.gitkeep" and data != b"":
            raise PublicBoundaryError("assets/.gitkeep must remain an exact empty sentinel.")
        if b"\0" in data:
            raise PublicBoundaryError(f"Tracked public file contains binary NUL bytes: '{path}'.")
        if GIT_LFS_POINTER_RE.match(data):
            raise PublicBoundaryError(
                f"Git LFS pointers are forbidden; R2 is the only runtime byte authority: '{path}'."
            )
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PublicBoundaryError(f"Tracked public file is not UTF-8 text: '{path}'.") from exc
        if _has_prohibited_text_codepoint(text, allow_layout_controls=True):
            raise PublicBoundaryError(
                f"Tracked public text contains prohibited control text: '{path}'."
            )
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise PublicBoundaryError(f"Tracked public file contains credential-shaped content: '{path}'.")
        if _contains_encoded_sigv4_credential(text):
            raise PublicBoundaryError(
                f"Tracked public file contains an encoded SigV4 credential: '{path}'."
            )
        if path in WORKFLOW_FILES:
            _validate_workflow(
                text,
                path,
                allow_reviewed_environment_migration=allow_reviewed_environment_migration,
            )
        if path == ".gitattributes":
            for line in text.splitlines():
                attributes = line.split("#", 1)[0].split()
                if any(attribute.casefold() == "filter=lfs" for attribute in attributes[1:]):
                    raise PublicBoundaryError("Git LFS filters are forbidden; runtime bytes belong in R2.")
        private_scan_text = text
        if path == ".gitignore":
            # These two exact repository-root patterns are required to keep
            # runtime bytes out of Git.  They are Git syntax, not filesystem
            # evidence.  Do not exempt comments, variants, or any other line.
            allowed_root_patterns = {
                "/" + "assets/*",
                "!/" + "assets/.gitkeep",
            }
            private_scan_text = "\n".join(
                "" if line in allowed_root_patterns else line
                for line in text.splitlines()
            )
        for pattern in PRIVATE_TEXT_PATTERNS:
            if pattern.search(private_scan_text):
                raise PublicBoundaryError(
                    f"Tracked public text contains an absolute/private path: '{path}'."
                )
        if path.endswith(".json"):
            _validate_decoded_public_json(text, path)


def validate_public_boundary_range(
    root: Path, base: str, head: str, branch: str | None = None
) -> None:
    root = root.resolve()
    _require_unmodified_git_graph(root)
    resolved_base = _run_git(root, "rev-parse", base).decode("ascii").strip()
    resolved_head = _run_git(root, "rev-parse", head).decode("ascii").strip()
    merge_base = _run_git(root, "merge-base", resolved_base, resolved_head).decode("ascii").strip()
    if merge_base != resolved_base:
        raise PublicBoundaryError("Public-boundary range head must descend from the exact reviewed base.")
    raw_revisions = _run_git(
        root, "rev-list", "--reverse", "--topo-order", f"{resolved_base}..{resolved_head}"
    )
    revisions = [line for line in raw_revisions.decode("ascii").splitlines() if line]
    if not revisions:
        raise PublicBoundaryError("Public-boundary range contains no candidate commits.")
    allow_reviewed_environment_migration = _execution_migration_allows_environment_rotation(
        root, resolved_base, resolved_head, branch
    )
    base_paths = {
        path for path, _mode, _object_id, _size in _tree_entries(root, resolved_base)
    }
    authority_required = ".github/workflows/release-policy.yml" in base_paths
    for revision in revisions:
        validate_public_boundary(
            root,
            revision,
            require_v1_authority=(
                authority_required
                or ".github/workflows/release-policy.yml"
                in {
                    path
                    for path, _mode, _object_id, _size in _tree_entries(root, revision)
                }
            ),
            allow_reviewed_environment_migration=allow_reviewed_environment_migration,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--branch")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.revision and not args.base and not args.head:
            validate_public_boundary(args.root, args.revision)
        elif not args.revision and args.base and args.head:
            validate_public_boundary_range(args.root, args.base, args.head, args.branch)
        else:
            raise PublicBoundaryError("Use either --revision or the complete --base/--head range.")
    except (PublicBoundaryError, OSError, UnicodeError, ValueError) as exc:
        print(f"Public repository boundary validation FAILED: {exc}", file=sys.stderr)
        return 1
    print("Tracked public repository boundary passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
