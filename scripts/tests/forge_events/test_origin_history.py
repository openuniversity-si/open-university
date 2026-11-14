"""ORIGIN-PUSH-HISTORY (D-300): Origin's pushes and force_pushes answered from this clone's reflog of the branch's
remote-tracking ref, proven against Origin's head, never from the Worker's /v1/events.

The adapter tests use fake refs (the reflog entries, Origin's tip and the ancestry answer); the git tests push to a local
bare remote, so the reflog is git's own. An answer is given only when the reflog proves the branch's history; otherwise
the operation refuses with the reason.
"""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))

import config  # noqa: E402
import forge_git_ref  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_history  # noqa: E402

REPO = 'openuniversity-si/open-university'
ORIGIN_HOST = 'origin.test'
ZERO = '0' * 40
A, B, C = ('a' * 40, 'b' * 40, 'c' * 40)
T1, T2, T3 = '2026-11-03T12:00:00.000Z', '2026-11-03T13:00:00.000Z', '2026-11-03T14:00:00.000Z'
S1, S2, S3 = (int(datetime.fromisoformat(moment.replace('Z', '+00:00')).timestamp()) for moment in (T1, T2, T3))
PUSH = forge_origin_history.PUSH


class FakeRefs:
    """GitRefs' history surface: the reflog entries, Origin's tip, and which moves are fast-forwards."""

    def __init__(self):
        self.entries, self.tip_sha, self.rewinds, self.unknown = [], None, set(), set()

    def url(self):
        return f'https://{ORIGIN_HOST}/{REPO}.git'

    def tip(self, branch):
        return self.tip_sha

    def push_log(self, branch):
        return list(self.entries) if branch == 'mod/x' else []

    def is_ancestor(self, older, newer):
        return None if (older, newer) in self.unknown else (older, newer) not in self.rewinds


class OriginHistory(unittest.TestCase):
    def setUp(self):
        self.refs = FakeRefs()
        real = config.get
        hosts = mock.patch.object(config, 'get', lambda key, *args: [ORIGIN_HOST] if key == 'origin-client.git_hosts'
                                  else real(key, *args))
        hosts.start()
        self.addCleanup(hosts.stop)
        self.adapter = forge_origin.OriginAdapter(client=None, repo=REPO, log=object(), refs=self.refs)

    def history(self):
        self.refs.entries = [(ZERO, A, S1, PUSH), (A, B, S2, PUSH), (B, C, S3, PUSH)]
        self.refs.tip_sha, self.refs.rewinds = C, {(B, C)}

    def test_pushes_answers_from_the_reflog(self):
        self.history()
        self.assertEqual(self.adapter.pushes(REPO, 'mod/x'), [
            {'before': B, 'after': C, 'timestamp': T3},
            {'before': A, 'after': B, 'timestamp': T2},
            {'before': ZERO, 'after': A, 'timestamp': T1}])

    def test_force_pushes_keeps_only_the_moves_that_are_not_fast_forwards(self):
        self.history()
        self.assertEqual(self.adapter.force_pushes(REPO, 'mod/x'), [{'before': B, 'after': C, 'timestamp': T3}])

    def test_a_proven_history_with_no_rewind_answers_empty_with_that_meaning(self):
        self.history()
        self.refs.rewinds = set()
        self.assertEqual(self.adapter.force_pushes(REPO, 'mod/x'), [])

    def test_no_record_refuses_with_the_reason(self):
        self.history()
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'holds no record of refs/heads/mod/y'):
            self.adapter.pushes(REPO, 'mod/y')

    def test_a_reflog_without_the_creation_refuses(self):
        self.history()
        self.refs.entries = self.refs.entries[1:]
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'does not reach its creation'):
            self.adapter.pushes(REPO, 'mod/x')

    def test_a_move_this_clone_fetched_refuses_and_names_it(self):
        self.history()
        self.refs.entries[1] = (A, B, S2, 'fetch: fast-forward')
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'by `fetch: fast-forward`, not by a push'):
            self.adapter.pushes(REPO, 'mod/x')

    def test_a_head_on_origin_past_the_reflog_refuses(self):
        self.history()
        self.refs.tip_sha = 'd' * 40  # another clone pushed after this clone's last push, unseen here
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'a push from another clone is not in its reflog'):
            self.adapter.force_pushes(REPO, 'mod/x')

    def test_a_move_whose_commits_are_missing_refuses(self):
        self.history()
        self.refs.unknown = {(A, B)}
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'cannot tell whether that push was forced'):
            self.adapter.pushes(REPO, 'mod/x')

    def test_another_repository_refuses(self):
        with self.assertRaisesRegex(forge_origin.OriginAdapterError, 'another repository'):
            self.adapter.pushes('other/repo', 'mod/x')

    def test_the_journal_is_the_git_ref_log_and_never_the_worker(self):
        with mock.patch.object(forge_origin, 'ControlAdapter', side_effect=AssertionError('the Worker is not used')):
            adapter = forge_origin.OriginAdapter(client=None, repo=REPO, refs=self.refs)
        self.assertIsInstance(adapter.log, forge_git_ref.GitRefAdapter)
        self.assertIs(adapter.log.refs, self.refs)

    def test_the_mapping_is_pure_and_needs_no_adapter(self):
        records = [{'ref': 'refs/heads/mod/x', 'before': ZERO, 'after': A, 'created': True, 'pushed_at': T1},
                   {'ref': 'refs/heads/mod/x', 'before': A, 'after': B, 'forced': True, 'pushed_at': T2}]
        self.assertEqual(forge_origin_history.push_history(records, 'refs/heads/mod/x', True, forced_only=True),
                         [{'before': A, 'after': B, 'timestamp': T2}])


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, input='', capture_output=True, text=True, check=True).stdout.strip()


class ReflogOfARealClone(unittest.TestCase):
    """git's own reflog: a local bare remote, this clone's pushes, and another clone's push fetched here."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        git('init', '-q', '--bare', 'remote.git', cwd=self.root)
        self.mine = self.clone('mine')
        self.refs = forge_git_ref.GitRefs(self.mine, 'origin')

    def clone(self, name):
        git('init', '-q', '-b', 'main', name, cwd=self.root)
        where = self.root / name
        for key, value in (('user.name', 't'), ('user.email', 't@t'), ('core.hooksPath', '/dev/null')):
            git('config', key, value, cwd=where)
        git('remote', 'add', 'origin', str(self.root / 'remote.git'), cwd=where)
        return where

    def commit(self, where, text):
        git('commit', '-q', '--allow-empty', '-m', text, cwd=where)
        return git('rev-parse', 'HEAD', cwd=where)

    def history(self, forced_only=False):
        return forge_origin_history.reflog_history(self.refs.push_log('topic/x'), 'refs/heads/topic/x',
                                                   self.refs.tip('topic/x'), self.refs.is_ancestor, forced_only)

    def test_each_push_is_one_entry_and_a_rewind_is_a_force_push(self):
        first = self.commit(self.mine, 'one')
        git('push', '-q', 'origin', 'HEAD:refs/heads/topic/x', cwd=self.mine)
        self.commit(self.mine, 'two')
        third = self.commit(self.mine, 'three')
        git('push', '-q', 'origin', 'HEAD:refs/heads/topic/x', cwd=self.mine)  # two commits in one push
        git('reset', '-q', '--hard', first, cwd=self.mine)
        rewound = self.commit(self.mine, 'rewritten')
        git('push', '-q', '--force', 'origin', 'HEAD:refs/heads/topic/x', cwd=self.mine)
        pushes = self.history()
        self.assertEqual([(push['before'], push['after']) for push in pushes],
                         [(third, rewound), (first, third), (ZERO, first)])
        self.assertTrue(all(push['timestamp'].endswith('Z') for push in pushes))
        self.assertEqual([(push['before'], push['after']) for push in self.history(forced_only=True)],
                         [(third, rewound)])

    def test_a_push_from_another_clone_is_a_refusal_fetched_or_not(self):
        self.commit(self.mine, 'one')
        git('push', '-q', 'origin', 'HEAD:refs/heads/topic/x', cwd=self.mine)
        other = self.clone('other')
        git('fetch', '-q', 'origin', cwd=other)
        git('checkout', '-q', '-b', 'topic/x', 'origin/topic/x', cwd=other)
        self.commit(other, 'elsewhere')
        git('push', '-q', 'origin', 'HEAD:refs/heads/topic/x', cwd=other)
        with self.assertRaisesRegex(forge_origin_history.HistoryGap, 'not in its reflog'):
            self.history()
        git('fetch', '-q', 'origin', cwd=self.mine)
        with self.assertRaisesRegex(forge_origin_history.HistoryGap, r'by `fetch.*`, not by a push of this clone'):
            self.history()

    def test_a_branch_this_clone_never_pushed_has_no_record(self):
        self.assertEqual(self.refs.push_log('topic/x'), [])


if __name__ == '__main__':
    unittest.main()
