#!/usr/bin/env python3
"""Validate immutable V1 runtime releases and reviewed current-pointer changes.

Infrastructure-only trees with no release artifacts or current pointer remain
valid. Once release state exists, every catalog, descriptor, tag, graph edge,
and pointer transition is checked against the permanent public contracts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote_to_bytes

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
RELEASES_ROOT = PurePosixPath("manifests/releases")
CURRENT_POINTER_PATH = RELEASES_ROOT / "current.json"
RELEASE_SCHEMA_PATH = PurePosixPath("schemas/runtime-release-v1.schema.json")
POINTER_SCHEMA_PATH = PurePosixPath("schemas/runtime-current-pointer-v1.schema.json")
CONSUMER_CATALOG_SCHEMA_PATH = PurePosixPath("schemas/nl-asset-consumer-catalog-v1.schema.json")
IMMUTABLE_V1_SCHEMA_PATHS = frozenset(
    {
        RELEASE_SCHEMA_PATH.as_posix(),
        POINTER_SCHEMA_PATH.as_posix(),
        CONSUMER_CATALOG_SCHEMA_PATH.as_posix(),
    }
)
IMMUTABLE_V1_WHEEL_PATHS = frozenset(
    {
        "ci/wheelhouse/attrs-26.1.0-py3-none-any.whl",
        "ci/wheelhouse/jsonschema-4.26.0-py3-none-any.whl",
        "ci/wheelhouse/jsonschema_specifications-2025.9.1-py3-none-any.whl",
        "ci/wheelhouse/referencing-0.37.0-py3-none-any.whl",
        "ci/wheelhouse/rfc3339_validator-0.1.4-py2.py3-none-any.whl",
        "ci/wheelhouse/rpds_py-2026.6.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        "ci/wheelhouse/six-1.17.0-py2.py3-none-any.whl",
        "ci/wheelhouse/typing_extensions-4.16.0-py3-none-any.whl",
    }
)
IMMUTABLE_V1_AUTHORITY_PATHS = IMMUTABLE_V1_SCHEMA_PATHS | frozenset(
    {
        ".gitattributes",
        "requirements-ci.txt",
        "tools/verify_v1_wheelhouse.py",
        PurePosixPath("tools/validate_runtime_release_v1.py").as_posix(),
    }
) | IMMUTABLE_V1_WHEEL_PATHS
EVOLVABLE_V1_EXECUTION_PATHS = frozenset(
    {
        ".github/workflows/release-policy.yml",
        ".github/workflows/validate-runtime.yml",
        "tools/validate_public_boundary.py",
        "tools/validate_runtime_release.py",
    }
)
V1_ACTIVATION_MARKER_PATH = ".github/workflows/release-policy.yml"
V1_WHEELHOUSE_PREFIX = "ci/wheelhouse/"
EXECUTION_WORKFLOW_TRIGGERS = {
    ".github/workflows/release-policy.yml": (
        "  pull_request_target:",
        "    branches: [main]",
        "    types: [opened, reopened, synchronize, ready_for_review]",
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
    ),
}

RELEASE_ID = r"runtime-v1-[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*"
RELEASE_ID_RE = re.compile(rf"^{RELEASE_ID}$")
ARTIFACT_BRANCH_RE = re.compile(
    rf"^publish/artifacts/(?P<release>{RELEASE_ID})\x2ffrom\x2f"
    rf"(?P<source>none|{RELEASE_ID})\x2f(?P<operation_id>[a-f0-9]{{64}})$"
)
POINTER_BRANCH_RE = re.compile(
    rf"^publish/pointer/(?P<operation>select|rollback|restore)\x2f"
    rf"(?P<target>{RELEASE_ID})\x2ffrom\x2f(?P<source>none|{RELEASE_ID})\x2f"
    r"(?P<operation_id>[a-f0-9]{64})$"
)
EXECUTION_MIGRATION_BRANCH_RE = re.compile(
    r"^infrastructure/runtime-v1-execution/(?P<operation_id>[a-f0-9]{64})$"
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
COMMIT_RE = re.compile(r"^[a-f0-9]{40}$")
UTC_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
MAX_INT32 = 2_147_483_647
MIB = 1024 * 1024
MAX_RELEASE_OBJECT_BYTES = 64 * MIB
MAX_RELEASE_TOTAL_BYTES = 8 * 1024 * MIB
FORMAT_MAX_BYTES = {
    "svg": 2 * MIB,
    "webp": 16 * MIB,
    "png": 16 * MIB,
    "jpg": 16 * MIB,
    "jpeg": 16 * MIB,
    "gltf": 8 * MIB,
    "glb": 64 * MIB,
}
MAX_TAG_OBJECT_BYTES = 64 * 1024
MAX_COMMIT_OBJECT_BYTES = 128 * 1024
MAX_EXECUTION_WORKFLOW_BYTES = 256 * 1024
MAX_REF_COUNT = 100_000
_SCHEMA_AUTHORITY_ROOT: Path | None = None
_SCHEMA_AUTHORITY_REVISION: str | None = None
MAX_TAG_CHAIN_DEPTH = 64
MAX_JSON_DEPTH = 64
UNSAFE_GIT_ENVIRONMENT = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)
RUNTIME_TAGGER_NAME = "NL Asset Runtime Publisher"
RUNTIME_TAGGER_EMAIL = "nl-asset-runtime-publisher[bot]@users.noreply.github.com"
RUNTIME_TAGGER_RE = re.compile(
    rf"^tagger {re.escape(RUNTIME_TAGGER_NAME)} <{re.escape(RUNTIME_TAGGER_EMAIL)}> "
    r"(?P<timestamp>[0-9]+) \+0000$"
)

PRIVATE_STRING_PATTERNS = (
    ("GitHub credential", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained credential", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    (
        "private-key material",
        re.compile(
            r"-----BEGIN (?:(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
        ),
    ),
    ("AWS access-key identity", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "labeled AWS or R2 secret access key",
        re.compile(
            r"(?i)\b(?:aws_secret_access_key|r2_secret_access_key)[\"']?\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9/+=]{40,}(?=$|[\s\"'])"
        ),
    ),
    (
        "labeled AWS session credential",
        re.compile(
            r"(?i)\baws_session_token[\"']?\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9/+=]{32,}(?=$|[\s\"'])"
        ),
    ),
    (
        "labeled R2 access-key identity",
        re.compile(
            r"(?i)\br2_access_key_id[\"']?\s*[:=]\s*[\"']?"
            r"[A-Za-z0-9]{32,}(?=$|[\s\"'])"
        ),
    ),
    (
        "Google API credential",
        re.compile(
            r"(?i)\bgoogle_api_key[\"']?\s*[:=]\s*[\"']?"
            r"AIza[A-Za-z0-9_-]{35}(?=$|[\s\"'])"
        ),
    ),
    (
        "Google OAuth client credential",
        re.compile(
            r"(?i)\b(?:google_client_secret|client_secret)[\"']?\s*[:=]\s*"
            r"[\"']?GOCSPX-[A-Za-z0-9_-]{20,}(?=$|[\s\"'])"
        ),
    ),
    ("provider secret", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "labeled provider credential",
        re.compile(
            r"(?i)\b(?:cloudflare_api_token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~-]{20,}"
        ),
    ),
    (
        "Cloudflare Access client credential",
        re.compile(
            r"(?i)\b(?:cf_access_client_secret|cloudflare_access_client_secret)"
            r"[\"']?\s*[:=]\s*[\"']?[a-f0-9]{64}(?=$|[\s\"'])"
        ),
    ),
    (
        "AWS SigV4 credential scope",
        re.compile(
            r"(?i)\bx-amz-credential[\"']?\s*(?:=|%3d|:)\s*[\"']?"
            r"[a-z0-9]{16,64}(?:\x2f|%2f)"
        ),
    ),
    (
        "AWS SigV4 security token",
        re.compile(
            r"(?i)\bx-amz-security-token[\"']?\s*(?:=|%3d|:)\s*[\"']?"
            r"[a-z0-9._~+/%=-]{20,}(?=$|[&\s\"'])"
        ),
    ),
    (
        "AWS SigV4 signature",
        re.compile(
            r"(?i)\bx-amz-signature[\"']?\s*(?:=|%3d|:)\s*[\"']?"
            r"[a-f0-9]{64}(?=$|[&\s\"'])"
        ),
    ),
    (
        "bearer credential",
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    ),
    ("Windows absolute path", re.compile(r"(?i)(?:^|[\s\"'`()=:\[])(?:[a-z]:[\\/])")),
    ("UNC path", re.compile(r"(?:^|[\s\"'`()=\[])(?:\\\\|//)[^\\/\s]+[\\/][^\\/\s]+")),
    ("file URI", re.compile(r"(?i)\bfile:(?://|\\\\)")),
    (
        "POSIX absolute path",
        re.compile(r"(?:^|[\s\"'`()=:\[\{,;])\x2f(?!\x2f)[^\s\"'`()\]\},;]+"),
    ),
    (
        "home-relative path",
        re.compile(r"(?:^|[\s\"'`()=:\[\{,;])~[\\/][^\s\"'`()\]\},;]+"),
    ),
    (
        "private vault path",
        re.compile(
            r"(?i)(?:^|[\\/])(?:\.ssh|\.aws|\.azure|appdata|secrets?|vault|credentials?|private[-_ ]?keys?)(?:[\\/]|$)"
        ),
    ),
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


class ReleaseValidationError(RuntimeError):
    """A fail-closed release-contract violation."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseValidationError("JSON contains a duplicate member name.")
        result[key] = value
    return result


def _reject_non_json_constant(_value: str) -> None:
    raise ReleaseValidationError("JSON contains a non-standard numeric constant.")


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
                raise ReleaseValidationError(
                    "JSON exceeds the maximum reviewed nesting depth."
                )
        elif character in "]}":
            depth -= 1


def _require_bounded_value_depth(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, dict):
            child_depth = depth + 1
            if child_depth > MAX_JSON_DEPTH:
                raise ReleaseValidationError(
                    "JSON exceeds the maximum reviewed nesting depth."
                )
            pending.extend((child, child_depth) for child in current.values())
        elif isinstance(current, list):
            child_depth = depth + 1
            if child_depth > MAX_JSON_DEPTH:
                raise ReleaseValidationError(
                    "JSON exceeds the maximum reviewed nesting depth."
                )
            pending.extend((child, child_depth) for child in current)


def load_json_bytes(data: bytes, label: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError(f"{label} is not valid UTF-8: {exc}") from exc
    _require_bounded_json_text_depth(text)
    for description, pattern in PRIVATE_STRING_PATTERNS:
        if pattern.search(text):
            raise ReleaseValidationError(
                f"{label} contains prohibited {description} text."
            )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_non_json_constant,
        )
    except (json.JSONDecodeError, ReleaseValidationError) as exc:
        raise ReleaseValidationError(f"{label} is not valid strict JSON: {exc}") from exc
    reject_private_strings(value, label)
    return value


def load_json_file(path: Path, label: str | None = None) -> Any:
    try:
        return load_json_bytes(path.read_bytes(), label or path.as_posix())
    except OSError as exc:
        raise ReleaseValidationError(f"Unable to read {label or path.as_posix()}: {exc}") from exc


def _system_text_json_string(value: str) -> str:
    escaped = ['"']
    named_controls = {
        "\b": r"\b",
        "\t": r"\t",
        "\n": r"\n",
        "\f": r"\f",
        "\r": r"\r",
    }
    html_sensitive = {'"', "&", "'", "+", "<", ">", "`"}
    for character in value:
        if character in named_controls:
            escaped.append(named_controls[character])
            continue
        codepoint = ord(character)
        if character == "\\":
            escaped.append(r"\\")
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ReleaseValidationError("Canonical JSON strings cannot contain unpaired UTF-16 surrogates.")
        elif character in html_sensitive or codepoint < 0x20:
            escaped.append(f"\\u{codepoint:04X}")
        elif codepoint <= 0x7E:
            escaped.append(character)
        elif codepoint <= 0xFFFF:
            escaped.append(f"\\u{codepoint:04X}")
        else:
            scalar = codepoint - 0x10000
            high = 0xD800 + (scalar >> 10)
            low = 0xDC00 + (scalar & 0x3FF)
            escaped.append(f"\\u{high:04X}\\u{low:04X}")
    escaped.append('"')
    return "".join(escaped)


def _dotnet_ordinal_key(value: str) -> bytes:
    """Return the UTF-16 code-unit ordering key used by StringComparer.Ordinal."""
    return value.encode("utf-16-be", errors="surrogatepass")


def _canonical_json_text(value: Any, depth: int = 0) -> str:
    indent = "  " * depth
    child_indent = "  " * (depth + 1)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _system_text_json_string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        rendered = [f"{child_indent}{_canonical_json_text(item, depth + 1)}" for item in value]
        return "[\n" + ",\n".join(rendered) + f"\n{indent}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        rendered = [
            f"{child_indent}{_system_text_json_string(key)}: {_canonical_json_text(value[key], depth + 1)}"
            for key in sorted(value, key=_dotnet_ordinal_key)
        ]
        return "{\n" + ",\n".join(rendered) + f"\n{indent}}}"
    raise ReleaseValidationError(f"Canonical JSON does not support value type {type(value).__name__}.")


def canonical_json_bytes(value: Any) -> bytes:
    _require_bounded_value_depth(value)
    return (_canonical_json_text(value) + "\n").encode("utf-8")


def require_canonical_json(data: bytes, value: Any, label: str) -> None:
    if data != canonical_json_bytes(value):
        raise ReleaseValidationError(
            f"{label} must use canonical UTF-8 JSON (sorted keys, two-space indentation, one final newline)."
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk_strings(value: Any, path: str = "<root>") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pending: list[tuple[Any, str]] = [(value, path)]
    while pending:
        current, current_path = pending.pop()
        if isinstance(current, str):
            found.append((current_path, current))
        elif isinstance(current, dict):
            for index, (key, child) in reversed(list(enumerate(current.items()))):
                pending.append((child, f"{current_path}.values[{index}]"))
                found.append((f"{current_path}.keys[{index}]", key))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], f"{current_path}[{index}]"))
    return found


def _walk_labeled_descendant_strings(
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


def reject_private_strings(value: Any, label: str) -> None:
    for path, text in _walk_strings(value):
        for character in text:
            codepoint = ord(character)
            if (
                codepoint < 0x20
                or 0x7F <= codepoint <= 0x9F
                or codepoint in {0x061C, 0x200E, 0x200F}
                or 0x202A <= codepoint <= 0x202E
                or 0x2066 <= codepoint <= 0x2069
            ):
                raise ReleaseValidationError(
                    f"{label} contains prohibited control or bidirectional-format text at {path}."
                )
        for description, pattern in PRIVATE_STRING_PATTERNS:
            if pattern.search(text):
                raise ReleaseValidationError(
                    f"{label} contains prohibited {description} text at {path}."
                )
        if _contains_encoded_sigv4_credential(text):
            raise ReleaseValidationError(
                f"{label} contains a prohibited encoded SigV4 credential at {path}."
            )
    # Scan a decoded structural rendering as well as each string in isolation.
    # Otherwise an escaped JSON key can hide a credential label while its
    # sibling value independently looks like an ordinary opaque identifier.
    decoded_relationships = json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    )
    for description, pattern in PRIVATE_STRING_PATTERNS:
        if pattern.search(decoded_relationships):
            raise ReleaseValidationError(
                f"{label} contains prohibited {description} text in decoded JSON relationships."
            )
    for key, descendant in _walk_labeled_descendant_strings(value):
        if _is_labeled_credential(key, descendant):
            raise ReleaseValidationError(
                f"{label} contains a prohibited labeled credential in a decoded JSON descendant relationship."
            )
        relationship = (
            json.dumps(key, ensure_ascii=False)
            + ":"
            + json.dumps(descendant, ensure_ascii=False)
        )
        for description, pattern in PRIVATE_STRING_PATTERNS:
            if pattern.search(relationship):
                raise ReleaseValidationError(
                    f"{label} contains prohibited {description} text in a decoded JSON descendant relationship."
                )
        if _contains_encoded_sigv4_credential(relationship):
            raise ReleaseValidationError(
                f"{label} contains a prohibited encoded SigV4 credential in a decoded JSON descendant relationship."
            )


def require_public_branch_name(value: str) -> None:
    generic_error = "Pull-request branch name is not public-safe."
    if not value or not value.isascii():
        raise ReleaseValidationError(generic_error)
    try:
        reject_private_strings(value, "Pull-request branch name")
    except ReleaseValidationError:
        raise ReleaseValidationError(generic_error) from None
    if re.search(r"(?i)(?:^|/)(?:[a-z]:|~)[\\/]", value):
        raise ReleaseValidationError(generic_error)


def consumer_asset_version_material(asset: dict[str, Any]) -> dict[str, Any]:
    """Return NLAssetConsumerAssetVersionMaterialV1.

    Release selection and transport location are intentionally absent:
    releaseId, generatedAt, and each derived CDN URL do not change the
    immutable public semantic identity of an asset.
    """
    return {
        "accessibility": asset["accessibility"],
        "assetId": asset["assetId"],
        "deprecated": asset["deprecated"],
        "displayName": asset["displayName"],
        "fallbackAssetId": asset["fallbackAssetId"],
        "publicCredit": asset["publicCredit"],
        "readinessStatus": asset["readinessStatus"],
        "sanitizedProvenance": asset["sanitizedProvenance"],
        "styles": asset["styles"],
        "subjects": asset["subjects"],
        "subtype": asset["subtype"],
        "tags": asset["tags"],
        "themes": asset["themes"],
        "type": asset["type"],
        "useCases": asset["useCases"],
        "variants": [
            {
                "bytes": variant["bytes"],
                "format": variant["format"],
                "height": variant["height"],
                "mimeType": variant["mimeType"],
                "objectKey": variant["objectKey"],
                "sha256": variant["sha256"],
                "width": variant["width"],
            }
            for variant in asset["variants"]
        ],
    }


def expected_consumer_asset_version(asset: dict[str, Any]) -> str:
    material = consumer_asset_version_material(asset)
    return f"sha256:{sha256_bytes(canonical_json_bytes(material))}"


def pointer_operation_identity(
    operation: str,
    target_release_id: str,
    source_release_id: str,
    base_commit: str,
    pointer_bytes: bytes,
) -> str:
    if not COMMIT_RE.fullmatch(base_commit):
        raise ReleaseValidationError("Pointer operation base is not a lowercase full Git SHA.")
    pointer_sha256 = sha256_bytes(pointer_bytes)
    material = (
        "runtime-pointer-operation-v1\n"
        f"{operation}\n{target_release_id}\n{source_release_id}\n{base_commit}\n{pointer_sha256}\n"
    ).encode("utf-8")
    return sha256_bytes(material)


def artifact_operation_identity(
    release_id: str,
    source_release_id: str,
    base_commit: str,
    release_bytes: bytes,
    catalog_bytes: bytes,
) -> str:
    require_release_id(release_id, "artifact operation release")
    if source_release_id != "none":
        require_release_id(source_release_id, "artifact operation source")
    if not COMMIT_RE.fullmatch(base_commit):
        raise ReleaseValidationError("Artifact operation base is not a lowercase full Git SHA.")
    material = (
        "runtime-artifact-operation-v1\n"
        f"{release_id}\n{source_release_id}\n{base_commit}\n"
        f"{sha256_bytes(release_bytes)}\n{sha256_bytes(catalog_bytes)}\n"
    ).encode("utf-8")
    return sha256_bytes(material)


def validate_schema(value: Any, schema: Any, label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    rendered = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{location}: {error.message}")
    raise ReleaseValidationError(f"{label} failed schema validation: {'; '.join(rendered)}")


def normalize_repo_path(value: str, label: str) -> str:
    reject_private_strings(value, label)
    if not value or "\\" in value or value.startswith("/"):
        raise ReleaseValidationError(f"{label} is not a normalized repository-relative path.")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseValidationError(f"{label} contains an unsafe path segment.")
    return path.as_posix()


def release_directory_path(release_id: str) -> PurePosixPath:
    return RELEASES_ROOT / release_id


def release_document_path(release_id: str) -> PurePosixPath:
    return release_directory_path(release_id) / "release.json"


def consumer_catalog_path(release_id: str) -> PurePosixPath:
    return release_directory_path(release_id) / "consumer-catalog.json"


def require_release_id(value: str, label: str = "release ID") -> None:
    if not RELEASE_ID_RE.fullmatch(value):
        raise ReleaseValidationError(f"{label} is not a purpose-based immutable runtime release ID: '{value}'.")
    try:
        date_text = value.removeprefix("runtime-v1-").rsplit(".", 1)[0].replace(".", "-")
        dt.date.fromisoformat(date_text)
    except ValueError as exc:
        raise ReleaseValidationError(f"{label} contains an invalid calendar date: '{value}'.") from exc
    sequence = int(value.rsplit(".", 1)[1])
    if sequence > MAX_INT32:
        raise ReleaseValidationError(
            f"{label} sequence exceeds the permanent Int32 contract maximum ({MAX_INT32})."
        )


def release_sort_key(value: str) -> tuple[dt.date, int]:
    require_release_id(value)
    date_part, sequence = value.removeprefix("runtime-v1-").rsplit(".", 1)
    return dt.date.fromisoformat(date_part.replace(".", "-")), int(sequence)


def require_canonical_utc_timestamp(value: str, label: str) -> dt.datetime:
    if not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ReleaseValidationError(
            f"{label} must be canonical UTC with second precision: YYYY-MM-DDTHH:MM:SSZ."
        )
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise ReleaseValidationError(f"{label} is not a valid UTC timestamp: '{value}'.") from exc


def _fold_component(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def reject_release_namespace_alias(path: str) -> None:
    parts = PurePosixPath(path).parts
    if len(parts) < 2:
        return
    first, second = parts[0], parts[1]
    folded_first = _fold_component(first)
    folded_second = _fold_component(second)
    first_near = folded_first == "manifests" or (not first.isascii() and folded_second == "releases")
    second_near = folded_second == "releases" or (not second.isascii() and folded_first == "manifests")
    if first_near and second_near and (first != "manifests" or second != "releases"):
        raise ReleaseValidationError(
            "Confusable reviewed release namespace paths are forbidden."
        )


def _root_path(root: Path, relative: PurePosixPath) -> Path:
    return root.joinpath(*relative.parts)


def _schema_authority_path(root: Path, relative: PurePosixPath) -> Path:
    authority_root = _SCHEMA_AUTHORITY_ROOT or root
    return authority_root.joinpath(*relative.parts)


def _schema_authority_bytes(
    root: Path, relative: PurePosixPath, revision: str | None = None
) -> bytes:
    if _SCHEMA_AUTHORITY_ROOT is not None:
        if _SCHEMA_AUTHORITY_REVISION is None:
            raise ReleaseValidationError(
                "The separately trusted V1 schema authority is not revision-bound."
            )
        return _git_blob(
            _SCHEMA_AUTHORITY_ROOT,
            _SCHEMA_AUTHORITY_REVISION,
            relative.as_posix(),
        )
    if revision is not None:
        return _git_blob(root, revision, relative.as_posix())
    path = _schema_authority_path(root, relative)
    if not path.is_file() or path.is_symlink():
        raise ReleaseValidationError(
            f"Required V1 schema authority is absent: {relative.as_posix()}."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReleaseValidationError(
            f"Unable to read required V1 schema authority: {relative.as_posix()}."
        ) from exc


def _load_required_schema(
    root: Path,
    relative: PurePosixPath,
    label: str,
    revision: str | None = None,
) -> Any:
    if _SCHEMA_AUTHORITY_ROOT is not None or revision is not None:
        return load_json_bytes(
            _schema_authority_bytes(root, relative, revision), relative.as_posix()
        )
    path = _schema_authority_path(root, relative)
    if not path.is_file() or path.is_symlink():
        raise ReleaseValidationError(f"Required {label} is absent: {relative.as_posix()}.")
    return load_json_file(path, relative.as_posix())


def _validate_runtime_objects(objects: list[dict[str, Any]]) -> None:
    object_keys = [item["objectKey"] for item in objects]
    if object_keys != sorted(object_keys):
        raise ReleaseValidationError("Runtime release objects must be sorted by immutable objectKey.")
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    seen_digests: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for index, item in enumerate(objects):
        key = normalize_repo_path(item["objectKey"], f"objects[{index}].objectKey")
        digest = item["sha256"]
        if not SHA256_RE.fullmatch(digest):
            raise ReleaseValidationError(f"objects[{index}].sha256 is not lowercase SHA-256.")
        expected_prefix = f"objects/sha256/{digest[:2]}/{digest}."
        if not key.startswith(expected_prefix):
            raise ReleaseValidationError(
                f"objects[{index}].objectKey is not content-addressed by its declared SHA-256."
            )
        expected_url = f"https://cdn.nlightlabs.com/{key}"
        if item["url"] != expected_url:
            raise ReleaseValidationError(
                f"objects[{index}].url must be the canonical CDN URL for its immutable object key."
            )
        if key in seen_keys or item["url"] in seen_urls:
            raise ReleaseValidationError("Runtime release object keys and URLs must be unique.")
        if item["bytes"] > MAX_RELEASE_OBJECT_BYTES:
            raise ReleaseValidationError(
                f"Runtime release object exceeds the {MAX_RELEASE_OBJECT_BYTES}-byte limit."
            )
        total_bytes += item["bytes"]
        if total_bytes > MAX_RELEASE_TOTAL_BYTES:
            raise ReleaseValidationError(
                f"Runtime release object set exceeds the {MAX_RELEASE_TOTAL_BYTES}-byte aggregate limit."
            )
        digest_evidence = {
            "bytes": item["bytes"],
            "objectKey": key,
            "sha256": digest,
            "url": item["url"],
        }
        prior_digest = seen_digests.get(digest)
        if prior_digest is not None and prior_digest != digest_evidence:
            raise ReleaseValidationError(
                "One immutable SHA-256 digest cannot have multiple runtime object identities."
            )
        seen_keys.add(key)
        seen_urls.add(item["url"])
        seen_digests[digest] = digest_evidence


def _validate_fallback_graph(fallbacks: dict[str, str | None]) -> None:
    """Validate all fallback chains in linear time through path compression."""
    resolved: set[str] = set()
    for start in fallbacks:
        if start in resolved:
            continue
        path: set[str] = set()
        current: str | None = start
        while current is not None and current not in resolved:
            if current in path:
                raise ReleaseValidationError(
                    f"Consumer catalog fallback graph contains a cycle reachable from '{start}'."
                )
            path.add(current)
            current = fallbacks.get(current)
        resolved.update(path)


def _validate_consumer_catalog(catalog: dict[str, Any], release_id: str) -> list[dict[str, Any]]:
    if catalog["releaseId"] != release_id:
        raise ReleaseValidationError("Consumer catalog releaseId does not match its release directory.")
    assets = catalog["assets"]
    if catalog["assetCount"] != len(assets):
        raise ReleaseValidationError("Consumer catalog assetCount does not match its assets array.")
    asset_ids = [asset["assetId"] for asset in assets]
    if asset_ids != sorted(asset_ids, key=_dotnet_ordinal_key) or len(asset_ids) != len(set(asset_ids)):
        raise ReleaseValidationError("Consumer catalog assets must be uniquely sorted by permanent assetId.")
    known_ids = set(asset_ids)
    assets_by_id = {asset["assetId"]: asset for asset in assets}
    fallbacks = {asset["assetId"]: asset["fallbackAssetId"] for asset in assets}
    _validate_fallback_graph(fallbacks)
    runtime_objects: dict[str, dict[str, Any]] = {}
    runtime_variant_evidence: dict[str, dict[str, Any]] = {}
    runtime_digest_evidence: dict[str, dict[str, Any]] = {}
    expected_mime = {
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "glb": "model/gltf-binary",
        "gltf": "model/gltf+json",
    }
    for asset in assets:
        asset_id = asset["assetId"]
        if asset["releaseId"] != release_id:
            raise ReleaseValidationError(f"Consumer asset '{asset_id}' identifies a different release.")
        for field in ("tags", "themes", "subjects", "styles", "useCases"):
            if asset[field] != sorted(asset[field], key=_dotnet_ordinal_key):
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' {field} must use .NET ordinal UTF-16 ordering."
                )
        fallback = asset["fallbackAssetId"]
        if fallback is not None and (fallback not in known_ids or fallback == asset_id):
            raise ReleaseValidationError(f"Consumer asset '{asset_id}' has an invalid fallbackAssetId.")
        if fallback is not None:
            fallback_asset = assets_by_id[fallback]
            if (
                fallback_asset["readinessStatus"] != "READY"
                or fallback_asset["deprecated"]
            ):
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' fallbackAssetId must identify a READY, nondeprecated asset."
                )
        variants = asset["variants"]
        if variants != sorted(variants, key=lambda item: (item["format"], item["objectKey"])):
            raise ReleaseValidationError(
                f"Consumer asset '{asset_id}' variants must be sorted by format and immutable object key."
            )
        seen_asset_objects: set[str] = set()
        for variant in variants:
            if variant["objectKey"] in seen_asset_objects:
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' contains a duplicate immutable variant object."
                )
            seen_asset_objects.add(variant["objectKey"])
            if (variant["width"] is None) != (variant["height"] is None):
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' variant dimensions must be both known or both null."
                )
            if variant["format"] in {"webp", "png", "jpg", "jpeg"} and (
                variant["width"] is None or variant["height"] is None
            ):
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' raster variant dimensions must be known."
                )
            if variant["mimeType"] != expected_mime[variant["format"]]:
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' variant MIME type does not match its format."
                )
            if variant["bytes"] > FORMAT_MAX_BYTES[variant["format"]]:
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' variant exceeds its format-specific byte limit."
                )
            extension = PurePosixPath(variant["objectKey"]).suffix.removeprefix(".")
            if extension != variant["format"]:
                raise ReleaseValidationError(
                    f"Consumer asset '{asset_id}' variant format does not match its object-key extension."
                )
            runtime_object = {
                "bytes": variant["bytes"],
                "objectKey": variant["objectKey"],
                "sha256": variant["sha256"],
                "url": variant["url"],
            }
            _validate_runtime_objects([runtime_object])
            immutable_variant_evidence = {
                **runtime_object,
                "format": variant["format"],
                "height": variant["height"],
                "mimeType": variant["mimeType"],
                "width": variant["width"],
            }
            prior = runtime_variant_evidence.get(runtime_object["objectKey"])
            if prior is not None and prior != immutable_variant_evidence:
                raise ReleaseValidationError(
                    f"Consumer catalog variants disagree about immutable object '{runtime_object['objectKey']}'."
                )
            prior_digest = runtime_digest_evidence.get(runtime_object["sha256"])
            if prior_digest is not None and prior_digest != immutable_variant_evidence:
                raise ReleaseValidationError(
                    "Consumer catalog assigns multiple variant identities to one immutable SHA-256 digest."
                )
            runtime_variant_evidence[runtime_object["objectKey"]] = immutable_variant_evidence
            runtime_digest_evidence[runtime_object["sha256"]] = immutable_variant_evidence
            runtime_objects[runtime_object["objectKey"]] = runtime_object
        expected_version = expected_consumer_asset_version(asset)
        if asset["assetVersion"] != expected_version:
            raise ReleaseValidationError(
                f"Consumer asset '{asset_id}' assetVersion does not match "
                "NLAssetConsumerAssetVersionMaterialV1."
            )
    return sorted(runtime_objects.values(), key=lambda item: item["objectKey"])


def validate_release_directory(
    root: Path, release_id: str, revision: str | None = None
) -> dict[str, Any]:
    require_release_id(release_id)
    relative_directory = release_directory_path(release_id)
    if revision is None:
        directory = _root_path(root, relative_directory)
        if not directory.is_dir() or directory.is_symlink():
            raise ReleaseValidationError(
                f"Release directory is missing or unsafe: {relative_directory.as_posix()}."
            )

        actual_files: list[str] = []
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ReleaseValidationError("Release artifacts cannot be symbolic links.")
            if path.is_file():
                actual_files.append(path.relative_to(root).as_posix())
    else:
        prefix = f"{relative_directory.as_posix()}/"
        actual_files = [
            path for path in _git_tree_paths(root, revision) if path.startswith(prefix)
        ]
    expected_files = sorted(
        [release_document_path(release_id).as_posix(), consumer_catalog_path(release_id).as_posix()]
    )
    if sorted(actual_files) != expected_files:
        raise ReleaseValidationError(
            "A release directory must contain exactly release.json and consumer-catalog.json."
        )

    if revision is None:
        release_bytes = _root_path(root, release_document_path(release_id)).read_bytes()
        catalog_bytes = _root_path(root, consumer_catalog_path(release_id)).read_bytes()
    else:
        release_bytes = _git_blob(
            root, revision, release_document_path(release_id).as_posix()
        )
        catalog_bytes = _git_blob(
            root, revision, consumer_catalog_path(release_id).as_posix()
        )
    release = load_json_bytes(release_bytes, release_document_path(release_id).as_posix())
    catalog = load_json_bytes(catalog_bytes, consumer_catalog_path(release_id).as_posix())
    require_canonical_json(release_bytes, release, release_document_path(release_id).as_posix())
    require_canonical_json(catalog_bytes, catalog, consumer_catalog_path(release_id).as_posix())

    release_schema = _load_required_schema(
        root, RELEASE_SCHEMA_PATH, "runtime-release-v1 schema", revision
    )
    validate_schema(release, release_schema, release_document_path(release_id).as_posix())
    reject_private_strings(release, "Runtime release descriptor")
    if release["releaseId"] != release_id:
        raise ReleaseValidationError("Release directory name and release.json releaseId do not agree.")
    if release["predecessorReleaseId"] == release_id:
        raise ReleaseValidationError("A release cannot name itself as its predecessor.")

    catalog_evidence = release["consumerCatalog"]
    expected_catalog_path = consumer_catalog_path(release_id).as_posix()
    if normalize_repo_path(catalog_evidence["path"], "consumerCatalog.path") != expected_catalog_path:
        raise ReleaseValidationError("Release consumer catalog path does not match its immutable release directory.")
    if sha256_bytes(catalog_bytes) != catalog_evidence["sha256"]:
        raise ReleaseValidationError("Release consumer catalog SHA-256 does not match the exact catalog bytes.")
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != catalog_evidence["schemaVersion"]:
        raise ReleaseValidationError("Consumer catalog schemaVersion does not match release evidence.")

    try:
        catalog_schema = _load_required_schema(
            root,
            CONSUMER_CATALOG_SCHEMA_PATH,
            "owning NLAssetConsumerCatalogV1 schema",
            revision,
        )
    except ReleaseValidationError as exc:
        raise ReleaseValidationError(
            "The owning NLAssetConsumerCatalogV1 schema is not installed; "
            "release publication remains blocked."
        ) from exc
    validate_schema(catalog, catalog_schema, expected_catalog_path)
    reject_private_strings(catalog, "Consumer catalog")
    created_at = require_canonical_utc_timestamp(release["createdAt"], "release createdAt")
    generated_at = require_canonical_utc_timestamp(catalog["generatedAt"], "catalog generatedAt")
    if created_at != generated_at:
        raise ReleaseValidationError("Release createdAt and catalog generatedAt must be identical.")
    release_date, _ = release_sort_key(release_id)
    if created_at.date() != release_date:
        raise ReleaseValidationError("Release timestamp UTC date must match the release ID date.")
    _validate_runtime_objects(release["objects"])
    catalog_objects = _validate_consumer_catalog(catalog, release_id)
    release_objects = sorted(release["objects"], key=lambda item: item["objectKey"])
    if release_objects != catalog_objects:
        raise ReleaseValidationError(
            "Runtime release object evidence does not exactly match consumer catalog variants."
        )
    return release


def _run_git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.upper().startswith("GIT_CONFIG_"):
            environment.pop(name, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
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
        env=environment,
    )
    if check and result.returncode != 0:
        raise ReleaseValidationError(
            "A Git validation command failed; untrusted command detail was withheld."
        )
    return result


def _git_text(root: Path, *arguments: str, check: bool = True) -> str:
    return _run_git(root, *arguments, check=check).stdout.decode("utf-8", errors="strict").strip()


def _require_trusted_git_repository_state(root: Path) -> None:
    unsafe_environment = any(
        name.upper() in UNSAFE_GIT_ENVIRONMENT for name in os.environ
    )
    if unsafe_environment:
        raise ReleaseValidationError(
            "Git validation forbids repository, object-store, graph, and configuration environment overrides."
        )

    control_directories: set[Path] = set()
    for selector in ("--absolute-git-dir", "--git-common-dir"):
        arguments = ["rev-parse"]
        if selector == "--git-common-dir":
            arguments.append("--path-format=absolute")
        arguments.append(selector)
        value = _git_text(root, *arguments)
        try:
            control_directory = Path(value).resolve(strict=True)
        except OSError as exc:
            raise ReleaseValidationError(
                "Git validation could not resolve its repository control directory."
            ) from exc
        if not control_directory.is_dir():
            raise ReleaseValidationError(
                "Git validation requires a normal repository control directory."
            )
        control_directories.add(control_directory)

    for control_directory in control_directories:
        for relative in (
            PurePosixPath("info/grafts"),
            PurePosixPath("shallow"),
            PurePosixPath("objects/info/alternates"),
            PurePosixPath("objects/info/http-alternates"),
        ):
            metadata_path = control_directory.joinpath(*relative.parts)
            try:
                if metadata_path.exists() and (
                    not metadata_path.is_file() or metadata_path.stat().st_size != 0
                ):
                    raise ReleaseValidationError(
                        "Git validation forbids graft, shallow, and alternate object-store metadata."
                    )
            except OSError as exc:
                raise ReleaseValidationError(
                    "Git validation could not inspect repository graph metadata."
                ) from exc

    if _git_text(root, "rev-parse", "--is-shallow-repository") != "false":
        raise ReleaseValidationError("Git validation requires complete non-shallow history.")


def _raw_commit_parents(root: Path, commit: str) -> list[str]:
    if not COMMIT_RE.fullmatch(commit):
        raise ReleaseValidationError("Git commit identity is not one lowercase full SHA.")
    try:
        object_size = int(_git_text(root, "cat-file", "-s", commit))
    except ValueError as exc:
        raise ReleaseValidationError("Git returned an invalid commit object size.") from exc
    if object_size > MAX_COMMIT_OBJECT_BYTES:
        raise ReleaseValidationError(
            f"Git commit object exceeds the {MAX_COMMIT_OBJECT_BYTES}-byte validation limit."
        )
    result = _run_git(root, "cat-file", "commit", commit, check=False)
    if result.returncode != 0 or len(result.stdout) != object_size:
        raise ReleaseValidationError("Git returned invalid raw commit object evidence.")
    raw = result.stdout
    computed = hashlib.sha1(
        b"commit " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    if computed != commit:
        raise ReleaseValidationError("Raw commit bytes do not match their Git object identity.")
    separator = raw.find(b"\n\n")
    if separator < 0:
        raise ReleaseValidationError("Git commit object has no message separator.")
    headers = raw[:separator].split(b"\n")
    if not headers or re.fullmatch(br"tree [a-f0-9]{40}", headers[0]) is None:
        raise ReleaseValidationError("Git commit object has an invalid tree header.")
    parents: list[str] = []
    header_index = 1
    while header_index < len(headers) and headers[header_index].startswith(b"parent "):
        header = headers[header_index]
        match = re.fullmatch(br"parent ([a-f0-9]{40})", header)
        if match is None:
            raise ReleaseValidationError("Git commit object has an invalid parent header.")
        parents.append(match.group(1).decode("ascii"))
        header_index += 1
    if any(header.startswith(b"parent ") for header in headers[header_index:]):
        raise ReleaseValidationError(
            "Git commit parent headers must be contiguous immediately after the tree header."
        )
    if len(parents) != len(set(parents)):
        raise ReleaseValidationError("Git commit object contains a duplicate parent header.")
    git_parent_view = _git_text(
        root, "rev-list", "--parents", "-n", "1", commit
    ).split()
    if git_parent_view != [commit, *parents]:
        raise ReleaseValidationError(
            "Raw commit parent headers disagree with Git's no-replace commit view."
        )
    return parents


def _resolve_commit_identity(root: Path, revision: str) -> str:
    identity = _git_text(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not COMMIT_RE.fullmatch(identity):
        raise ReleaseValidationError("Git did not resolve one lowercase full commit SHA.")
    return identity


def _is_raw_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    pending = [descendant]
    seen: set[str] = set()
    while pending:
        commit = pending.pop()
        if commit == ancestor:
            return True
        if commit in seen:
            continue
        seen.add(commit)
        if len(seen) > MAX_REF_COUNT:
            raise ReleaseValidationError(
                f"Git ancestry validation cannot inspect more than {MAX_REF_COUNT} commits."
            )
        pending.extend(_raw_commit_parents(root, commit))
    return False


def _require_exact_clean_checkout(root: Path, revision: str, label: str) -> None:
    if not COMMIT_RE.fullmatch(revision):
        raise ReleaseValidationError(f"{label} requires one lowercase full commit SHA.")
    _require_trusted_git_repository_state(root)
    if _resolve_commit_identity(root, "HEAD") != revision:
        raise ReleaseValidationError(f"{label} is not checked out at the exact reviewed commit.")
    if _run_git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout:
        raise ReleaseValidationError(f"{label} requires a clean index and working tree.")


def _git_tree_paths(root: Path, revision: str) -> list[str]:
    raw = _run_git(root, "ls-tree", "-r", "-z", "--name-only", revision).stdout
    try:
        values = raw.decode("utf-8", errors="strict").split("\0")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError("Git tree contains a non-UTF-8 path.") from exc
    paths = [normalize_repo_path(value, "Git tree path") for value in values if value]
    for path in paths:
        reject_release_namespace_alias(path)
    return paths


def _release_ids_at_revision(root: Path, revision: str) -> list[str]:
    release_ids: set[str] = set()
    prefix = f"{RELEASES_ROOT.as_posix()}/"
    for path in _git_tree_paths(root, revision):
        if not path.startswith(prefix) or path == CURRENT_POINTER_PATH.as_posix():
            continue
        relative = path.removeprefix(prefix)
        release_id = relative.split("/", 1)[0]
        if RELEASE_ID_RE.fullmatch(release_id):
            require_release_id(release_id)
            release_ids.add(release_id)
    return sorted(release_ids, key=release_sort_key)


def _git_blob(root: Path, revision: str, path: str) -> bytes:
    normalize_repo_path(path, "Git blob path")
    tree_result = _run_git(
        root,
        "ls-tree",
        "-z",
        revision,
        "--",
        f":(literal){path}",
        check=False,
    )
    if tree_result.returncode != 0:
        raise ReleaseValidationError("A required reviewed Git artifact is absent.")
    records = [record for record in tree_result.stdout.split(b"\0") if record]
    if len(records) != 1:
        raise ReleaseValidationError("A required reviewed Git artifact is absent or ambiguous.")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii", errors="strict").split()
        selected_path = normalize_repo_path(
            raw_path.decode("utf-8", errors="strict"), "Git blob result path"
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReleaseValidationError("Git returned invalid reviewed artifact evidence.") from exc
    if (
        selected_path != path
        or mode != "100644"
        or kind != "blob"
        or re.fullmatch(r"[a-f0-9]{40,64}", object_id) is None
    ):
        raise ReleaseValidationError(
            "A required reviewed Git artifact is not one exact normal file."
        )
    result = _run_git(root, "cat-file", "blob", object_id, check=False)
    if result.returncode != 0:
        raise ReleaseValidationError("A required reviewed Git artifact is unreadable.")
    return result.stdout


def _workflow_top_level_block(lines: list[str], key: str) -> tuple[str, ...]:
    header = f"{key}:"
    indices = [index for index, line in enumerate(lines) if line == header]
    if len(indices) != 1:
        raise ReleaseValidationError(
            "A V1 execution workflow does not have one canonical required section."
        )
    start = indices[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line and not line.startswith((" ", "#")):
            end = index
            break
    return tuple(
        line for line in lines[start:end] if line and not line.lstrip().startswith("#")
    )


def _validate_execution_workflow(path: str, raw: bytes) -> None:
    if len(raw) > MAX_EXECUTION_WORKFLOW_BYTES:
        raise ReleaseValidationError("A V1 execution workflow exceeds its public size limit.")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or b"\t" in raw or not raw.endswith(b"\n"):
        raise ReleaseValidationError(
            "A V1 execution workflow must be canonical UTF-8 text with LF line endings."
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError("A V1 execution workflow is not valid UTF-8.") from exc
    lines = text.splitlines()
    for line in lines:
        reject_private_strings(line, "V1 execution workflow")
    top_level_keys: list[str] = []
    for line in lines:
        if not line or line.startswith((" ", "#")):
            continue
        match = re.fullmatch(r"([a-z][a-z0-9-]*):(?: .*)?", line)
        if match is None:
            raise ReleaseValidationError(
                "A V1 execution workflow uses unsupported top-level YAML syntax."
            )
        top_level_keys.append(match.group(1))
    if top_level_keys != ["name", "on", "permissions", "jobs"]:
        raise ReleaseValidationError(
            "A V1 execution workflow must retain its canonical top-level trust structure."
        )
    if _workflow_top_level_block(lines, "on") != EXECUTION_WORKFLOW_TRIGGERS[path]:
        raise ReleaseValidationError(
            "A V1 execution workflow must retain its exact bounded event triggers."
        )
    if _workflow_top_level_block(lines, "permissions") != ("  contents: read",):
        raise ReleaseValidationError(
            "A V1 execution workflow must grant only read access to repository contents."
        )

    forbidden_key = re.compile(
        r"^[ ]*(?:-[ ]*)?[\"']?(?:uses|services|credentials|options|volumes)[\"']?[ ]*:",
        re.IGNORECASE,
    )
    permission_key = re.compile(
        r"^[ ]*[\"']?permissions[\"']?[ ]*:", re.IGNORECASE
    )
    if any(forbidden_key.match(line) for line in lines):
        raise ReleaseValidationError(
            "A V1 execution workflow may not use actions, services, or privileged container features."
        )
    if [line for line in lines if permission_key.match(line)] != ["permissions:"]:
        raise ReleaseValidationError(
            "A V1 execution workflow may not add or override permissions."
        )
    if re.search(r"\$\{\{\s*secrets(?:\.|\[)", text, flags=re.IGNORECASE):
        raise ReleaseValidationError(
            "A V1 execution workflow may not consume GitHub secret contexts."
        )

    jobs_start = lines.index("jobs:") + 1
    job_starts = [
        index
        for index in range(jobs_start, len(lines))
        if re.fullmatch(r"  [a-z][a-z0-9_-]*:", lines[index])
    ]
    if not job_starts:
        raise ReleaseValidationError("A V1 execution workflow must contain a bounded job.")
    job_starts.append(len(lines))
    for position in range(len(job_starts) - 1):
        job = lines[job_starts[position] : job_starts[position + 1]]
        runners = [line for line in job if line.startswith("    runs-on:")]
        if len(runners) != 1 or re.fullmatch(
            r"    runs-on: ubuntu-[0-9]{2}\.[0-9]{2}", runners[0]
        ) is None:
            raise ReleaseValidationError(
                "Each V1 execution job must pin one dated Ubuntu runner label."
            )
        timeouts = [line for line in job if line.startswith("    timeout-minutes:")]
        if len(timeouts) != 1 or re.fullmatch(
            r"    timeout-minutes: (?:[1-9]|[1-5][0-9]|60)", timeouts[0]
        ) is None:
            raise ReleaseValidationError(
                "Each V1 execution job must retain a timeout of at most 60 minutes."
            )
        if job.count("    container:") != 1 or job.count("    steps:") != 1:
            raise ReleaseValidationError(
                "Each V1 execution job must use one pinned container and an explicit step list."
            )
        images = [line for line in job if line.startswith("      image:")]
        if len(images) != 1 or re.fullmatch(
            r"      image: [a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
            r"@sha256:[a-f0-9]{64}",
            images[0],
        ) is None:
            raise ReleaseValidationError(
                "Each V1 execution job container must use one exact SHA-256 image digest."
            )


def _execution_workflow_migration_skeleton(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="strict")
    normalized: list[str] = []
    for line in text.splitlines():
        if line.startswith("    runs-on:"):
            normalized.append("    runs-on: <reviewed-runner>")
        elif line.startswith("    timeout-minutes:"):
            normalized.append("    timeout-minutes: <reviewed-timeout>")
        elif line.startswith("      image:"):
            normalized.append("      image: <reviewed-container>")
        else:
            normalized.append(line)
    return ("\n".join(normalized) + "\n").encode("utf-8")


def _validate_execution_migration_workflows(root: Path, base: str, head: str) -> None:
    for path in sorted(EXECUTION_WORKFLOW_TRIGGERS):
        base_bytes = _git_blob(root, base, path)
        head_bytes = _git_blob(root, head, path)
        _validate_execution_workflow(path, base_bytes)
        _validate_execution_workflow(path, head_bytes)
        if _execution_workflow_migration_skeleton(
            base_bytes
        ) != _execution_workflow_migration_skeleton(head_bytes):
            raise ReleaseValidationError(
                "A V1 execution workflow migration may change only its pinned runner, timeout, and container image scalar values."
            )


def execution_migration_identity(
    root: Path,
    base: str,
    head: str,
    changes: list[tuple[str, str]] | None = None,
) -> str:
    if not COMMIT_RE.fullmatch(base) or not COMMIT_RE.fullmatch(head):
        raise ReleaseValidationError(
            "Execution-migration identities require lowercase full Git SHAs."
        )
    selected_changes = changes if changes is not None else _changed_paths(root, base, head)
    material = ["runtime-v1-execution-migration-v1", base]
    for status, path in sorted(selected_changes, key=lambda item: item[1]):
        if status != "M" or path not in EVOLVABLE_V1_EXECUTION_PATHS:
            raise ReleaseValidationError(
                "A V1 execution migration may modify only the established execution closure."
            )
        material.extend((status, path, sha256_bytes(_git_blob(root, head, path))))
    if len(material) == 2:
        raise ReleaseValidationError("A V1 execution migration must change its execution closure.")
    _validate_execution_migration_workflows(root, base, head)
    return sha256_bytes(("\n".join(material) + "\n").encode("utf-8"))


def _git_path_exists(root: Path, revision: str, path: str) -> bool:
    result = _run_git(root, "cat-file", "-e", f"{revision}:{path}", check=False)
    return result.returncode == 0


def _git_path_identity(root: Path, revision: str, path: str) -> str | None:
    normalize_repo_path(path, "Git identity path")
    result = _run_git(root, "rev-parse", f"{revision}:{path}", check=False)
    if result.returncode != 0:
        return None
    identity = result.stdout.decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"[a-f0-9]{40,64}", identity):
        raise ReleaseValidationError("Git returned an invalid path object identity.")
    return identity


def _require_single_commit_on_base(root: Path, head: str, base: str, label: str) -> None:
    if _raw_commit_parents(root, head) != [base]:
        raise ReleaseValidationError(
            f"{label} must be one ordinary commit whose sole parent is the exact reviewed base."
        )


def _require_retained_purpose_ref(root: Path, branch: str, purpose_head: str) -> None:
    require_public_branch_name(branch)
    targets: list[str] = []
    for ref_name in (
        f"refs/heads/{branch}",
        f"refs/remotes/origin/{branch}",
    ):
        result = _run_git(
            root, "show-ref", "--verify", "--hash", ref_name, check=False
        )
        if result.returncode:
            continue
        try:
            target = result.stdout.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise ReleaseValidationError(
                "Git returned an invalid retained purpose-ref identity."
            ) from exc
        if not COMMIT_RE.fullmatch(target):
            raise ReleaseValidationError(
                "Git returned an invalid retained purpose-ref identity."
            )
        targets.append(target)
    if not targets or any(target != purpose_head for target in targets):
        raise ReleaseValidationError(
            "Protected history is not bound to its exact retained purpose branch identity."
        )


def _tag_object(root: Path, tag: str, tag_object: str | None = None) -> tuple[str, bytes]:
    revision = tag_object or f"refs/tags/{tag}"
    if tag_object is not None and not COMMIT_RE.fullmatch(tag_object):
        raise ReleaseValidationError("Unreferenced annotated tag object is not a lowercase full Git SHA.")
    if _git_text(root, "cat-file", "-t", revision) != "tag":
        raise ReleaseValidationError(f"Release tag '{tag}' must be an annotated tag object.")
    try:
        object_size = int(_git_text(root, "cat-file", "-s", revision))
    except ValueError as exc:
        raise ReleaseValidationError("Git returned an invalid annotated tag object size.") from exc
    if object_size > MAX_TAG_OBJECT_BYTES:
        raise ReleaseValidationError(
            f"Annotated release tag object exceeds the {MAX_TAG_OBJECT_BYTES}-byte public limit."
        )
    raw = _run_git(root, "cat-file", "tag", revision).stdout
    if len(raw) != object_size:
        raise ReleaseValidationError("Git returned inconsistent annotated tag object bytes.")
    computed_identity = hashlib.sha1(
        b"tag " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    if tag_object is not None and computed_identity != tag_object:
        raise ReleaseValidationError(
            "Unreferenced annotated tag bytes do not match the supplied Git object identity."
        )
    separator = raw.find(b"\n\n")
    if separator < 0:
        raise ReleaseValidationError(f"Annotated release tag '{tag}' has no message body.")
    headers = raw[:separator].split(b"\n")
    if len(headers) != 4 or not headers[3].startswith(b"tagger "):
        raise ReleaseValidationError(
            f"Annotated release tag '{tag}' must be one unsigned direct commit tag."
        )
    try:
        object_header = headers[0].decode("ascii")
        type_header = headers[1].decode("ascii")
        name_header = headers[2].decode("ascii")
        tagger_header = headers[3].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError(f"Annotated release tag '{tag}' has invalid headers.") from exc
    if not object_header.startswith("object ") or not COMMIT_RE.fullmatch(object_header[7:]):
        raise ReleaseValidationError(f"Annotated release tag '{tag}' has an invalid target object.")
    if type_header != "type commit":
        raise ReleaseValidationError(f"Annotated release tag '{tag}' must target a commit directly.")
    if name_header != f"tag {tag}":
        raise ReleaseValidationError(
            f"Annotated release tag ref '{tag}' does not match its internal tag name."
        )
    reject_private_strings({"tagger": tagger_header}, "Annotated release tag header")
    if RUNTIME_TAGGER_RE.fullmatch(tagger_header) is None:
        raise ReleaseValidationError(
            f"Annotated release tag '{tag}' does not use the exact runtime publisher tagger identity."
        )
    return object_header[7:], raw[separator + 2 :]


def _tag_message(root: Path, tag: str) -> bytes:
    return _tag_object(root, tag)[1]


def _validate_release_introduction_commit(root: Path, release_id: str, commit: str) -> None:
    parents = _raw_commit_parents(root, commit)
    if len(parents) != 2:
        raise ReleaseValidationError(
            "releaseArtifactCommit must be the normal two-parent merge that introduced the release."
        )
    first_parent, purpose_head = parents
    _require_single_commit_on_base(
        root, purpose_head, first_parent, "A reviewed release purpose branch"
    )

    expected = {
        ("A", release_document_path(release_id).as_posix()),
        ("A", consumer_catalog_path(release_id).as_posix()),
    }
    if set(_changed_paths(root, first_parent, purpose_head)) != expected:
        raise ReleaseValidationError(
            "Release merge purpose head did not add exactly its two immutable release artifacts."
        )
    merge_output = _git_text(
        root, "diff", "--name-status", "--no-renames", f"{first_parent}..{commit}"
    )
    merge_changes: set[tuple[str, str]] = set()
    for line in filter(None, merge_output.splitlines()):
        parts = line.split("\t")
        if len(parts) != 2:
            raise ReleaseValidationError(f"Unexpected release merge name-status record: '{line}'.")
        status, path = parts
        merge_changes.add((status, normalize_repo_path(path, "release merge path")))
    if merge_changes != expected:
        raise ReleaseValidationError(
            "releaseArtifactCommit is not the exact merge that introduced only the release artifacts."
        )
    for _status, path in expected:
        if _git_path_identity(root, commit, path) != _git_path_identity(root, purpose_head, path):
            raise ReleaseValidationError(
                "Release merge artifact bytes differ from the exact reviewed purpose commit."
            )

    release = validate_release_directory(root, release_id, commit)
    base_release_ids = _release_ids_at_revision(root, first_parent)
    if release_id in base_release_ids:
        raise ReleaseValidationError(
            "A release introduction merge cannot replace an existing immutable release."
        )
    if base_release_ids and release_sort_key(release_id) <= max(
        release_sort_key(item) for item in base_release_ids
    ):
        raise ReleaseValidationError(
            "A release introduction must use an ID later than every reviewed base release."
        )
    base_pointer = _read_pointer_from_revision(root, first_parent)
    if base_pointer is None:
        if base_release_ids:
            raise ReleaseValidationError(
                "A release introduction cannot proceed while prior releases remain unselected."
            )
        expected_predecessor = ""
        source = "none"
    else:
        expected_predecessor = str(base_pointer.get("releaseId", ""))
        source = expected_predecessor
        if base_release_ids:
            base_tip = max(base_release_ids, key=release_sort_key)
            if expected_predecessor != base_tip:
                raise ReleaseValidationError(
                    "A release introduction requires the reviewed pointer to select the existing immutable tip."
                )
    if release["predecessorReleaseId"] != expected_predecessor:
        raise ReleaseValidationError(
            "A release introduction predecessor does not match its exact reviewed base pointer."
        )
    release_bytes = _git_blob(
        root, purpose_head, release_document_path(release_id).as_posix()
    )
    catalog_bytes = _git_blob(
        root, purpose_head, consumer_catalog_path(release_id).as_posix()
    )
    operation_id = artifact_operation_identity(
        release_id, source, first_parent, release_bytes, catalog_bytes
    )
    branch = f"publish/artifacts/{release_id}/from/{source}/{operation_id}"
    _require_retained_purpose_ref(root, branch, purpose_head)


def _validate_release_at_commit(
    root: Path,
    pointer: dict[str, Any],
    release: dict[str, Any],
    state_revision: str | None = None,
) -> None:
    commit = pointer["releaseArtifactCommit"]
    release_path = release_document_path(pointer["releaseId"]).as_posix()
    catalog_path = pointer["catalogPath"]
    committed_release = _git_blob(root, commit, release_path)
    committed_catalog = _git_blob(root, commit, catalog_path)
    if state_revision is None:
        current_release = _root_path(root, PurePosixPath(release_path)).read_bytes()
        current_catalog = _root_path(root, PurePosixPath(catalog_path)).read_bytes()
    else:
        current_release = _git_blob(root, state_revision, release_path)
        current_catalog = _git_blob(root, state_revision, catalog_path)
    if committed_release != current_release or committed_catalog != current_catalog:
        raise ReleaseValidationError("Release artifacts differ from the exact release-artifact commit.")
    for schema_path in sorted(IMMUTABLE_V1_SCHEMA_PATHS):
        committed_schema = _git_blob(root, commit, schema_path)
        current_schema = _schema_authority_bytes(
            root, PurePosixPath(schema_path), state_revision
        )
        if committed_schema != current_schema:
            raise ReleaseValidationError(
                "Published V1 schema bytes differ from the exact release-artifact commit."
            )
    if sha256_bytes(committed_catalog) != pointer["catalogSha256"]:
        raise ReleaseValidationError("Pointer catalog SHA-256 does not match the commit-pinned catalog bytes.")
    if pointer["catalogSha256"] != release["consumerCatalog"]["sha256"]:
        raise ReleaseValidationError("Pointer and release catalog hashes do not agree.")


def validate_pointer(
    root: Path,
    pointer: dict[str, Any],
    pointer_bytes: bytes,
    main_commit: str,
    pointer_head: str | None,
    tag_object: str | None = None,
    state_revision: str | None = None,
) -> None:
    pointer_schema = _load_required_schema(
        root,
        POINTER_SCHEMA_PATH,
        "runtime-current-pointer-v1 schema",
        state_revision,
    )
    validate_schema(pointer, pointer_schema, "runtime current pointer")
    require_canonical_json(pointer_bytes, pointer, "runtime current pointer")
    reject_private_strings(pointer, "Runtime current pointer")
    release_id = pointer["releaseId"]
    require_release_id(release_id)
    expected_catalog_path = consumer_catalog_path(release_id).as_posix()
    if normalize_repo_path(pointer["catalogPath"], "catalogPath") != expected_catalog_path:
        raise ReleaseValidationError("Pointer catalogPath does not agree with releaseId.")
    commit = pointer["releaseArtifactCommit"]
    if not COMMIT_RE.fullmatch(commit):
        raise ReleaseValidationError("Pointer releaseArtifactCommit is not a lowercase full Git SHA.")
    if pointer_head is not None and commit == pointer_head:
        raise ReleaseValidationError("A current pointer cannot reference its own pointer-branch commit.")
    if not _is_raw_ancestor(root, commit, main_commit):
        raise ReleaseValidationError("Pointer releaseArtifactCommit is not already merged into reviewed main.")

    release = validate_release_directory(root, release_id, state_revision)
    if release["predecessorReleaseId"] != pointer["predecessorReleaseId"]:
        raise ReleaseValidationError("Pointer predecessor does not match immutable release evidence.")
    if release["consumerCatalog"]["schemaVersion"] != pointer["catalogSchemaVersion"]:
        raise ReleaseValidationError("Pointer catalog schema version does not match immutable release evidence.")
    if release["publicationAuthorizationIdentity"] != pointer["publicationAuthorizationIdentity"]:
        raise ReleaseValidationError(
            "Pointer publication authorization does not match immutable release evidence."
        )
    _validate_release_at_commit(root, pointer, release, state_revision)

    tagged_commit, message = _tag_object(root, release_id, tag_object)
    if tagged_commit != commit:
        raise ReleaseValidationError("Annotated release tag does not target releaseArtifactCommit.")
    _validate_release_introduction_commit(root, release_id, commit)
    if message != pointer_bytes:
        raise ReleaseValidationError("Current pointer must byte-match the canonical annotated-tag receipt.")


def _list_release_ids(root: Path, revision: str | None = None) -> list[str]:
    if revision is not None:
        release_ids: set[str] = set()
        prefix = f"{RELEASES_ROOT.as_posix()}/"
        for path in _git_tree_paths(root, revision):
            if path == RELEASES_ROOT.as_posix():
                raise ReleaseValidationError(
                    "manifests/releases must be a normal Git tree directory."
                )
            if not path.startswith(prefix):
                continue
            relative = path.removeprefix(prefix)
            if relative == "current.json":
                continue
            release_id = relative.split("/", 1)[0]
            if not RELEASE_ID_RE.fullmatch(release_id):
                raise ReleaseValidationError(
                    "The reviewed release namespace contains an unexpected path."
                )
            require_release_id(release_id)
            release_ids.add(release_id)
        return sorted(release_ids)

    releases = _root_path(root, RELEASES_ROOT)
    if not releases.exists():
        return []
    if not releases.is_dir() or releases.is_symlink():
        raise ReleaseValidationError("manifests/releases must be a normal directory.")
    release_ids: list[str] = []
    for child in releases.iterdir():
        if child.name == "current.json" and child.is_file() and not child.is_symlink():
            continue
        if not child.is_dir() or child.is_symlink() or not RELEASE_ID_RE.fullmatch(child.name):
            raise ReleaseValidationError("The reviewed release namespace contains an unexpected path.")
        release_ids.append(child.name)
    return sorted(release_ids)


def validate_release_graph(
    root: Path, revision: str | None = None
) -> dict[str, str]:
    releases = {
        release_id: validate_release_directory(root, release_id, revision)
        for release_id in _list_release_ids(root, revision)
    }
    predecessors = {
        release_id: str(release["predecessorReleaseId"])
        for release_id, release in releases.items()
    }
    if not predecessors:
        return {}
    for release_id, predecessor in predecessors.items():
        if predecessor and predecessor not in predecessors:
            raise ReleaseValidationError(
                f"Release '{release_id}' references missing predecessor '{predecessor}'."
            )
    asset_ids_by_release: dict[str, set[str]] = {}
    immutable_object_evidence: dict[str, dict[str, Any]] = {}
    immutable_digest_evidence: dict[str, dict[str, Any]] = {}
    for release_id in sorted(releases, key=release_sort_key):
        catalog_path = consumer_catalog_path(release_id)
        if revision is None:
            catalog = load_json_file(
                _root_path(root, catalog_path), catalog_path.as_posix()
            )
        else:
            catalog = load_json_bytes(
                _git_blob(root, revision, catalog_path.as_posix()),
                catalog_path.as_posix(),
            )
        asset_ids_by_release[release_id] = {
            str(asset["assetId"]) for asset in catalog["assets"]
        }
        for asset in catalog["assets"]:
            for variant in asset["variants"]:
                evidence = {
                    "bytes": variant["bytes"],
                    "format": variant["format"],
                    "height": variant["height"],
                    "mimeType": variant["mimeType"],
                    "objectKey": variant["objectKey"],
                    "sha256": variant["sha256"],
                    "url": variant["url"],
                    "width": variant["width"],
                }
                prior = immutable_object_evidence.get(variant["objectKey"])
                if prior is not None and prior != evidence:
                    raise ReleaseValidationError(
                        "Reviewed releases disagree about immutable object evidence."
                    )
                prior_digest = immutable_digest_evidence.get(variant["sha256"])
                if prior_digest is not None and prior_digest != evidence:
                    raise ReleaseValidationError(
                        "Reviewed releases assign multiple identities to one immutable SHA-256 digest."
                    )
                immutable_object_evidence[variant["objectKey"]] = evidence
                immutable_digest_evidence[variant["sha256"]] = evidence
    for release_id, predecessor in predecessors.items():
        if not predecessor:
            continue
        missing = asset_ids_by_release[predecessor] - asset_ids_by_release[release_id]
        if missing:
            raise ReleaseValidationError(
                f"Release '{release_id}' omits {len(missing)} stable asset ID(s) from its predecessor; "
                "retired IDs must remain represented by a retained, normally deprecated record."
            )
    for start in predecessors:
        seen: set[str] = set()
        current = start
        while current:
            if current in seen:
                raise ReleaseValidationError(
                    f"Immutable release predecessor graph contains a cycle reachable from '{start}'."
                )
            seen.add(current)
            current = predecessors[current]
    for release_id, predecessor in predecessors.items():
        if predecessor and release_sort_key(predecessor) >= release_sort_key(release_id):
            raise ReleaseValidationError(
                f"Release '{release_id}' predecessor must be chronologically earlier."
            )
    children: dict[str, str] = {}
    for release_id, predecessor in predecessors.items():
        if not predecessor:
            continue
        prior_child = children.get(predecessor)
        if prior_child is not None:
            raise ReleaseValidationError(
                "The immutable release graph must be linear; "
                f"'{predecessor}' cannot have sibling successors '{prior_child}' and '{release_id}'."
            )
        children[predecessor] = release_id
    roots = [release_id for release_id, predecessor in predecessors.items() if predecessor == ""]
    if len(roots) != 1:
        raise ReleaseValidationError("The immutable release graph must have exactly one root release.")
    tips = [release_id for release_id in predecessors if release_id not in children]
    if len(tips) != 1:
        raise ReleaseValidationError("The immutable release graph must have exactly one tip release.")
    return predecessors


def _is_strict_ancestor(predecessors: dict[str, str], ancestor: str, descendant: str) -> bool:
    current = predecessors.get(descendant, "")
    while current:
        if current == ancestor:
            return True
        current = predecessors.get(current, "")
    return False


def _validate_existing_runtime_tags(root: Path, main_commit: str) -> None:
    tag_lines = _git_text(root, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags")
    tags = tag_lines.splitlines()
    if len(tags) > MAX_REF_COUNT:
        raise ReleaseValidationError(
            f"Runtime tag validation cannot inspect more than {MAX_REF_COUNT} tag refs."
        )
    for tag in tags:
        # This retained validator owns only the immutable V1 namespace.  The
        # evolvable dispatcher classifies every tag before routing recognized
        # namespaces here; keeping this filter version-scoped lets a future
        # dispatcher add a disjoint namespace without rewriting V1 authority.
        if not tag.startswith("runtime-v1-"):
            continue
        require_release_id(tag, "release tag")
        message = _tag_message(root, tag)
        pointer = load_json_bytes(message, f"annotated tag {tag}")
        if not isinstance(pointer, dict):
            raise ReleaseValidationError("Annotated release tag receipt must be a JSON object.")
        if pointer.get("releaseId") != tag:
            raise ReleaseValidationError(f"Annotated tag '{tag}' message identifies a different release.")
        validate_pointer(
            root,
            pointer,
            message,
            main_commit,
            pointer_head=None,
            state_revision=main_commit,
        )


def validate_repository(
    root: Path, main_commit: str, allow_unmerged_tip: bool = False
) -> None:
    if not COMMIT_RE.fullmatch(main_commit):
        raise ReleaseValidationError(
            "Repository validation requires one lowercase full main commit SHA."
        )
    _require_trusted_git_repository_state(root)
    _raw_commit_parents(root, main_commit)
    _git_tree_paths(root, main_commit)
    validate_release_graph(root, main_commit)
    if _git_path_exists(root, main_commit, CURRENT_POINTER_PATH.as_posix()):
        pointer_bytes = _git_blob(
            root, main_commit, CURRENT_POINTER_PATH.as_posix()
        )
        pointer = load_json_bytes(pointer_bytes, CURRENT_POINTER_PATH.as_posix())
        validate_pointer(
            root,
            pointer,
            pointer_bytes,
            main_commit,
            pointer_head=main_commit,
            state_revision=main_commit,
        )
    _validate_reviewed_main_history(
        root, main_commit, allow_unmerged_tip=allow_unmerged_tip
    )
    _validate_existing_runtime_tags(root, main_commit)


def _changed_paths(root: Path, base: str, head: str) -> list[tuple[str, str]]:
    return _diff_paths(root, f"{base}..{head}")


def _diff_paths(root: Path, *revisions: str) -> list[tuple[str, str]]:
    output = _run_git(
        root, "diff", "--name-status", "--no-renames", "-z", *revisions
    ).stdout
    fields = [field for field in output.split(b"\0") if field]
    if len(fields) % 2:
        raise ReleaseValidationError("Git returned an incomplete name-status record.")
    changes: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii", errors="strict")
            path = fields[index + 1].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReleaseValidationError("Git returned a non-UTF-8 changed path record.") from exc
        if not re.fullmatch(r"[A-Z]", status):
            raise ReleaseValidationError("Git returned an unexpected name-status record.")
        changes.append((status, normalize_repo_path(path, "changed path")))
    return changes


def _protected_history_changes(
    root: Path, base: str, head: str, v1_authority_locked: bool
) -> list[tuple[str, str, str]]:
    output = _git_text(
        root, "rev-list", "--reverse", "--topo-order", "--parents", f"{base}..{head}"
    )
    findings: list[tuple[str, str, str]] = []
    for line in filter(None, output.splitlines()):
        parts = line.split()
        commit = parts[0]
        parents = _raw_commit_parents(root, commit)
        if not parents:
            raise ReleaseValidationError("Candidate history contains an unexplained root commit.")
        protected_paths: set[str] = set()
        for parent in parents:
            for _status, path in _diff_paths(root, parent, commit):
                reject_release_namespace_alias(path)
                if path.startswith("manifests/") or (
                    v1_authority_locked
                    and path
                    in (IMMUTABLE_V1_AUTHORITY_PATHS | EVOLVABLE_V1_EXECUTION_PATHS)
                ) or (
                    v1_authority_locked and path.startswith(V1_WHEELHOUSE_PREFIX)
                ):
                    protected_paths.add(path)
        for path in sorted(protected_paths):
            if len(parents) > 1:
                merged_identity = _git_path_identity(root, commit, path)
                if _git_path_identity(root, base, path) == merged_identity:
                    continue
            findings.append((commit, parents[0], path))
    return findings


def _read_pointer_from_revision(root: Path, revision: str) -> dict[str, Any] | None:
    result = _run_git(root, "show", f"{revision}:{CURRENT_POINTER_PATH.as_posix()}", check=False)
    if result.returncode != 0:
        return None
    value = load_json_bytes(result.stdout, f"{revision}:{CURRENT_POINTER_PATH.as_posix()}")
    if not isinstance(value, dict):
        raise ReleaseValidationError("Base current pointer is not a JSON object.")
    return value


def _validate_pointer_introduction_commit(root: Path, commit: str) -> None:
    parents = _raw_commit_parents(root, commit)
    if len(parents) != 2:
        raise ReleaseValidationError(
            "Every current-pointer transition must be its normal two-parent purpose merge."
        )
    first_parent, purpose_head = parents
    _require_single_commit_on_base(
        root, purpose_head, first_parent, "A reviewed pointer purpose branch"
    )
    pointer_path = CURRENT_POINTER_PATH.as_posix()
    purpose_changes = _changed_paths(root, first_parent, purpose_head)
    merge_changes = _changed_paths(root, first_parent, commit)
    allowed = (["A", pointer_path], ["M", pointer_path])
    if list(map(list, purpose_changes)) not in ([allowed[0]], [allowed[1]]):
        raise ReleaseValidationError(
            "A pointer purpose head must add or modify only the reviewed current pointer."
        )
    if list(map(list, merge_changes)) != list(map(list, purpose_changes)):
        raise ReleaseValidationError(
            "A pointer merge must reproduce only its exact reviewed pointer transition."
        )
    if _git_path_identity(root, commit, pointer_path) != _git_path_identity(
        root, purpose_head, pointer_path
    ):
        raise ReleaseValidationError(
            "Pointer merge bytes differ from the exact reviewed purpose commit."
        )

    pointer_bytes = _git_blob(root, commit, pointer_path)
    pointer = load_json_bytes(pointer_bytes, pointer_path)
    if not isinstance(pointer, dict):
        raise ReleaseValidationError("Runtime current pointer must be a JSON object.")
    base_pointer = _read_pointer_from_revision(root, first_parent)
    source = "none" if base_pointer is None else str(base_pointer.get("releaseId", ""))
    target = str(pointer.get("releaseId", ""))
    predecessors = validate_release_graph(root, commit)
    operations: list[str] = []
    expected_predecessor = "" if source == "none" else source
    if predecessors.get(target) == expected_predecessor:
        operations.append("select")
    if source != "none" and _is_strict_ancestor(predecessors, target, source):
        operations.append("rollback")
    if source != "none" and _is_strict_ancestor(predecessors, source, target):
        operations.append("restore")
    if len(operations) != 1:
        raise ReleaseValidationError(
            "A protected current-pointer transition has no single permitted graph direction."
        )
    operation = operations[0]
    operation_id = pointer_operation_identity(
        operation, target, source, first_parent, pointer_bytes
    )
    branch = f"publish/pointer/{operation}/{target}/from/{source}/{operation_id}"
    _require_retained_purpose_ref(root, branch, purpose_head)
    validate_pointer(
        root,
        pointer,
        pointer_bytes,
        first_parent,
        pointer_head=purpose_head,
        state_revision=commit,
    )


def _first_parent_history(root: Path, head: str) -> list[str]:
    history: list[str] = []
    current = head
    while True:
        history.append(current)
        if len(history) > MAX_REF_COUNT:
            raise ReleaseValidationError(
                f"Protected history validation cannot inspect more than {MAX_REF_COUNT} commits."
            )
        parents = _raw_commit_parents(root, current)
        if not parents:
            break
        current = parents[0]
    history.reverse()
    return history


def _validate_reviewed_main_history(
    root: Path, main_commit: str, allow_unmerged_tip: bool = False
) -> None:
    history = _first_parent_history(root, main_commit)
    expected_revision = main_commit
    if allow_unmerged_tip:
        if len(history) < 2:
            raise ReleaseValidationError(
                "Candidate repository validation requires a non-root reviewed base."
            )
        expected_revision = _raw_commit_parents(root, main_commit)[0]
        history = history[:-1]

    introduced_releases: set[str] = set()
    release_prefix = f"{RELEASES_ROOT.as_posix()}/"
    for commit in history:
        parents = _raw_commit_parents(root, commit)
        if not parents:
            continue
        first_parent = parents[0]
        protected = [
            (status, path)
            for status, path in _changed_paths(root, first_parent, commit)
            if path == CURRENT_POINTER_PATH.as_posix() or path.startswith(release_prefix)
        ]
        if not protected:
            continue
        if any(path == CURRENT_POINTER_PATH.as_posix() for _status, path in protected):
            if len(protected) != 1:
                raise ReleaseValidationError(
                    "A protected merge cannot combine a current-pointer transition with release artifacts."
                )
            _validate_pointer_introduction_commit(root, commit)
            continue
        release_ids: set[str] = set()
        for status, path in protected:
            relative = path.removeprefix(release_prefix)
            release_id, separator, leaf = relative.partition("/")
            if (
                status != "A"
                or not separator
                or leaf not in {"release.json", "consumer-catalog.json"}
            ):
                raise ReleaseValidationError(
                    "Protected release history contains a modification outside one immutable introduction."
                )
            require_release_id(release_id, "protected release history")
            release_ids.add(release_id)
        if len(release_ids) != 1 or len(protected) != 2:
            raise ReleaseValidationError(
                "Each protected release history transition must introduce exactly one release pair."
            )
        release_id = next(iter(release_ids))
        _validate_release_introduction_commit(root, release_id, commit)
        if release_id in introduced_releases:
            raise ReleaseValidationError(
                "Protected history introduces one immutable release more than once."
            )
        introduced_releases.add(release_id)

    expected_releases = set(_list_release_ids(root, expected_revision))
    if introduced_releases != expected_releases:
        raise ReleaseValidationError(
            "Reviewed release directories do not match exact protected merge provenance."
        )


def validate_pull_request(root: Path, base: str, head: str, branch: str) -> None:
    if not COMMIT_RE.fullmatch(base) or not COMMIT_RE.fullmatch(head):
        raise ReleaseValidationError("Pull-request base and head must be lowercase full Git SHAs.")
    require_public_branch_name(branch)
    _require_trusted_git_repository_state(root)
    if not _is_raw_ancestor(root, base, head):
        raise ReleaseValidationError("Pull-request head must descend from the exact reviewed base commit.")
    changes = _changed_paths(root, base, head)
    for _, path in changes:
        reject_release_namespace_alias(path)
    artifact_match = ARTIFACT_BRANCH_RE.fullmatch(branch)
    pointer_match = POINTER_BRANCH_RE.fullmatch(branch)
    execution_migration_match = EXECUTION_MIGRATION_BRANCH_RE.fullmatch(branch)
    base_release_ids = _release_ids_at_revision(root, base)
    v1_authority_locked = bool(base_release_ids) or _git_path_exists(
        root, base, V1_ACTIVATION_MARKER_PATH
    )
    if artifact_match or pointer_match:
        _require_single_commit_on_base(
            root, head, base, "A publisher purpose branch"
        )
    elif execution_migration_match:
        if not v1_authority_locked:
            raise ReleaseValidationError(
                "The V1 execution-migration lane exists only after V1 safeguards are activated."
            )
        _require_single_commit_on_base(
            root, head, base, "A V1 execution-migration branch"
        )
        expected_operation_id = execution_migration_identity(root, base, head, changes)
        if execution_migration_match.group("operation_id") != expected_operation_id:
            raise ReleaseValidationError(
                "V1 execution-migration branch identity does not match its exact reviewed intent."
            )
        return
    else:
        history_changes = _protected_history_changes(
            root, base, head, v1_authority_locked=v1_authority_locked
        )
        if any(
            path in IMMUTABLE_V1_AUTHORITY_PATHS
            or path.startswith(V1_WHEELHOUSE_PREFIX)
            for _, _, path in history_changes
        ):
            raise ReleaseValidationError(
                "Once V1 authority is activated, its schema and semantic validator authority are immutable in place; add a versioned authority."
            )
        if any(path in EVOLVABLE_V1_EXECUTION_PATHS for _, _, path in history_changes):
            raise ReleaseValidationError(
                "Once V1 authority is activated, execution-closure changes require the exact execution-migration lane and private migration authorization."
            )
        if history_changes:
            raise ReleaseValidationError(
                "Only exact publisher purpose branches may change a reviewed runtime manifest in reachable candidate history."
            )
    protected_changes = [
        path
        for _, path in changes
        if path.startswith("manifests/")
    ]

    if artifact_match:
        release_id = artifact_match.group("release")
        source_release_id = artifact_match.group("source")
        expected = {
            release_document_path(release_id).as_posix(),
            consumer_catalog_path(release_id).as_posix(),
        }
        if {(status, path) for status, path in changes} != {("A", path) for path in expected}:
            raise ReleaseValidationError(
                "An artifact PR must add exactly release.json and consumer-catalog.json in its matching release directory."
            )
        if _git_path_exists(root, base, release_directory_path(release_id).as_posix()):
            raise ReleaseValidationError("An artifact PR cannot replace or extend an existing immutable release directory.")
        release = validate_release_directory(root, release_id, head)
        base_pointer = _read_pointer_from_revision(root, base)
        if base_release_ids and release_sort_key(release_id) <= max(
            (release_sort_key(item) for item in base_release_ids)
        ):
            raise ReleaseValidationError(
                "A newly added release ID must be later than every immutable release in the reviewed base."
            )
        if base_pointer is None:
            if base_release_ids:
                raise ReleaseValidationError("A new release cannot proceed while prior releases exist without a reviewed current pointer.")
            expected_predecessor = ""
        else:
            expected_predecessor = str(base_pointer.get("releaseId", ""))
            if base_release_ids:
                base_tip = max(base_release_ids, key=release_sort_key)
                if expected_predecessor != base_tip:
                    raise ReleaseValidationError(
                        "A new release cannot proceed until the reviewed current pointer selects "
                        "the existing immutable release tip."
                    )
        if release["predecessorReleaseId"] != expected_predecessor:
            raise ReleaseValidationError("New release predecessor must match the reviewed base current pointer.")
        expected_source = "none" if base_pointer is None else expected_predecessor
        if source_release_id != expected_source:
            raise ReleaseValidationError(
                "Artifact branch source does not match the exact reviewed base current pointer."
            )
        release_bytes = _git_blob(
            root, head, release_document_path(release_id).as_posix()
        )
        catalog_bytes = _git_blob(
            root, head, consumer_catalog_path(release_id).as_posix()
        )
        expected_operation_id = artifact_operation_identity(
            release_id,
            source_release_id,
            base,
            release_bytes,
            catalog_bytes,
        )
        if artifact_match.group("operation_id") != expected_operation_id:
            raise ReleaseValidationError(
                "Artifact branch operation identity does not match its canonical intent."
            )
        validate_release_graph(root, head)
        return

    if pointer_match:
        operation = pointer_match.group("operation")
        release_id = pointer_match.group("target")
        source_release_id = pointer_match.group("source")
        if changes not in ([('A', CURRENT_POINTER_PATH.as_posix())], [('M', CURRENT_POINTER_PATH.as_posix())]):
            raise ReleaseValidationError("A pointer PR may add or modify only manifests/releases/current.json.")
        pointer_bytes = _git_blob(root, head, CURRENT_POINTER_PATH.as_posix())
        pointer = load_json_bytes(pointer_bytes, CURRENT_POINTER_PATH.as_posix())
        if pointer.get("releaseId") != release_id:
            raise ReleaseValidationError("Pointer branch target and current pointer releaseId do not agree.")
        expected_operation_id = pointer_operation_identity(
            operation, release_id, source_release_id, base, pointer_bytes
        )
        if pointer_match.group("operation_id") != expected_operation_id:
            raise ReleaseValidationError("Pointer branch operation identity does not match its canonical intent.")
        base_pointer = _read_pointer_from_revision(root, base)
        expected_source = "none" if base_pointer is None else str(base_pointer.get("releaseId", ""))
        if source_release_id != expected_source:
            raise ReleaseValidationError("Pointer branch source does not match the exact reviewed base current pointer.")
        validate_pointer(
            root,
            pointer,
            pointer_bytes,
            base,
            pointer_head=head,
            state_revision=head,
        )
        predecessors = validate_release_graph(root, head)
        if operation == "select":
            expected_predecessor = "" if source_release_id == "none" else source_release_id
            if predecessors.get(release_id) != expected_predecessor:
                raise ReleaseValidationError(
                    "A select operation must choose the root first release or a direct next release."
                )
        elif operation == "rollback":
            if source_release_id == "none" or not _is_strict_ancestor(
                predecessors, release_id, source_release_id
            ):
                raise ReleaseValidationError(
                    "A rollback target must be a strict ancestor of the reviewed source release."
                )
        elif source_release_id == "none" or not _is_strict_ancestor(
            predecessors, source_release_id, release_id
        ):
            raise ReleaseValidationError(
                "A restore target must be a strict descendant of the reviewed source release."
            )
        return

    if protected_changes:
        raise ReleaseValidationError(
            "Only exact publish/artifacts or publish/pointer purpose branches may change reviewed runtime manifests."
        )
    if branch.startswith("publish/artifacts/") or branch.startswith("publish/pointer/"):
        raise ReleaseValidationError("Malformed publisher purpose branch.")


def validate_tag(root: Path, tag: str, main_commit: str) -> None:
    require_release_id(tag, "release tag")
    _require_trusted_git_repository_state(root)
    resolved_main = _resolve_commit_identity(root, main_commit)
    _git_tree_paths(root, tag)
    validate_release_graph(root, resolved_main)
    _validate_reviewed_main_history(root, resolved_main)
    _validate_existing_runtime_tags(root, resolved_main)
    message = _tag_message(root, tag)
    pointer = load_json_bytes(message, f"annotated tag {tag}")
    if not isinstance(pointer, dict):
        raise ReleaseValidationError("Annotated release tag receipt must be a JSON object.")
    if pointer.get("releaseId") != tag:
        raise ReleaseValidationError("Annotated tag name and receipt releaseId do not agree.")
    validate_pointer(
        root,
        pointer,
        message,
        resolved_main,
        pointer_head=None,
        state_revision=resolved_main,
    )


def _require_unreferenced_tag_object(root: Path, tag_object: str) -> None:
    direct_objects = _git_text(root, "for-each-ref", "--format=%(objectname)").splitlines()
    if len(direct_objects) > MAX_REF_COUNT:
        raise ReleaseValidationError(
            f"Tag-object preflight cannot inspect more than {MAX_REF_COUNT} Git refs."
        )
    for direct_object in direct_objects:
        current = direct_object
        for _depth in range(MAX_TAG_CHAIN_DEPTH):
            if current == tag_object:
                raise ReleaseValidationError(
                    "Tag-object preflight requires an object with no existing Git ref."
                )
            object_type = _git_text(root, "cat-file", "-t", current)
            if object_type != "tag":
                break
            try:
                object_size = int(_git_text(root, "cat-file", "-s", current))
            except ValueError as exc:
                raise ReleaseValidationError(
                    "Git returned an invalid referenced tag object size."
                ) from exc
            if object_size > MAX_TAG_OBJECT_BYTES:
                raise ReleaseValidationError(
                    "Tag-object preflight encountered an oversized referenced tag object."
                )
            raw = _run_git(root, "cat-file", "tag", current).stdout
            if len(raw) != object_size:
                raise ReleaseValidationError(
                    "Git returned inconsistent referenced tag object bytes."
                )
            first_header = raw.split(b"\n", 1)[0]
            match = re.fullmatch(br"object ([a-f0-9]{40})", first_header)
            if match is None:
                raise ReleaseValidationError(
                    "Tag-object preflight encountered an invalid referenced tag chain."
                )
            current = match.group(1).decode("ascii")
        else:
            raise ReleaseValidationError(
                f"Tag-object preflight cannot inspect a tag chain deeper than {MAX_TAG_CHAIN_DEPTH}."
            )


def validate_unreferenced_tag_object(
    root: Path, tag_object: str, tag: str, main_commit: str
) -> None:
    require_release_id(tag, "release tag")
    if not COMMIT_RE.fullmatch(tag_object):
        raise ReleaseValidationError("Unreferenced annotated tag object must be a lowercase full Git SHA.")
    if not COMMIT_RE.fullmatch(main_commit):
        raise ReleaseValidationError("Tag-object main identity must be a lowercase full Git SHA.")
    _require_trusted_git_repository_state(root)
    if _git_text(root, "rev-parse", "HEAD") != main_commit:
        raise ReleaseValidationError(
            "Unreferenced tag-object validation requires HEAD at the exact reviewed main commit."
        )
    if _run_git(
        root, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout:
        raise ReleaseValidationError(
            "Unreferenced tag-object validation requires a clean index and working tree."
        )
    intended_ref_name = f"refs/tags/{tag}"
    if _run_git(
        root,
        "check-ref-format",
        intended_ref_name,
        check=False,
    ).returncode != 0:
        raise ReleaseValidationError(
            "Tag-object preflight requires one valid intended release ref name."
        )
    occupied_names = _git_text(
        root,
        "for-each-ref",
        "--format=%(refname)",
        intended_ref_name,
    ).splitlines()
    if any(
        value == intended_ref_name or value.startswith(f"{intended_ref_name}/")
        for value in occupied_names
    ):
        raise ReleaseValidationError(
            "Tag-object preflight requires the intended release tag namespace to be unused."
        )
    _require_unreferenced_tag_object(root, tag_object)
    _git_tree_paths(root, tag_object)
    validate_release_graph(root, main_commit)
    _validate_reviewed_main_history(root, main_commit)
    _validate_existing_runtime_tags(root, main_commit)
    tagged_commit, message = _tag_object(root, tag, tag_object)
    pointer = load_json_bytes(message, f"unreferenced annotated tag object for {tag}")
    if not isinstance(pointer, dict):
        raise ReleaseValidationError("Unreferenced annotated tag receipt must be a JSON object.")
    if pointer.get("releaseId") != tag:
        raise ReleaseValidationError("Annotated tag name and receipt releaseId do not agree.")
    validate_pointer(
        root,
        pointer,
        message,
        main_commit,
        pointer_head=None,
        tag_object=tag_object,
        state_revision=main_commit,
    )
    if tagged_commit != pointer["releaseArtifactCommit"]:
        raise ReleaseValidationError("Unreferenced annotated tag object targets the wrong release commit.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--schema-root",
        type=Path,
        help="Read immutable V1 schemas from this separately trusted checkout.",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--repository", action="store_true")
    modes.add_argument("--candidate-repository", action="store_true")
    modes.add_argument("--pull-request", action="store_true")
    modes.add_argument("--tag")
    modes.add_argument("--tag-object")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--branch")
    parser.add_argument("--main")
    parser.add_argument("--tag-name")
    return parser.parse_args()


def main() -> int:
    global _SCHEMA_AUTHORITY_ROOT, _SCHEMA_AUTHORITY_REVISION
    args = parse_args()
    try:
        _SCHEMA_AUTHORITY_ROOT = None
        _SCHEMA_AUTHORITY_REVISION = None
        root = args.root.resolve()
        if args.schema_root is not None:
            if not (args.pull_request or args.candidate_repository):
                raise ReleaseValidationError(
                    "A separate V1 schema root is permitted only in trusted-base pull-request mode."
                )
            if not args.base or not COMMIT_RE.fullmatch(args.base):
                raise ReleaseValidationError(
                    "Trusted-base schema authority requires the exact pull-request base commit."
                )
            schema_root_input = (
                args.schema_root
                if args.schema_root.is_absolute()
                else Path.cwd() / args.schema_root
            )
            if not schema_root_input.is_dir() or schema_root_input.is_symlink():
                raise ReleaseValidationError(
                    "The separately trusted V1 schema root must be a normal directory."
                )
            _SCHEMA_AUTHORITY_ROOT = schema_root_input.resolve()
            _require_exact_clean_checkout(
                _SCHEMA_AUTHORITY_ROOT,
                args.base,
                "The separately trusted V1 schema root",
            )
            _SCHEMA_AUTHORITY_REVISION = args.base
        if args.pull_request:
            if not args.base or not args.head or not args.branch:
                raise ReleaseValidationError("Pull-request mode requires --base, --head, and --branch.")
            validate_pull_request(root, args.base, args.head, args.branch)
            print("Reviewed release PR lane passed.")
        elif args.candidate_repository:
            if (
                not args.base
                or not args.head
                or not args.branch
                or not args.main
                or args.head != args.main
            ):
                raise ReleaseValidationError(
                    "Candidate repository mode requires matching --head/--main plus --base and --branch."
                )
            _require_exact_clean_checkout(root, args.main, "Candidate repository mode")
            validate_pull_request(root, args.base, args.head, args.branch)
            # The trusted-base lane above first proves the candidate schema
            # paths byte-immutable. Repository validation then evaluates the
            # candidate-tree copies rather than retaining an external schema
            # authority outside its narrowly scoped PR check.
            _SCHEMA_AUTHORITY_ROOT = None
            _SCHEMA_AUTHORITY_REVISION = None
            validate_repository(root, args.main, allow_unmerged_tip=True)
            print("Reviewed candidate runtime repository state passed.")
        elif args.tag:
            if not args.main:
                raise ReleaseValidationError("Tag mode requires --main.")
            validate_tag(root, args.tag, args.main)
            print(f"Annotated runtime release tag passed: {args.tag}.")
        elif args.tag_object:
            if not args.main or not args.tag_name:
                raise ReleaseValidationError(
                    "Unreferenced tag-object mode requires --tag-name and --main."
                )
            validate_unreferenced_tag_object(root, args.tag_object, args.tag_name, args.main)
            print(f"Unreferenced annotated runtime tag object passed: {args.tag_name}.")
        else:
            if not args.main:
                raise ReleaseValidationError(
                    "Repository mode requires an exact lowercase full --main commit SHA."
                )
            _require_exact_clean_checkout(root, args.main, "Repository mode")
            validate_repository(root, args.main)
            print("Reviewed runtime release repository state passed.")
    except (ReleaseValidationError, OSError, UnicodeError, ValueError):
        print(
            "Reviewed runtime release validation FAILED; untrusted detail was withheld.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
