from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EvaluationReceiptTests(unittest.TestCase):
    def test_actual_workflow_receipt_matches_added_modified_and_removed_git_blobs(self) -> None:
        workflow = (ROOT / '.github/workflows/release-policy.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Record exact evaluated pull request\n', 1)[1]
        script = textwrap.dedent(step.split("python -I - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / 'repository'
            repository.mkdir()
            def git(*arguments: str) -> str:
                return subprocess.check_output(['git', '-C', str(repository), *arguments], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Receipt Fixture')
            git('config', 'user.email', 'receipt@example.invalid')
            git('config', 'core.autocrlf', 'false')
            (repository / 'modified.md').write_text('before\n', encoding='utf-8')
            (repository / 'removed.md').write_text('remove\n', encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'Base fixture')
            base = git('rev-parse', 'HEAD')
            (repository / 'modified.md').write_text('after\n', encoding='utf-8')
            (repository / 'removed.md').unlink()
            (repository / 'added.md').write_text('add\n', encoding='utf-8')
            git('add', '.')
            git('commit', '-qm', 'Candidate fixture')
            head = git('rev-parse', 'HEAD')
            environment = dict(os.environ, EVALUATED_REPOSITORY_ID='123', EVALUATED_PR_NUMBER='2',
                               EVALUATED_HEAD_SHA=head, EVALUATED_BASE_SHA=base,
                               EVALUATED_WORKFLOW_SHA=base, EVALUATED_RUN_ID='999', EVALUATED_RUN_ATTEMPT='1')
            result = subprocess.run(['python', '-I', '-'], input=script, text=True, cwd=root,
                                    env=environment, capture_output=True, check=True)
            encoded = re.fullmatch(r'NL_RUNTIME_EVALUATION_V1=([A-Za-z0-9+/=]+)\n', result.stdout)
            self.assertIsNotNone(encoded)
            receipt = json.loads(base64.b64decode(encoded[1]))
            self.assertEqual(receipt['headSha'], head)
            self.assertEqual(receipt['baseSha'], base)
            self.assertEqual(receipt['runAttempt'], 1)
            self.assertEqual(receipt['changes'], [
                dict(path='added.md', before=None, after=git('rev-parse', head + ':added.md')),
                dict(path='modified.md', before=git('rev-parse', base + ':modified.md'), after=git('rev-parse', head + ':modified.md')),
                dict(path='removed.md', before=git('rev-parse', base + ':removed.md'), after=None)
            ])
            environment['EVALUATED_WORKFLOW_SHA'] = head
            denied = subprocess.run(['python', '-I', '-'], input=script, text=True, cwd=root,
                                    env=environment, capture_output=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertNotIn('NL_RUNTIME_EVALUATION_V1=', denied.stdout)


if __name__ == '__main__':
    unittest.main()
