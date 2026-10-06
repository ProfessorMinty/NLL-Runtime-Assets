from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "validate-runtime.yml",
    ROOT / ".github" / "workflows" / "release-policy.yml",
)
V1_EXECUTION_IMAGE = (
    "python:3.12.11-bookworm@"
    "sha256:13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12"
)


def run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        indentation = len(match.group(1))
        block = [match.group(2)]
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= indentation:
                break
            block.append(line)
            index += 1
        blocks.append("\n".join(block))
    return blocks


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_set_is_exact(self) -> None:
        actual = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / ".github" / "workflows").glob("*.yml")
        }
        self.assertEqual(
            actual,
            {
                ".github/workflows/release-policy.yml",
                ".github/workflows/validate-runtime.yml",
            },
        )

    def test_execution_image_and_repository_materialization_are_frozen(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            self.assertEqual(text.count("runs-on: ubuntu-24.04"), 1)
            self.assertEqual(text.count("timeout-minutes: 30"), 1)
            self.assertEqual(text.count(f"image: {V1_EXECUTION_IMAGE}"), 1)
            self.assertIn('= "3.12.11"', text)
            self.assertNotRegex(text, r"(?m)^\s*uses:\s*")
            self.assertNotIn("setup-python", text)
            self.assertRegex(text, r"git(?: -C repository)? fetch --force origin")
            self.assertIn("'+refs/heads/*:refs/remotes/origin/*'", text)
            self.assertIn("'+refs/tags/*:refs/tags/*'", text)
            self.assertNotIn("persist-credentials", text)

    def test_materialized_repositories_use_exact_ephemeral_safe_directories(self) -> None:
        expected = {
            "validate-runtime.yml": (
                "git init .",
                'git config --global --add safe.directory "$GITHUB_WORKSPACE"',
                'git remote add origin "$GITHUB_SERVER_URL/$REPOSITORY.git"',
            ),
            "release-policy.yml": (
                "git init repository",
                'git config --global --add safe.directory "$GITHUB_WORKSPACE/repository"',
                'git -C repository remote add origin "$GITHUB_SERVER_URL/$BASE_REPOSITORY.git"',
            ),
        }
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            initialize, trust, remote = expected[workflow.name]
            self.assertEqual(text.count(trust), 1)
            self.assertLess(text.index(initialize), text.index(trust))
            self.assertLess(text.index(trust), text.index(remote))
            self.assertNotRegex(text, r"safe\.directory\s+['\"]?\*['\"]?")

    def test_untrusted_event_values_never_interpolate_inside_run_scripts(self) -> None:
        for workflow in WORKFLOWS:
            for block in run_blocks(workflow.read_text(encoding="utf-8")):
                self.assertNotIn("${{", block)

    def test_release_policy_uses_trusted_base_and_never_executes_candidate_code(self) -> None:
        text = WORKFLOWS[1].read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", text)
        self.assertIn("contents: read", text)
        self.assertNotRegex(text, r"(?m)^\s*(?:contents|checks|pull-requests):\s*write\s*$")
        self.assertIn("worktree add --detach ../trusted", text)
        self.assertIn("worktree add --detach ../candidate", text)
        self.assertLess(
            text.index("Verify immutable execution environment and same-repository head"),
            text.index("Materialize exact trusted base and candidate as data"),
        )
        self.assertIn('test "$HEAD_REPOSITORY" = "$BASE_REPOSITORY"', text)
        self.assertNotIn("working-directory: candidate", text)
        self.assertNotIn("uses: ./candidate", text)
        for block in run_blocks(text):
            candidate_path_pattern = (
                r"(?m)(?:python|bash|sh|node|npm|make|dotnet)\s+candidate[\x2f\\]"
            )
            self.assertNotRegex(block, candidate_path_pattern)
        self.assertIn("python -P trusted/tools/validate_public_boundary.py", text)
        self.assertIn("python -P trusted/tools/validate_runtime_release_v1.py", text)
        self.assertIn("python -P trusted/tools/validate_runtime_release.py", text)
        self.assertNotIn("python trusted/tools/validate_runtime_release_v1.py", text)
        self.assertNotIn("cp trusted/schemas", text)
        self.assertEqual(text.count("--schema-root trusted"), 2)
        self.assertIn(
            "--root candidate --schema-root trusted --pull-request",
            text,
        )
        trusted_python_paths = re.findall(
            r"python\s+-P\s+trusted/(tools/[a-z0-9_]+\.py)", text
        )
        self.assertEqual(
            set(trusted_python_paths),
            {
                "tools/validate_public_boundary.py",
                "tools/validate_runtime_release.py",
                "tools/validate_runtime_release_v1.py",
                "tools/verify_v1_wheelhouse.py",
            },
        )
        self.assertEqual(trusted_python_paths.count("tools/validate_runtime_release_v1.py"), 1)
        self.assertEqual(trusted_python_paths.count("tools/validate_runtime_release.py"), 1)
        self.assertEqual(trusted_python_paths.count("tools/validate_public_boundary.py"), 1)
        self.assertEqual(trusted_python_paths.count("tools/verify_v1_wheelhouse.py"), 1)
        self.assertNotIn("trusted/tests", text)
        self.assertNotIn("unittest discover", text)
        self.assertNotIn("trusted/tools/validate_identity_contracts.py", text)
        self.assertNotIn("trusted/tools/validate_runtime_semantics.py", text)
        self.assertNotIn("trusted/tools/generate_discovery.py", text)
        self.assertNotIn("trusted/tools/validate_discovery.py", text)
        self.assertIn('--root candidate --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"', text)
        self.assertNotIn('--root candidate --revision "$PR_HEAD_SHA"', text)
        self.assertLess(
            text.index("Enforce tracked public repository boundary from trusted base"),
            text.index("Verify immutable trusted wheelhouse before dependency install"),
        )
        self.assertLess(
            text.index("Verify immutable trusted wheelhouse before dependency install"),
            text.index("Install trusted validation dependency"),
        )
        self.assertLess(
            text.index("Install trusted validation dependency"),
            text.index("Enforce changed-path lane from trusted base"),
        )
        self.assertLess(
            text.index("Enforce changed-path lane from trusted base"),
            text.index("Enforce reviewed repository state from trusted base"),
        )

    def test_later_added_tools_or_tests_cannot_enter_privileged_execution(self) -> None:
        text = WORKFLOWS[1].read_text(encoding="utf-8")
        executable_trusted_paths = set(
            re.findall(
                r"trusted/" + r"(?:tools|tests)/" + r"[A-Za-z0-9_./-]+",
                text,
            )
        )
        self.assertEqual(
            executable_trusted_paths,
            {
                "trusted/tools/validate_public_boundary.py",
                "trusted/tools/validate_runtime_release.py",
                "trusted/tools/validate_runtime_release_v1.py",
                "trusted/tools/verify_v1_wheelhouse.py",
            },
        )
        self.assertNotRegex(text, r"(?:discover|find|glob|rglob).*trusted/(?:tools|tests)")

    def test_changed_path_gate_precedes_any_candidate_schema_evaluation(self) -> None:
        text = WORKFLOWS[1].read_text(encoding="utf-8")
        changed = text.index("Enforce changed-path lane from trusted base")
        repository = text.index("Enforce reviewed repository state from trusted base")
        self.assertLess(changed, repository)
        changed_block = text[changed:repository]
        self.assertIn("--schema-root trusted --pull-request", changed_block)
        repository_block = text[repository:]
        self.assertIn("trusted/tools/validate_runtime_release.py", repository_block)
        self.assertIn("--root candidate --schema-root trusted --candidate-repository", repository_block)
        self.assertIn('--base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"', repository_block)
        self.assertIn('--branch "$PR_HEAD_REF" --main "$PR_HEAD_SHA"', repository_block)

    def test_evaluation_receipt_follows_successful_validation_and_uses_only_event_identities(self) -> None:
        text = WORKFLOWS[1].read_text(encoding="utf-8")
        self.assertLess(text.index("Enforce reviewed repository state from trusted base"), text.index("Record exact evaluated pull request"))
        receipt_step = text[text.index("      - name: Record exact evaluated pull request"):]
        self.assertNotIn("if:", receipt_step)
        self.assertIn("python -I -", receipt_step)
        self.assertIn("NL_RUNTIME_EVALUATION_V1=", receipt_step)
        self.assertIn("'--abbrev=40', '-z', base, head", receipt_step)
        self.assertIn("if workflow != base:", receipt_step)
        self.assertNotIn("candidate/", receipt_step)
        for name in ("REPOSITORY_ID", "PR_NUMBER", "HEAD_SHA", "BASE_SHA", "WORKFLOW_SHA", "RUN_ID", "RUN_ATTEMPT"):
            self.assertIn("EVALUATED_" + name, receipt_step)

    def test_scheduled_monitor_lane_executes_only_protected_python(self) -> None:
        text = WORKFLOWS[0].read_text(encoding="utf-8")
        schedule_safe_entrypoints = {
            "tools/validate_public_boundary.py",
            "tools/validate_runtime_release.py",
            "tools/verify_v1_wheelhouse.py",
        }
        protected_commands = re.findall(
            r"python\s+-P\s+(tools/[a-z0-9_]+\.py)", text
        )
        self.assertEqual(set(protected_commands), schedule_safe_entrypoints)
        self.assertLess(
            text.index("Verify immutable wheelhouse before dependency install"),
            text.index("Install validation dependency"),
        )
        self.assertLess(
            text.index("Validate reviewed release repository state"),
            text.index("Validate tracked public repository boundary"),
        )
        mutable_steps = (
            "Validate immutable identity contracts",
            "Validate public runtime semantics",
            "Require deterministic discovery output",
            "Validate discovery consistency",
            "Run contract regression tests",
        )
        non_schedule_condition = (
            "if: github.event_name == 'pull_request' || "
            "(github.event_name == 'push' && github.ref == 'refs/heads/main')"
        )
        for step in mutable_steps:
            start = text.index(f"- name: {step}")
            following = text[start:text.find("\n\n", start)]
            self.assertIn(non_schedule_condition, following)

    def test_trusted_ci_dependencies_are_fully_pinned_and_hash_required(self) -> None:
        requirements = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
        for package in (
            "attrs",
            "jsonschema",
            "jsonschema-specifications",
            "referencing",
            "rfc3339-validator",
            "rpds-py",
            "six",
            "typing-extensions",
        ):
            matching = [line for line in requirements.splitlines() if line.startswith(f"{package}==")]
            self.assertEqual(len(matching), 1)
            self.assertTrue(matching[0].endswith(" \\"))
        self.assertNotRegex(requirements, r"(?m)^\s*--hash=sha256:[A-F]")
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            self.assertIn("python -m pip install --disable-pip-version-check --no-deps --no-index", text)
            self.assertIn("--find-links", text)
            self.assertIn("--require-hashes", text)

    def test_offline_v1_wheelhouse_is_exact(self) -> None:
        expected = {
            "attrs-26.1.0-py3-none-any.whl": "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
            "jsonschema-4.26.0-py3-none-any.whl": "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
            "jsonschema_specifications-2025.9.1-py3-none-any.whl": "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
            "referencing-0.37.0-py3-none-any.whl": "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
            "rfc3339_validator-0.1.4-py2.py3-none-any.whl": "24f6ec1eda14ef823da9e36ec7113124b39c04d50a4d3d3a3c2859577e7791fa",
            "rpds_py-2026.6.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": "ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6",
            "six-1.17.0-py2.py3-none-any.whl": "4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274",
            "typing_extensions-4.16.0-py3-none-any.whl": "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
        }
        wheelhouse = ROOT / "ci" / "wheelhouse"
        actual = {path.name for path in wheelhouse.glob("*.whl")}
        self.assertEqual(actual, set(expected))
        for filename, digest in expected.items():
            self.assertEqual(hashlib.sha256((wheelhouse / filename).read_bytes()).hexdigest(), digest)

    def test_exact_required_check_contexts_remain_stable(self) -> None:
        normal = WORKFLOWS[0].read_text(encoding="utf-8")
        trusted = WORKFLOWS[1].read_text(encoding="utf-8")
        self.assertRegex(normal, r"(?m)^  validate:\s*$")
        self.assertRegex(trusted, r"(?m)^  release-policy:\s*$")
        self.assertIn("- 'runtime-v1-*'", normal)
        self.assertIn("- 'runtime-v1-*/**'", normal)
        self.assertIn("python -P tools/validate_runtime_release.py", normal)
        self.assertNotIn("python tools/validate_runtime_release_v1.py", normal)
        self.assertLess(
            normal.index("Validate reviewed release repository state"),
            normal.index("Validate immutable identity contracts"),
        )
        self.assertLess(
            normal.index("Validate annotated runtime release tag"),
            normal.index("Validate immutable identity contracts"),
        )
        self.assertIn("schedule:", normal)
        self.assertIn("cron: '17 * * * *'", normal)
        self.assertNotIn("workflow_dispatch:", normal)

    def test_global_repository_and_tag_audits_route_through_dispatcher(self) -> None:
        trusted = WORKFLOWS[1].read_text(encoding="utf-8")
        normal = WORKFLOWS[0].read_text(encoding="utf-8")
        self.assertRegex(
            trusted,
            r"python -P trusted/tools/validate_runtime_release\.py\s+"
            r"--root candidate --schema-root trusted --candidate-repository",
        )
        self.assertRegex(
            normal,
            r"python -P tools/validate_runtime_release\.py --repository",
        )
        self.assertRegex(
            normal,
            r"python -P tools/validate_runtime_release\.py --tag",
        )
        self.assertRegex(
            normal,
            r"python -P tools/validate_runtime_release\.py --candidate-repository",
        )

    def test_documented_tag_rulesets_cover_flat_and_nested_runtime_refs(self) -> None:
        contract = (ROOT / "docs" / "PUBLISHING-CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("`refs/tags/runtime-v1-*`", contract)
        self.assertIn("`refs/tags/runtime-v1-*/*`", contract)
        self.assertIn("`refs/tags/runtime-v1-*/**/*`", contract)
        self.assertIn("File::FNM_PATHNAME", contract)
        self.assertIn("Path A — eligible Enterprise Cloud organization ownership", contract)
        self.assertIn("Path B — dedicated independent App evaluator", contract)
        self.assertIn("Restrict non-publisher branches", contract)
        self.assertIn("refs/heads/**/*", contract)
        self.assertIn("Restrict non-runtime tags", contract)
        self.assertIn("refs/tags/**/*", contract)
        self.assertIn("must not be a bypass actor", contract)
        self.assertIn("Protect runtime publisher branch updates", contract)
        self.assertIn("restrict every update", contract)
        self.assertIn("no-update rule remains active", contract)
        self.assertIn("independently credentialed private policy service", contract)
        self.assertIn("no contents-write authority", contract)
        self.assertIn("runtime-rights-eligibility", contract)
        self.assertIn("runtime-v1-execution-migration", contract)
        self.assertIn("infrastructure/runtime-v1-execution/<operation-id>", contract)
        self.assertIn("bounded explicit not-applicable", contract)
        self.assertIn(
            "publish/artifacts/<release-id>/from/<source-release-id-or-none>/<operation-id>",
            contract,
        )
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn(
            "publish/artifacts/runtime-v1-YYYY.MM.DD.N/from/<source|none>/<operation-id>",
            contributing,
        )

    def test_real_private_library_root_is_absent_from_public_text(self) -> None:
        forbidden = "E:" + "\\" + "Assets"
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn(forbidden, text, path.as_posix())


if __name__ == "__main__":
    unittest.main()
