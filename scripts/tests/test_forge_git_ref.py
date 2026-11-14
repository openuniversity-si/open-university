"""forge_git_ref (GX-FIX-train-lock, D-070): lock refs over the git protocol, create and fast-forward only, never a
delete or a rewind. A local bare repository is the remote; no network."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import forge_git_ref  # noqa: E402

NAME = 'train/lock'


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, input='', capture_output=True, text=True, check=True).stdout.strip()


class Remote:
    """A bare remote and one clone per contender (hooks off: the clones are not this checkout)."""

    def __init__(self, test):
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        git('init', '-q', '--bare', 'remote.git', cwd=self.root)

    def clone(self, name):
        git('init', '-q', name, cwd=self.root)
        git('remote', 'add', 'origin', str(self.root / 'remote.git'), cwd=self.root / name)
        return forge_git_ref.GitRefs(self.root / name, 'origin')

    def tip(self):
        out = git('for-each-ref', '--format=%(objectname)', f'refs/heads/{NAME}', cwd=self.root / 'remote.git')
        return out or None

    def tip_of(self, name):
        return git('for-each-ref', '--format=%(objectname)', f'refs/heads/{name}', cwd=self.root / 'remote.git') or None

    def refs(self):
        return git('for-each-ref', '--format=%(refname)', cwd=self.root / 'remote.git').split()


ORIGIN_EXISTS = 'reference already exists'  # Origin's words for a create the ref beat (PR #90's gate evidence, F29)
ORIGIN_MOVED = 'reference changed'  # a stand-in for any other wording of a fast-forward a rival beat
ORIGIN_POLICY = 'permission denied'  # a refusal that is no race: the ref did not move
# Origin as a git server: the update is applied by its own receive step (a proc-receive hook here), which refuses a ref
# that exists or moved with its own reason, after the client already checked the advertisement. A `rival` file makes
# that step first apply a rival's record (the rival won between this push's advertisement and its update); a `policy`
# file makes it refuse every push with ORIGIN_POLICY.
ORIGIN_HOOK = '''#!{python}
import os, subprocess, sys
ZERO = '0' * 40
IDENTITY = dict(os.environ, GIT_AUTHOR_NAME='rival', GIT_AUTHOR_EMAIL='r@r', GIT_COMMITTER_NAME='rival',
                GIT_COMMITTER_EMAIL='r@r')

def read():
    size = int(sys.stdin.buffer.read(4), 16)
    return None if size == 0 else sys.stdin.buffer.read(size - 4).decode().rstrip('\\n')

def write(*lines):
    for line in lines:
        data = (line + '\\n').encode()
        sys.stdout.buffer.write(b'%04x' % (len(data) + 4) + data)
    sys.stdout.buffer.write(b'0000')
    sys.stdout.buffer.flush()

def git(*args, stdin=''):
    return subprocess.run(['git', *args], input=stdin, capture_output=True, text=True, env=IDENTITY)

while read() is not None:
    pass
write('version=1')
commands = []
while (line := read()) is not None:
    commands.append(line.split())
results = []
for old, new, ref in commands:
    if os.path.exists('policy'):
        results.append(f'ng {{ref}} {ORIGIN_POLICY}')
        continue
    if os.path.exists('rival'):
        record = open('rival').read()
        os.remove('rival')
        held = git('rev-parse', '--verify', '-q', ref).stdout.strip()
        tree = git('mktree').stdout.strip()
        rival = git('commit-tree', tree, *(['-p', held] if held else []), stdin=record).stdout.strip()
        git('update-ref', ref, rival, held or ZERO)
    if git('update-ref', ref, new, old).returncode == 0:
        results.append(f'ok {{ref}}')
    else:
        results.append(f'ng {{ref}} {{\"{ORIGIN_EXISTS}\" if old == ZERO else \"{ORIGIN_MOVED}\"}}')
write(*results)
'''


class Origin(Remote):
    """A bare remote that applies refs/heads/* updates itself and words its refusals as Origin does."""

    def __init__(self, test):
        super().__init__(test)
        self.bare = self.root / 'remote.git'
        hook = self.bare / 'hooks' / 'proc-receive'
        hook.write_text(ORIGIN_HOOK.format(python=sys.executable, ORIGIN_EXISTS=ORIGIN_EXISTS,
                                           ORIGIN_MOVED=ORIGIN_MOVED, ORIGIN_POLICY=ORIGIN_POLICY))
        hook.chmod(0o755)
        git('config', 'receive.procReceiveRefs', 'refs/heads/', cwd=self.bare)

    def rival_wins_next_push(self, record):
        (self.bare / 'rival').write_text(json.dumps(record, sort_keys=True))

    def refuse_every_push(self):
        (self.bare / 'policy').write_text('')


class GitRefs(unittest.TestCase):
    def setUp(self):
        self.remote = Remote(self)
        self.a, self.b = self.remote.clone('a'), self.remote.clone('b')

    def test_an_absent_ref_reads_none(self):
        self.assertIsNone(self.a.read(NAME))

    def test_create_then_read_the_record_from_another_clone(self):
        self.assertTrue(self.a.advance(NAME, {'owner': 'a', 'expires': 'x'}, None))
        sha, record = self.b.read(NAME)
        self.assertEqual((sha, record), (self.remote.tip(), {'owner': 'a', 'expires': 'x'}))
        files = git('ls-tree', '--name-only', sha, cwd=self.remote.root / 'remote.git')
        self.assertEqual(files, forge_git_ref.RECORD_FILE)
        self.assertEqual(json.loads(git('show', f'{sha}:{forge_git_ref.RECORD_FILE}',
                                        cwd=self.remote.root / 'remote.git')), record)

    def test_a_record_larger_than_the_argument_limit_is_committed_through_stdin(self):
        record = {'owner': 'a', 'body': 'x' * os.sysconf('SC_ARG_MAX')}  # more than any one argument may hold
        self.assertTrue(self.a.advance(NAME, record, None))
        self.assertEqual(self.b.read(NAME)[1], record)

    def test_two_creators_only_one_wins(self):
        self.assertIsNone(self.b.read(NAME), 'b read the ref absent before a created it')
        self.assertTrue(self.a.advance(NAME, {'owner': 'a'}, None))
        self.assertFalse(self.b.advance(NAME, {'owner': 'b'}, None))
        self.assertEqual(self.a.read(NAME)[1], {'owner': 'a'})

    def test_an_advance_fast_forwards_from_the_sha_read(self):
        self.a.advance(NAME, {'owner': 'a', 'n': 'first'}, None)
        first, _ = self.a.read(NAME)
        self.assertTrue(self.a.advance(NAME, {'owner': 'a', 'n': 'second'}, first))
        tip = self.remote.tip()
        self.assertEqual(git('rev-parse', f'{tip}^', cwd=self.remote.root / 'remote.git'), first)

    def test_two_advances_from_the_same_read_only_one_wins(self):
        self.a.advance(NAME, {'owner': 'a'}, None)
        read_a, read_b = self.a.read(NAME)[0], self.b.read(NAME)[0]
        self.assertTrue(self.b.advance(NAME, {'owner': 'b'}, read_b))
        self.assertFalse(self.a.advance(NAME, {'owner': 'a2'}, read_a), 'a stale read never overwrites')
        self.assertEqual(self.a.read(NAME)[1], {'owner': 'b'})

    def test_a_refused_transport_is_an_error_not_a_lost_race(self):
        broken = forge_git_ref.GitRefs(self.remote.root / 'a', 'nowhere')
        with self.assertRaises(forge_git_ref.GitRefError):
            broken.advance(NAME, {'owner': 'a'}, None)
        with self.assertRaises(forge_git_ref.GitRefError):
            broken.read(NAME)

    def test_a_ref_that_is_not_a_record_is_an_error(self):
        clone = self.remote.root / 'a'
        tree = git('mktree', cwd=clone)
        commit = subprocess.run(['git', 'commit-tree', tree, '-m', 'not json'], cwd=clone, input='', capture_output=True,
                                text=True, check=True, env=dict(os.environ, **self.a.identity)).stdout.strip()
        git('push', '-q', 'origin', f'{commit}:refs/heads/{NAME}', cwd=clone)
        with self.assertRaises(forge_git_ref.GitRefError):
            self.b.read(NAME)

    def test_nothing_is_deleted_or_pushed_besides_the_ref(self):
        self.a.advance(NAME, {'owner': 'a'}, None)
        self.a.read(NAME)
        self.assertEqual(self.remote.refs(), [f'refs/heads/{NAME}'])


class Append(unittest.TestCase):
    """GATE-ON-PUSH R2: a log ref (train.wake_ref) takes every producer's record, a refused fast-forward retried from a
    fresh read; the commit history is the log."""

    LOG = 'train/wake'
    ONCE = 1  # attempts: a single push
    RETRY = ONCE + 1  # a push and one retry
    FIRST, SECOND, RIVAL = {'wake': 'first'}, {'wake': 'second'}, {'wake': 'rival'}

    def setUp(self):
        self.remote = Remote(self)
        self.a, self.b = self.remote.clone('a'), self.remote.clone('b')

    def history(self):
        bare = self.remote.root / 'remote.git'
        return [json.loads(git('show', '-s', '--format=%B', sha, cwd=bare))
                for sha in git('rev-list', '--reverse', f'refs/heads/{self.LOG}', cwd=bare).split()]

    def race(self, refs, rival):
        """refs' first read returns the tip, then `rival` appends before refs pushes (a stale read)."""
        real, calls = refs.read, []

        def read(name):
            held = real(name)
            if not calls:
                rival.append(name, self.RIVAL, self.ONCE)
            calls.append(name)
            return held
        refs.read = read
        return calls

    def test_two_producers_stack_their_records_in_order(self):
        first = self.a.append(self.LOG, self.FIRST, self.RETRY)
        second = self.b.append(self.LOG, self.SECOND, self.RETRY)
        self.assertEqual(git('rev-parse', f'{second}^', cwd=self.remote.root / 'remote.git'), first)
        self.assertEqual(self.history(), [self.FIRST, self.SECOND])

    def test_a_refused_fast_forward_is_retried_from_a_fresh_read(self):
        self.a.append(self.LOG, self.FIRST, self.ONCE)
        calls = self.race(self.a, self.b)
        sha = self.a.append(self.LOG, self.SECOND, self.RETRY)
        self.assertEqual(len(calls), self.RETRY, 'one refused push, one retry')
        self.assertEqual(sha, self.remote.tip_of(self.LOG))
        self.assertEqual(self.history(), [self.FIRST, self.RIVAL, self.SECOND], "the rival's wake is kept")

    def test_tip_and_log_read_the_records_after_a_sha(self):
        self.assertIsNone(self.b.tip(self.LOG))
        self.assertEqual(self.b.log(self.LOG), [])
        first = self.a.append(self.LOG, self.FIRST, self.ONCE)
        second = self.a.append(self.LOG, self.SECOND, self.ONCE)
        self.assertEqual(self.b.tip(self.LOG), second)
        self.assertEqual(self.b.log(self.LOG, first), [(second, self.SECOND)])
        self.assertEqual(self.b.log(self.LOG), [(first, self.FIRST), (second, self.SECOND)])
        self.assertEqual(self.b.log(self.LOG, 'f' * len(first)), self.b.log(self.LOG), 'an unknown sha reads it all')

    def test_a_wake_lost_on_every_attempt_is_none_and_overwrites_nothing(self):
        self.a.append(self.LOG, self.FIRST, self.ONCE)
        self.race(self.a, self.b)
        self.assertIsNone(self.a.append(self.LOG, self.SECOND, self.ONCE))
        self.assertEqual(self.history(), [self.FIRST, self.RIVAL])

    def test_a_lost_attempt_waits_with_growing_jitter_before_the_next_and_not_after_the_last(self):
        from unittest import mock
        self.a.append(self.LOG, self.FIRST, self.ONCE)
        stale = self.a.read(self.LOG)
        self.b.append(self.LOG, self.RIVAL, self.ONCE)  # the tip moves past what a reads
        self.a.read = lambda name: stale  # every read is stale: every push loses
        slept = []
        with mock.patch.object(forge_git_ref, 'time', mock.Mock(sleep=slept.append)), \
                mock.patch.object(forge_git_ref.random, 'uniform', lambda lo, hi: hi):
            self.assertIsNone(self.a.append(self.LOG, self.SECOND, 4))
        self.assertEqual(len(slept), 3, 'between 4 attempts, not after the last')
        self.assertEqual(slept, sorted(slept))
        self.assertLessEqual(max(slept), forge_git_ref.BACKOFF_CAP)

    def test_the_backoff_is_jittered_and_capped(self):
        waits = {forge_git_ref._backoff(30) for _ in range(50)}
        self.assertGreater(len(waits), 1)
        self.assertTrue(all(0 <= w <= forge_git_ref.BACKOFF_CAP for w in waits))


class OriginRace(unittest.TestCase):
    """F29: on Origin a rival can create or move the ref between this push's advertisement and its update; the server
    refuses the push in its own words ('reference already exists'), and that refusal is a lost race (retried from a
    fresh read), while a refusal of a ref that did not move stays an error."""

    LOG = 'train/events'
    RETRY = 2  # a push and one retry
    MINE, RIVAL, FIRST = {'gate': 'mine'}, {'gate': 'rival'}, {'gate': 'first'}

    def setUp(self):
        self.origin = Origin(self)
        self.a = self.origin.clone('a')

    def history(self):
        return [json.loads(git('show', '-s', '--format=%B', sha, cwd=self.origin.bare))
                for sha in git('rev-list', '--reverse', f'refs/heads/{self.LOG}', cwd=self.origin.bare).split()]

    def test_a_create_a_rival_beat_is_retried_on_top_of_the_rival(self):
        self.origin.rival_wins_next_push(self.RIVAL)
        sha = self.a.append(self.LOG, self.MINE, self.RETRY)
        self.assertEqual(sha, self.origin.tip_of(self.LOG))
        self.assertEqual(self.history(), [self.RIVAL, self.MINE], "the rival's record is kept, mine on top")

    def test_a_fast_forward_a_rival_beat_is_retried_on_top_of_the_rival(self):
        self.a.append(self.LOG, self.FIRST, self.RETRY)
        self.origin.rival_wins_next_push(self.RIVAL)
        self.assertEqual(self.a.append(self.LOG, self.MINE, self.RETRY), self.origin.tip_of(self.LOG))
        self.assertEqual(self.history(), [self.FIRST, self.RIVAL, self.MINE])

    def test_an_advance_a_rival_beat_is_a_lost_race(self):
        self.origin.rival_wins_next_push(self.RIVAL)
        self.assertFalse(self.a.advance(self.LOG, self.MINE, None), 'a create the rival beat')
        held = self.a.read(self.LOG)[0]
        self.origin.rival_wins_next_push(self.RIVAL)
        self.assertFalse(self.a.advance(self.LOG, self.MINE, held), 'a fast-forward the rival beat')
        self.assertEqual(self.history(), [self.RIVAL, self.RIVAL])

    def test_a_refusal_of_a_ref_that_did_not_move_is_an_error_not_a_lost_race(self):
        self.a.append(self.LOG, self.FIRST, self.RETRY)
        self.origin.refuse_every_push()
        with self.assertRaisesRegex(forge_git_ref.GitRefError, ORIGIN_POLICY):
            self.a.append(self.LOG, self.MINE, self.RETRY)
        with self.assertRaisesRegex(forge_git_ref.GitRefError, ORIGIN_POLICY):
            self.a.advance('train/new', self.MINE, None)
        self.assertEqual(self.history(), [self.FIRST])

    def test_two_gates_record_their_verdicts_on_a_new_log(self):
        """PR #90: a gate's first verdict on train/events lost the create to another gate's; both verdicts land."""
        rival = {'channel': {'repo': 'o/r', 'pr': '89'}, 'events': [{'event_id': 'theirs'}]}
        gate = forge_git_ref.GitRefAdapter(self.a, self.LOG, forge_git_ref.config.get('forge-events.git_ref_attempts'))
        self.origin.rival_wins_next_push(rival)
        gate.append(Channel('o/r', '90'), [{'event_id': 'mine'}])
        self.assertEqual([e['event_id'] for e in gate.read(Channel('o/r', '90'))], ['mine'])
        self.assertEqual([e['event_id'] for e in gate.read(Channel('o/r', '89'))], ['theirs'])


class Channel:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr


class GitRefAdapterTest(unittest.TestCase):
    """EVENTS-REF (E1, D-273): the event port's log on one git ref, shared by every channel, no REST."""
    LOG = 'train/events'

    def setUp(self):
        self.remote = Remote(self)
        attempts = forge_git_ref.config.get('forge-events.git_ref_attempts')
        self.newest = ['2', '3']  # the window of recent(): the two newest of three appends
        self.a = forge_git_ref.GitRefAdapter(self.remote.clone('a'), self.LOG, attempts, window=len(self.newest))
        self.b = forge_git_ref.GitRefAdapter(self.remote.clone('b'), self.LOG, attempts, window=len(self.newest))
        self.pr = Channel('o/r', 'a')
        self.repo = Channel('o/r', None)

    def test_an_absent_log_reads_empty_and_complete(self):
        self.assertEqual(self.a.read(self.pr), [])
        self.assertEqual(self.a.recent(self.pr), ([], True))

    def test_append_then_read_from_another_clone_by_channel(self):
        self.a.append(self.pr, [{'event_id': '1', 'type': 'pr.ready'}])
        self.a.append(self.repo, [{'event_id': '2', 'type': 'train.queue.empty'}])
        self.a.append(self.pr, [{'event_id': '3', 'type': 'gate.passed'}, {'event_id': '4', 'type': 'pr.checked'}])
        self.assertEqual([e['event_id'] for e in self.b.read(self.pr)], ['1', '3', '4'])
        self.assertEqual([e['event_id'] for e in self.b.read(self.repo)], ['2'])
        self.assertEqual(self.remote.refs(), ['refs/heads/train/events'], 'one ref for every channel')

    def test_two_writers_keep_both_records(self):
        self.a.append(self.pr, [{'event_id': '1'}])
        self.b.append(self.pr, [{'event_id': '2'}])
        self.a.append(self.pr, [{'event_id': '3'}])
        self.assertEqual([e['event_id'] for e in self.b.read(self.pr)], ['1', '2', '3'])

    def test_recent_is_the_newest_window_and_says_when_it_is_partial(self):
        for number in '123':
            self.a.append(self.pr, [{'event_id': number}])
        events, complete = self.b.recent(self.pr)
        self.assertEqual(([e['event_id'] for e in events], complete), (self.newest, False))

    def test_an_empty_append_writes_nothing(self):
        self.a.append(self.pr, [])
        self.assertIsNone(self.remote.tip_of(self.LOG))

    def test_an_append_lost_on_every_attempt_raises(self):
        self.a.refs.append = lambda name, record, attempts: None
        with self.assertRaises(forge_git_ref.GitRefError):
            self.a.append(self.pr, [{'event_id': '1'}])


class Merge(unittest.TestCase):
    """FORGE-PORT (CANALE8): the vendor-independent merge pushes the merge commit to the base, fast-forward only."""
    BASE, HEAD = 'base', 'feature'

    def setUp(self):
        self.remote = Remote(self)
        self.refs = self.remote.clone('a')
        work = self.remote.root / 'work'
        git('clone', '-q', str(self.remote.root / 'remote.git'), str(work), cwd=self.remote.root)
        self.work = work
        self.commit('base.txt', 'base\n', self.BASE, new=True)
        self.head = self.commit('feature.txt', 'feature\n', self.HEAD, new=True, start=self.BASE)

    def commit(self, name, text, branch, new=False, start=None):
        if new:
            git('checkout', '-q', '--orphan' if start is None else '-b', branch, *([] if start is None else [f'origin/{start}']),
                cwd=self.work)
        else:
            git('checkout', '-q', branch, cwd=self.work)
        (self.work / name).write_text(text)
        git('add', name, cwd=self.work)
        git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', name, cwd=self.work)
        git('push', '-q', 'origin', f'HEAD:refs/heads/{branch}', cwd=self.work)
        return git('rev-parse', 'HEAD', cwd=self.work)

    def test_a_clean_merge_is_pushed_as_a_merge_commit_of_both(self):
        before = self.remote.tip_of(self.BASE)
        merged = self.refs.merge(self.BASE, self.HEAD, self.head, 'Merge feature')
        self.assertEqual(self.remote.tip_of(self.BASE), merged)
        parents = git('rev-list', '--parents', '-n', '1', merged, cwd=self.remote.root / 'remote.git').split()[1:]
        self.assertEqual(parents, [before, self.head])

    def test_a_head_that_moved_since_it_was_judged_is_refused(self):
        self.commit('more.txt', 'more\n', self.HEAD)
        with self.assertRaisesRegex(forge_git_ref.GitRefError, 'not the head'):
            self.refs.merge(self.BASE, self.HEAD, self.head, 'Merge feature')

    def test_a_conflict_is_refused_and_the_base_is_untouched(self):
        self.commit('feature.txt', 'base side\n', self.BASE)
        before = self.remote.tip_of(self.BASE)
        with self.assertRaisesRegex(forge_git_ref.GitRefError, 'does not merge cleanly'):
            self.refs.merge(self.BASE, self.HEAD, self.head, 'Merge feature')
        self.assertEqual(self.remote.tip_of(self.BASE), before)

    def test_a_base_that_moved_meanwhile_is_a_lost_race_not_a_force_push(self):
        real = self.refs.read_tip
        rival = {'done': False}

        def stale(name):
            tip = real(name)
            if name == self.BASE and not rival['done']:
                rival['done'] = True
                self.commit('rival.txt', 'rival\n', self.BASE)  # the base moves after this merge read it
            return tip
        self.refs.read_tip = stale
        self.assertIsNone(self.refs.merge(self.BASE, self.HEAD, self.head, 'Merge feature'))
        moved = self.remote.tip_of(self.BASE)
        self.assertEqual(git('log', '-1', '--format=%s', moved, cwd=self.remote.root / 'remote.git'), 'rival.txt')


if __name__ == '__main__':
    unittest.main()
