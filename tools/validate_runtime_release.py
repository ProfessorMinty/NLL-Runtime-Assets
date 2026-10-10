"""V1.1 dispatcher: retained V1 contracts with reviewed pointer-intent resolution.

The original V1 file remains byte-immutable. Only history's pointer classifier is
superseded: graph direction constrains intent, while the exact retained purpose
ref determines select versus restore. Neither history nor tag checks are skipped.
"""

from __future__ import annotations

import importlib.util
import sys
from types import FunctionType
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

POINTER_HISTORY_AUTHORITY_VERSION = "1.1"


def _validate_pointer_introduction_commit_v1_1(root: Path, commit: str) -> None:
    parents = _v1._raw_commit_parents(root, commit)
    if len(parents) != 2:
        raise _v1.ReleaseValidationError(
            "Every current-pointer transition must be its normal two-parent purpose merge."
        )
    first_parent, purpose_head = parents
    _v1._require_single_commit_on_base(
        root, purpose_head, first_parent, "A reviewed pointer purpose branch"
    )
    pointer_path = _v1.CURRENT_POINTER_PATH.as_posix()
    purpose_changes = _v1._changed_paths(root, first_parent, purpose_head)
    merge_changes = _v1._changed_paths(root, first_parent, commit)
    allowed = (["A", pointer_path], ["M", pointer_path])
    if list(map(list, purpose_changes)) not in ([allowed[0]], [allowed[1]]):
        raise _v1.ReleaseValidationError(
            "A pointer purpose head must add or modify only the reviewed current pointer."
        )
    if list(map(list, merge_changes)) != list(map(list, purpose_changes)):
        raise _v1.ReleaseValidationError(
            "A pointer merge must reproduce only its exact reviewed pointer transition."
        )
    if _v1._git_path_identity(root, commit, pointer_path) != _v1._git_path_identity(
        root, purpose_head, pointer_path
    ):
        raise _v1.ReleaseValidationError(
            "Pointer merge bytes differ from the exact reviewed purpose commit."
        )
    pointer_bytes = _v1._git_blob(root, commit, pointer_path)
    pointer = _v1.load_json_bytes(pointer_bytes, pointer_path)
    if not isinstance(pointer, dict):
        raise _v1.ReleaseValidationError("Runtime current pointer must be a JSON object.")
    base_pointer = _v1._read_pointer_from_revision(root, first_parent)
    source = "none" if base_pointer is None else str(base_pointer.get("releaseId", ""))
    target = str(pointer.get("releaseId", ""))
    predecessors = _v1.validate_release_graph(root, commit)
    permitted: list[str] = []
    if predecessors.get(target) == ("" if source == "none" else source):
        permitted.append("select")
    if source != "none" and _v1._is_strict_ancestor(predecessors, target, source):
        permitted.append("rollback")
    if source != "none" and _v1._is_strict_ancestor(predecessors, source, target):
        permitted.append("restore")

    # An immediate successor is legitimately both graph-selectable and graph-
    # restorable. Require exactly one *reviewed intent*, not one graph predicate.
    # Existing refs with a wrong target are errors, not ignored alternatives.
    intents: list[str] = []
    for operation in permitted:
        operation_id = _v1.pointer_operation_identity(
            operation, target, source, first_parent, pointer_bytes
        )
        branch = f"publish/pointer/{operation}/{target}/from/{source}/{operation_id}"
        refs = (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}")
        if any(_v1._run_git(root, "show-ref", "--verify", "--hash", ref,
                           check=False).returncode == 0 for ref in refs):
            _v1._require_retained_purpose_ref(root, branch, purpose_head)
            intents.append(operation)
    if len(intents) != 1:
        raise _v1.ReleaseValidationError(
            "A protected current-pointer transition requires exactly one graph-permitted retained purpose branch identity."
        )
    _v1.validate_pointer(
        root, pointer, pointer_bytes, first_parent,
        pointer_head=purpose_head, state_revision=commit,
    )


# Rebind the two unchanged retained function bodies in an isolated namespace.
# This avoids forking the entire V1 validator or mutating its module/import API.
# All other release/schema/tag/merge guards continue using retained V1 code.
_history_namespace = dict(vars(_v1))
_history_namespace["_validate_pointer_introduction_commit"] = _validate_pointer_introduction_commit_v1_1
_history_namespace["_validate_reviewed_main_history"] = FunctionType(
    _v1._validate_reviewed_main_history.__code__, _history_namespace,
    argdefs=_v1._validate_reviewed_main_history.__defaults__,
)
_validate_repository_v1_1 = FunctionType(
    _v1.validate_repository.__code__, _history_namespace,
    argdefs=_v1.validate_repository.__defaults__,
)


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
    _validate_repository_v1_1(
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
        _v1._SCHEMA_AUTHORITY_ROOT = None
        _v1._SCHEMA_AUTHORITY_REVISION = None
        root = args.root.resolve()
        if args.schema_root is not None:
            if not (args.pull_request or args.candidate_repository):
                raise _v1.ReleaseValidationError(
                    "A separate V1 schema root is permitted only in trusted-base pull-request mode."
                )
            if not args.base or not _v1.COMMIT_RE.fullmatch(args.base):
                raise _v1.ReleaseValidationError(
                    "Trusted-base schema authority requires the exact pull-request base commit."
                )
            schema_root = args.schema_root if args.schema_root.is_absolute() else Path.cwd() / args.schema_root
            if not schema_root.is_dir() or schema_root.is_symlink():
                raise _v1.ReleaseValidationError(
                    "The separately trusted V1 schema root must be a normal directory."
                )
            _v1._SCHEMA_AUTHORITY_ROOT = schema_root.resolve()
            _v1._require_exact_clean_checkout(_v1._SCHEMA_AUTHORITY_ROOT, args.base,
                                             "The separately trusted V1 schema root")
            _v1._SCHEMA_AUTHORITY_REVISION = args.base
        if args.repository or args.candidate_repository or args.tag or args.tag_object:
            validate_global_tag_namespace(root)
        if args.pull_request:
            if not args.base or not args.head or not args.branch:
                raise _v1.ReleaseValidationError("Pull-request mode requires --base, --head, and --branch.")
            _v1.validate_pull_request(root, args.base, args.head, args.branch)
            print("Reviewed release PR lane passed.")
        elif args.candidate_repository:
            if not args.base or not args.head or not args.branch or not args.main or args.head != args.main:
                raise _v1.ReleaseValidationError(
                    "Candidate repository mode requires matching --head/--main plus --base and --branch."
                )
            _v1._require_exact_clean_checkout(root, args.main, "Candidate repository mode")
            _v1.validate_pull_request(root, args.base, args.head, args.branch)
            _v1._SCHEMA_AUTHORITY_ROOT = None
            _v1._SCHEMA_AUTHORITY_REVISION = None
            validate_repository(root, args.main, allow_unmerged_tip=True)
            print("Reviewed candidate runtime repository state passed.")
        elif args.tag:
            if not args.main:
                raise _v1.ReleaseValidationError("Tag mode requires --main.")
            validate_tag(root, args.tag, args.main)
            print(f"Annotated runtime release tag passed: {args.tag}.")
        elif args.tag_object:
            if not args.main or not args.tag_name:
                raise _v1.ReleaseValidationError("Unreferenced tag-object mode requires --tag-name and --main.")
            validate_unreferenced_tag_object(root, args.tag_object, args.tag_name, args.main)
            print(f"Unreferenced annotated runtime tag object passed: {args.tag_name}.")
        else:
            if not args.main:
                raise _v1.ReleaseValidationError("Repository mode requires an exact lowercase full --main commit SHA.")
            _v1._require_exact_clean_checkout(root, args.main, "Repository mode")
            validate_repository(root, args.main)
            print("Reviewed runtime release repository state passed.")
    except (_v1.ReleaseValidationError, OSError, UnicodeError, ValueError):
        print(
            "Reviewed runtime release validation FAILED; untrusted detail was withheld.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
