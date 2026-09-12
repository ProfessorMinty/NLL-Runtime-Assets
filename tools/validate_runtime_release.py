"""Classify global runtime namespaces, then invoke retained V1 authority."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_V1_PATH = Path(__file__).resolve().with_name("validate_runtime_release_v1.py")
_V1_SPEC = importlib.util.spec_from_file_location(
    "validate_runtime_release_v1", _V1_PATH
)
if _V1_SPEC is None or _V1_SPEC.loader is None:
    raise RuntimeError("The retained V1 validation authority could not be loaded.")
_v1 = importlib.util.module_from_spec(_V1_SPEC)
sys.modules[_V1_SPEC.name] = _v1
_V1_SPEC.loader.exec_module(_v1)

# Preserve the compatibility import surface without adding the script directory
# (or any candidate-controlled location) to sys.path.  This also keeps exact
# `python -P tools/validate_runtime_release.py` invocations functional.
for _name in dir(_v1):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_v1, _name)
_validate_runtime_objects = _v1._validate_runtime_objects


def validate_global_tag_namespace(root: Path) -> None:
    """Reject every tag not owned by the currently recognized V1 namespace."""

    root = root.resolve()
    _v1._require_trusted_git_repository_state(root)
    tag_lines = _v1._git_text(
        root, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags"
    )
    tags = tag_lines.splitlines()
    if len(tags) > _v1.MAX_REF_COUNT:
        raise _v1.ReleaseValidationError(
            f"Global tag validation cannot inspect more than {_v1.MAX_REF_COUNT} refs."
        )
    for tag in tags:
        try:
            _v1.require_release_id(tag, "release tag")
        except _v1.ReleaseValidationError as exc:
            raise _v1.ReleaseValidationError(
                "Git contains a tag outside the recognized runtime namespace."
            ) from exc


def validate_repository(
    root: Path, main_commit: str, *, allow_unmerged_tip: bool = False
) -> None:
    validate_global_tag_namespace(root)
    _v1.validate_repository(
        root, main_commit, allow_unmerged_tip=allow_unmerged_tip
    )


def validate_tag(root: Path, tag: str, main_commit: str) -> None:
    validate_global_tag_namespace(root)
    _v1.validate_tag(root, tag, main_commit)


def validate_unreferenced_tag_object(
    root: Path, tag_object: str, tag_name: str, main_commit: str
) -> None:
    validate_global_tag_namespace(root)
    _v1.validate_unreferenced_tag_object(root, tag_object, tag_name, main_commit)


def main() -> int:
    args = _v1.parse_args()
    try:
        if args.repository or args.candidate_repository or args.tag or args.tag_object:
            validate_global_tag_namespace(args.root)
    except (_v1.ReleaseValidationError, OSError, UnicodeError, ValueError):
        print(
            "Reviewed runtime release validation FAILED; untrusted detail was withheld.",
            file=sys.stderr,
        )
        return 1
    return _v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
