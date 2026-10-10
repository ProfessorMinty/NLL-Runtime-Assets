"""Real local Git histories; never operational or hosted-release evidence."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import test_runtime_release as fixtures
import validate_runtime_release as dispatcher
import validate_runtime_release_v1 as retained


class PointerHistoryVersionedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.RuntimeReleaseContractTests()
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def first(self):
        f = self.fixture
        _, pointer, _ = f.prepare_tagged_release()
        f.merge_pointer("select", pointer, "none")
        return pointer

    def second(self):
        first = self.first()
        f = self.fixture
        _, second, _ = f.prepare_tagged_release(fixtures.RELEASE_TWO, fixtures.RELEASE_ONE)
        head, merge = f.merge_pointer("select", second, fixtures.RELEASE_ONE)
        return first, second, head, merge

    def test_original_v1_bytes_and_callable_are_preserved(self):
        raw = (fixtures.ROOT / "tools/validate_runtime_release_v1.py").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "a30ff047d9bcd4de8271a3b30413caa67acdc01da880d4477172dbf232d13c80")
        self.assertIsNot(retained._validate_pointer_introduction_commit,
                         dispatcher._validate_pointer_introduction_commit_v1_1)
        self.assertIs(retained.validate_repository.__globals__["_validate_reviewed_main_history"],
                      retained._validate_reviewed_main_history)
        self.assertEqual(dispatcher.POINTER_HISTORY_AUTHORITY_VERSION, "1.1")

    def test_first_normal_select_remains_valid(self):
        self.first()
        dispatcher.validate_repository(self.fixture.root, self.fixture.sha())
        retained.validate_repository(self.fixture.root, self.fixture.sha())

    def test_second_select_passes_without_suppressing_original_bug(self):
        _, _, _, merge = self.second()
        with self.assertRaisesRegex(retained.ReleaseValidationError, "single permitted graph direction"):
            retained.validate_repository(self.fixture.root, merge)
        dispatcher.validate_repository(self.fixture.root, merge)

    def test_real_merge_rollback_and_immediate_forward_restore_pass(self):
        first, second, _, _ = self.second()
        f = self.fixture
        _, rollback = f.merge_pointer("rollback", first, fixtures.RELEASE_TWO)
        dispatcher.validate_repository(f.root, rollback)
        _, restoration = f.merge_pointer("restore", second, fixtures.RELEASE_ONE)
        dispatcher.validate_repository(f.root, restoration)

    def test_nonadjacent_forward_restore_retains_graph_validation(self):
        first, _, _, _ = self.second()
        f = self.fixture
        _, third, _ = f.prepare_tagged_release(fixtures.RELEASE_THREE, fixtures.RELEASE_TWO)
        f.merge_pointer("select", third, fixtures.RELEASE_TWO)
        f.merge_pointer("rollback", first, fixtures.RELEASE_THREE)
        _, restoration = f.merge_pointer("restore", third, fixtures.RELEASE_ONE)
        dispatcher.validate_repository(f.root, restoration)

    def test_two_graph_permitted_purpose_aliases_are_rejected(self):
        _, second, head, merge = self.second()
        f = self.fixture
        base = f.git("rev-parse", merge + "^1").stdout.decode().strip()
        alias = f.pointer_branch("restore", second, fixtures.RELEASE_ONE, base)
        f.git("update-ref", "refs/heads/" + alias, head)
        with self.assertRaisesRegex(retained.ReleaseValidationError, "exactly one"):
            dispatcher.validate_repository(f.root, merge)

    def test_missing_purpose_ref_is_rejected(self):
        _, second, _, merge = self.second()
        f = self.fixture
        base = f.git("rev-parse", merge + "^1").stdout.decode().strip()
        branch = f.pointer_branch("select", second, fixtures.RELEASE_ONE, base)
        f.git("update-ref", "-d", "refs/heads/" + branch)
        with self.assertRaisesRegex(retained.ReleaseValidationError, "retained purpose branch identity"):
            dispatcher.validate_repository(f.root, merge)

    def test_wrong_or_disagreeing_retained_target_is_rejected(self):
        _, second, _, merge = self.second()
        f = self.fixture
        base = f.git("rev-parse", merge + "^1").stdout.decode().strip()
        branch = f.pointer_branch("select", second, fixtures.RELEASE_ONE, base)
        f.git("update-ref", "refs/remotes/origin/" + branch, base)
        with self.assertRaisesRegex(retained.ReleaseValidationError, "exact retained purpose"):
            dispatcher.validate_repository(f.root, merge)

    def test_wrong_direction_branch_cannot_authorize_merge(self):
        _, second, head, merge = self.second()
        f = self.fixture
        base = f.git("rev-parse", merge + "^1").stdout.decode().strip()
        branch = f.pointer_branch("select", second, fixtures.RELEASE_ONE, base)
        wrong = f.pointer_branch("rollback", second, fixtures.RELEASE_ONE, base)
        f.git("update-ref", "-d", "refs/heads/" + branch)
        f.git("update-ref", "refs/heads/" + wrong, head)
        with self.assertRaisesRegex(retained.ReleaseValidationError, "retained purpose branch identity"):
            dispatcher.validate_repository(f.root, merge)

    def test_direct_pointer_commit_remains_rejected(self):
        self.first()
        f = self.fixture
        _, second, _ = f.prepare_tagged_release(fixtures.RELEASE_TWO, fixtures.RELEASE_ONE)
        f.write_json(retained.CURRENT_POINTER_PATH.as_posix(), second)
        direct = f.commit("Unreviewed direct pointer")
        with self.assertRaisesRegex(retained.ReleaseValidationError, "two-parent"):
            dispatcher.validate_repository(f.root, direct)

    def test_purpose_commit_with_extra_file_remains_rejected(self):
        self.first()
        f = self.fixture
        _, second, _ = f.prepare_tagged_release(fixtures.RELEASE_TWO, fixtures.RELEASE_ONE)
        base_branch = f.git("branch", "--show-current").stdout.decode().strip()
        branch = f.pointer_branch("select", second, fixtures.RELEASE_ONE)
        f.git("switch", "-c", branch)
        f.write_json(retained.CURRENT_POINTER_PATH.as_posix(), second)
        f.write_json("extra.json", {"not": "a pointer"})
        head = f.commit("Extra change")
        f.git("switch", base_branch)
        f.git("merge", "--no-ff", head, "-m", "Merge invalid extra change")
        with self.assertRaisesRegex(retained.ReleaseValidationError, "only the reviewed current pointer"):
            dispatcher.validate_repository(f.root, f.sha())


if __name__ == "__main__":
    unittest.main()
