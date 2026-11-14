"""Verdict admission in the train (D-075 as amended; P-53, P-54): train_verdict, the verdict branch of Train.drain,
with the train's own resync under the requeue fallback (Daniel 15:02: updating the base is the train's work).

TX24: one file per feature; fixtures in scripts/tests/test_train.py, the trusted forge in test_train_reuse.py. Each PR
carries a cold v4 gate.passed made by the real producer (gate_proof.bind + proof_payload) on the tip it branched from.
"""
import contextlib
import io
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import REPO, Fixture, setUpModule  # noqa: E402,F401
from test_train_reuse import TOOLCHAIN, TrustedForge  # noqa: E402
import config  # noqa: E402
import engine_role  # noqa: E402
import forge_events  # noqa: E402
import gate_proof  # noqa: E402
import train  # noqa: E402
import train_verdict  # noqa: E402

PASSED, FAILED = 'PASSED', 'FAILED'
ROOT = engine_role.ROOT  # the checkout whose scripts/ judge (gate_version), as on the train


class ReleaseCount(unittest.TestCase):
    def test_prs_since_release_counts_from_the_last_release(self):
        events = [{'type': 'integration.advanced', 'payload': {'prs': [1, 2]}},
                  {'type': 'release.ready', 'payload': {}}, {'type': 'integration.advanced', 'payload': {'prs': [3]}}]
        self.assertEqual(train_verdict.prs_since_release(events), 1)


class FakeReverdict:
    """The gate API as the train calls it: PASSED publishes a cold verdict of the head on the current tip and its
    pr.ready (what scripts/gate-verdict --cold --pr does through gate-local); FAILED prints its red lines; any other
    answer is the UNOBSERVABLE exit."""

    def __init__(self, test):
        self.test, self.calls, self.answer, self.red = test, [], PASSED, [('unit tests', 'code')]
        self.answers = {}  # pr: answer, over self.answer
        self.lock = threading.Lock()  # the fake publishes through one git workspace; the real gates are processes
        self.reasons = ['test_x: expected 3']

    def run(self, pr, head):
        with self.lock:
            return self.answer_for(pr, head, self.answers.get(pr, self.answer))

    def answer_for(self, pr, head, answer):
        self.calls.append((pr, head))
        if answer == PASSED:
            self.test.publish(pr, head, self.test.workspace.tip(self.test.base_branch))
            return 0, f'verdict PASSED {head}\n'
        if answer == FAILED:
            return 1, (f'verdict FAILED {head}\n' + ''.join(f'red {stage}: {kind}\n' for stage, kind in self.red)
                       + ''.join(f'reason {line}\n' for line in self.reasons))
        return config.get('gate.verdict_unobservable_exit_code'), f'verdict UNOBSERVABLE {head} the gate could not run\n'


class Verdict(Fixture):
    settings = {'train.admit_mode': 'verdict', 'train.verdict_fallback': 'requeue', 'train.shard_admit': 'off',
                'train.reverdict_parallel': 1}

    def setUp(self):
        super().setUp()
        self.forge = TrustedForge(self.origin)
        self.gate_port = forge_events.ForgeEvents(self.forge, self.clock, 'gate_report', 'run-1')
        self.lane_port = forge_events.ForgeEvents(self.forge, self.clock, 'pr-ready', 'lane-1')
        self.use(**self.settings)

    def use(self, **values):
        """The train as the shared store would set it: `values` over the registry, read when the train is built."""
        real = engine_role.setting
        patch = mock.patch.object(engine_role, 'setting', lambda key: values[key] if key in values else real(key))
        patch.start()
        self.addCleanup(patch.stop)
        self.train = train.Train(self.forge, self.clock, self.workspace, self.gate, REPO)
        self.train.reuse.toolchain_id = lambda: TOOLCHAIN
        self.gate_api = self.train.reverdict = FakeReverdict(self)
        self.head_leg = self.train.self_host_leg = FakeSelfHost()

    def verdict_pr(self, files, base=None, cache_hits=0, toolchain=TOOLCHAIN):
        """A PR from `base` (default: the first tip) with a verified verdict on that base (cold unless `cache_hits`),
        and its pr.ready."""
        base = base or self.base
        number = max(self.forge.open + self.forge.merges, default=0) + 1
        self.run_git(self.seed, 'checkout', '--quiet', '-B', f'pr-{number}', base)
        self.write(files)
        head = self.commit(f'pr {number}')
        self.run_git(self.seed, 'push', '--quiet', '--force', str(self.origin), f'HEAD:refs/heads/pr-{number}')
        self.forge.open.append(number)
        self.publish(number, head, base, cache_hits, toolchain)
        return number, head

    def publish(self, number, head, base, cache_hits=0, toolchain=TOOLCHAIN):
        """A verified v4 verdict of `head` on `base` by the real producer, and the pr.ready that rests on it."""
        self.workspace.fetch(head)
        binding = gate_proof.bind(self.work, ROOT, head, base, train_verdict.PLAN, None, toolchain_id=toolchain)
        verdict = dict(forge_events.subject(REPO, number, head, ['P-53']), tier=1, plan=train_verdict.PLAN, stages=[],
                       missing_stages=[], input_hash=binding['input_digest'])
        proof = gate_proof.proof_payload(verdict, {'stages': [], 'sha': head}, binding, self.dir)
        proof['cost']['cache_hits'] += cache_hits
        event = self.gate_port.emit('gate.passed', proof, gate_proof.proof_version())
        self.ready(number, head, evidence=event['event_id'])

    def toolchain_pr(self, toolchain='another-box'):
        """A PR on the tip whose verdict came from another machine: the head contains the tip (#805, 29/10)."""
        number = max(self.forge.open + self.forge.merges, default=0) + 1
        self.run_git(self.seed, 'checkout', '--quiet', '-B', f'pr-{number}', self.base)
        self.write({'c.txt': 'one\n'})
        head = self.commit(f'pr {number}')
        self.run_git(self.seed, 'push', '--quiet', '--force', str(self.origin), f'HEAD:refs/heads/pr-{number}')
        self.forge.open.append(number)
        self.publish(number, head, self.base, toolchain=toolchain)
        return number, head

    def drain(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            outcome = self.train.drain(self.train.port('test'))
        return outcome, printed.getvalue()

    def batch_ids(self, kind):
        return [event['payload']['batch_id'] for event in self.events(kind=kind)]

    def parents(self, number):
        return self.run_git(self.origin, 'rev-list', '--parents', '-n', '1', f'refs/heads/pr-{number}').split()[1:]

    def measured(self, step):
        return [event['payload']['result'] for event in self.events(kind='engine.step.measured')
                if event['payload']['step'] == engine_role.setting('train.step_prefix') + step]


class FakeSelfHost:
    """train_verdict.SelfHostLeg as the train calls it: the head's own tooling answers `passed`."""

    def __init__(self, passed=True):
        self.passed, self.calls, self.output = passed, [], {}

    def run(self, head):
        self.calls.append(head)
        self.output[head] = 'noise\nnoise\n' + ('gate-local: pass' if self.passed else 'FAIL unit tests (exit 1)\nlast line')
        return self.passed, 'exit 0' if self.passed else 'exit 1: FAIL unit tests'


class Strict(Verdict):
    def test_a_ready_pr_with_an_exact_cold_verdict_merges_alone_with_zero_tier2_runs(self):
        """(a) P-53: the tested tree is the merged tree."""
        number, head = self.verdict_pr({'c.txt': 'one\n'})
        self.assertEqual(self.drain()[0], 'drained')
        self.assertEqual((self.forge.merges, self.gate.runs, self.gate_api.calls), ([number], [], []))
        [bid] = self.batch_ids('pr.merged')
        self.assertTrue(bid.startswith(train_verdict.VERDICT))
        self.assertEqual(self.batch_ids('integration.advanced'), [bid])
        self.assertEqual(self.measured('admit'), ['ok'])
        self.assertEqual(self.workspace.tree(self.workspace.tip(self.base_branch)), self.workspace.tree(head))

    def test_the_merge_alone_reads_only_the_newest_window_of_the_repository_log(self):
        """A channel past forge-events.github_max_pages (#548): integration.advanced counts the window, never raises."""
        number, _ = self.verdict_pr({'c.txt': 'one\n'})
        read, windows = self.forge.read, []

        def whole(channel):
            if channel.pr is None:
                self.fail('a post-merge read took the whole repository channel')
            return read(channel)

        self.forge.read = whole
        self.forge.recent = lambda channel: windows.append(channel) or ([], False)
        self.assertEqual(self.drain()[0], 'drained')
        self.forge.read = read
        self.assertEqual(self.forge.merges, [number])
        self.assertTrue(windows)
        [advanced] = self.events(kind='integration.advanced')
        self.assertEqual((advanced['payload']['prs'], advanced['payload']['prs_since_release']), ([number], 1))

    def test_batch_mode_is_unchanged(self):
        """(e) the one-key rollback: tier 2 judges the batch and no PR merges on its verdict."""
        self.use(**dict(self.settings, **{'train.admit_mode': 'batch'}))
        self.verdict_pr({'c.txt': 'one\n'})
        self.drain()
        self.assertEqual(len(self.gate.runs), 1)
        self.assertTrue(all(bid.startswith('b-') for bid in self.batch_ids('pr.merged')))
        self.assertEqual(self.measured('admit'), [])

    def test_a_clean_merge_the_forge_refuses_stays_queued_for_the_next_run(self):
        """(c) D-078: a forge refusal of a pinned head that merges cleanly is not a conflict; it leaves this run's
        queue (no loop) with no event and the next run takes it again."""
        number, _ = self.verdict_pr({'c.txt': 'one\n'})
        self.forge.refuse.add(number)
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges, self.events(number, 'pr.conflicted')), ('drained', [], []))
        self.assertIn('the forge refused the merge', printed)
        self.assertIn('it stays queued', printed)
        self.forge.refuse.clear()
        self.use(**self.settings)  # the next run: a new train
        self.drain()
        self.assertEqual(self.forge.merges, [number])

    def test_a_head_that_moved_before_the_merge_waits_for_its_next_ready_with_no_event(self):
        """(c) the pin: the owner pushed after the queue read; the forge refuses the old sha and nothing is emitted."""
        number, _ = self.verdict_pr({'c.txt': 'one\n'})
        real = self.forge.merge

        def push_then_merge(repo, pr, sha):
            self.write({'e.txt': 'later\n'})
            self.run_git(self.seed, 'push', '--quiet', '--force', str(self.origin),
                         f'{self.commit("owner push")}:refs/heads/pr-{pr}')
            return real(repo, pr, sha)
        with mock.patch.object(self.forge, 'merge', side_effect=push_then_merge):
            outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges, self.events(number, 'pr.conflicted')), ('drained', [], []))
        self.assertIn('its head moved', printed)

    def test_the_guard_never_builds_a_conflict_with_no_file(self):
        """D-078: #805's 19:27Z event (pr.conflicted, files []) cannot be built any more."""
        number, head = self.toolchain_pr()
        subject = forge_events.subject(REPO, number, head, ['P-53'], None)
        with self.assertRaisesRegex(ValueError, 'no conflicting file'):
            train_verdict.conflicted(subject, self.base, 'toolchain x is not the attested y', [])
        built = train_verdict.conflicted(subject, self.base, 'does not merge', ['b.txt', 'a.txt'])
        self.assertEqual((built['cause'], built['files']), ('textual', ['a.txt', 'b.txt']))

    def test_a_refused_pinned_head_that_conflicts_with_the_tip_names_its_files(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, head = self.verdict_pr({'c.txt': 'other\n'})
        self.drain()  # the first merges; the second conflicts at its resync
        self.assertEqual(self.forge.merges, [first])
        tip = self.workspace.tip(self.base_branch)
        entry = train.train_queue.Entry(second, head, None, ('P-53',), 'lane', '2026-10-29T19:27:44Z', None)
        with contextlib.redirect_stdout(io.StringIO()):
            self.train.refused(self.train.port('test'), entry, tip, RuntimeError('not mergeable'))
        conflicted = self.events(second, 'pr.conflicted')
        self.assertTrue(conflicted and all(event['payload']['files'] == ['c.txt'] for event in conflicted))

    def test_a_merged_tree_other_than_the_verdict_tree_halts(self):
        """(d) the tree proof: the forge merged something else."""
        self.verdict_pr({'c.txt': 'one\n'})
        real = self.forge.merge
        with mock.patch.object(self.forge, 'merge', side_effect=lambda *args: real(*args) and self.base):
            with self.assertRaisesRegex(train.TrainHalt, 'tree proof failed'):
                self.drain()

    def test_a_moved_tip_with_the_tier2_fallback_runs_a_batch_of_one(self):
        """(b) tier2: today's path, one tier-2 run on the tip, no resync."""
        self.use(**dict(self.settings, **{'train.verdict_fallback': 'tier2'}))
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        self.drain()
        self.assertEqual((self.forge.merges, len(self.gate.runs), self.gate_api.calls), ([first, second], 1, []))
        self.assertTrue(self.batch_ids('pr.merged')[1].startswith('b-'))


class Shards(Verdict):
    """P-54: a verdict on an older tip still admits when the base moved only outside the PR's shard."""

    def two(self, second_files):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr(second_files)
        outcome, printed = self.drain()
        self.assertEqual(outcome, 'drained')
        return first, second, printed

    def test_on_admits_a_disjoint_pr_behind_the_tip_without_resync_or_reverdict(self):
        self.use(**dict(self.settings, **{'train.shard_admit': 'on'}))
        first, second, _ = self.two({'d.txt': 'two\n'})
        self.assertEqual((self.forge.merges, self.gate.runs, self.gate_api.calls), ([first, second], [], []))
        self.assertTrue(self.batch_ids('pr.merged')[1].startswith(train_verdict.SHARD))
        tip = self.workspace.tip(self.base_branch)
        self.assertEqual(sorted(self.run_git(self.work, 'ls-tree', '--name-only', tip).split()),
                         sorted(['README', 'a.txt', 'b.txt', 'c.txt', 'd.txt']))

    def test_shadow_measures_a_would_admit_and_resyncs_as_if_it_did_not_exist(self):
        self.use(**dict(self.settings, **{'train.shard_admit': 'shadow'}))
        first, second, printed = self.two({'d.txt': 'two\n'})
        self.assertEqual(self.measured('shard-admit'), ['ok'])
        self.assertIn(f'#{second} shard shadow', printed)
        self.assertIn('would admit', printed)
        self.assertEqual((self.forge.merges, len(self.gate_api.calls)), ([first, second], 1))
        self.assertTrue(self.batch_ids('pr.merged')[1].startswith(train_verdict.VERDICT))

    def test_a_collision_resyncs_even_when_on(self):
        self.use(**dict(self.settings, **{'train.shard_admit': 'on'}))
        first, second, printed = self.two({'c.txt': 'one\n', 'e.txt': 'three\n'})
        self.assertIn('overlap on path:c.txt', printed)
        self.assertEqual(self.measured('shard-admit'), ['blocked'])
        self.assertEqual((self.forge.merges, len(self.gate_api.calls)), ([first, second], 1))

    def test_off_never_computes_the_shard(self):
        first, second, printed = self.two({'d.txt': 'two\n'})
        self.assertEqual(self.measured('shard-admit'), [])
        self.assertIn('not the tip', printed)


class SelfHostLegOutput(unittest.TestCase):
    """D-082 (the leg exited 1 on #804, #809 and #810 and only its last line was kept): a red leg names its FAIL and
    class lines and keeps its whole output in train.trigger_log_dir."""

    def test_a_red_leg_keeps_its_whole_output_and_names_its_fail_lines(self):
        import hashlib
        import os
        import stat
        import tempfile
        import gate_pin
        head, prefix = hashlib.sha1(b'head').hexdigest(), engine_role.setting('gate.class_line_prefix')
        lines = [f'noise {word}' for word in 'a long run of output before the cause'.split()] + [
            'FAIL unit tests (exit 1; log: u.log)', f'{prefix} unit tests\tcode', 'FAIL a later stage', 'gate-local: done']
        with tempfile.TemporaryDirectory() as tmp:
            root, tool = Path(tmp) / 'train', Path(tmp) / 'head'
            (tool / 'scripts').mkdir(parents=True)
            root.mkdir()
            script = tool / 'scripts' / 'leg'
            script.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n" + '\n'.join(lines) + '\nEOF\nexit 1\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            leg = train_verdict.SelfHostLeg(root)
            leg.command = ['scripts/leg']
            with mock.patch.object(gate_pin, 'head_tooling', return_value=(str(tool), None)), \
                    mock.patch.object(gate_pin, 'report_env', return_value=dict(os.environ)), \
                    mock.patch.object(gate_pin, 'gate_version', return_value='v'), \
                    mock.patch.object(gate_pin, 'drop'):
                passed, why = leg.run(head)
            log = root / engine_role.setting('train.trigger_log_dir') / f'self-host-{head}.log'
            self.assertFalse(passed)
            self.assertTrue(why.startswith('exit 1: gate-local: done; FAIL unit tests (exit 1'))
            self.assertIn(f'{prefix} unit tests', why)
            self.assertNotIn('a later stage', why)
            self.assertIn(f'(full output: {log.relative_to(root)})', why)
            self.assertEqual(log.read_text().splitlines(), lines)
            self.assertEqual(leg.output[head].splitlines(), lines)


if __name__ == '__main__':
    unittest.main()
