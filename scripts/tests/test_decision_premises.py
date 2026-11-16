"""A decision a PR adds or changes cites its premises (D-066, D-069 item 10; decision_premises.py).

A temporary git repository holds the base register and the change; the premise records are fixtures, no network.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import decision_premises  # noqa: E402
import premises  # noqa: E402

REGISTER = config.get('process.decisions_register')
REGISTERED, _ = premises.load(ROOT)  # the repository's premise records; the fixture repositories hold none
HEADER = '| Id | Date | Decision | Invariant | Proof | Status |\n|---|---|---|---|---|---|\n'
OLD = '| D-001 | 2026-10-01 | Old decision | none | test | proven |'
NEW_ROW = '| D-002 | 2026-10-26 | New decision. Premises: P-41 | none | test pending | rite |'
UNSETTLED = {'P-90': {'id': 'P-90', 'slug': 'unsettled', 'status': 'inferred', 'radius': 'high',
                      'path': 'docs/process/premises/unsettled.yml'}}


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                   env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})


class DecisionPremises(unittest.TestCase):
    def repository(self, base_rows, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        git(root, 'init', '-q')
        (root / REGISTER).parent.mkdir(parents=True)
        (root / REGISTER).write_text(HEADER + '\n'.join(base_rows) + '\n')
        git(root, 'add', '-A')
        git(root, 'commit', '-q', '-m', 'base')
        (root / REGISTER).write_text(HEADER + '\n'.join(rows) + '\n')
        return root

    def check(self, root, by_id=None):
        return decision_premises.check(root, 'HEAD', [REGISTER], by_id=by_id or REGISTERED)

    def test_an_existing_row_is_not_judged(self):
        root = self.repository([OLD], [OLD])
        self.assertEqual(self.check(root), ([], []))

    def test_an_added_row_without_a_clause_is_refused(self):
        root = self.repository([OLD], [OLD, '| D-002 | 2026-10-26 | No clause | none | test | rite |'])
        errors, _ = self.check(root)
        self.assertEqual(len(errors), 1)
        self.assertIn('D-002', errors[0])
        self.assertIn('cites its premises', errors[0])

    def test_a_changed_row_is_judged(self):
        root = self.repository([OLD], ['| D-001 | 2026-10-01 | Changed without a clause | none | test | proven |'])
        errors, _ = self.check(root)
        self.assertEqual([error.split(':')[0] for error in errors], ['DECISIONS.md D-001'])

    def test_a_settled_premise_in_a_new_row_passes(self):
        root = self.repository([OLD], [OLD, NEW_ROW])
        self.assertEqual(self.check(root), ([], []))

    def test_a_premise_id_that_is_not_in_the_register_is_refused(self):
        root = self.repository([OLD], [OLD, NEW_ROW.replace('P-41', 'P-999')])
        errors, _ = self.check(root)
        self.assertEqual(len(errors), 1)
        self.assertIn('P-999 is not in', errors[0])

    def test_an_unsettled_high_radius_premise_blocks_the_row(self):
        root = self.repository([OLD], [OLD, NEW_ROW.replace('P-41', 'P-90')])
        errors, _ = self.check(root, by_id=UNSETTLED)
        self.assertEqual(len(errors), 1)
        self.assertIn('blocks this work', errors[0])

    def test_none_is_a_clause_that_passes(self):
        root = self.repository([OLD], [OLD, NEW_ROW.replace('Premises: P-41', 'Premises: none')])
        self.assertEqual(self.check(root), ([], []))

    def test_without_a_base_there_is_no_change_to_judge(self):
        root = self.repository([OLD], [OLD, '| D-002 | 2026-10-26 | No clause | none | test | rite |'])
        self.assertEqual(decision_premises.check(root, None), ([], []))

    def test_an_unreadable_base_is_a_warning_not_a_silent_pass(self):
        root = self.repository([OLD], [OLD])
        errors, warnings = decision_premises.check(root, 'no-such-ref')
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('cannot be read', warnings[0])

    def test_the_repository_register_passes(self):
        errors, _ = decision_premises.check(ROOT, 'HEAD')
        self.assertEqual(errors, [])

    def test_the_clause_line_is_the_premise_line_name(self):
        self.assertEqual(premises.setting('line_name'), 'Premises')
        self.assertEqual(decision_premises.clause('| D-9 | d | x Premises: P-41, P-30 | i | p | s |'), 'P-41, P-30')


if __name__ == '__main__':
    unittest.main(verbosity=1)
