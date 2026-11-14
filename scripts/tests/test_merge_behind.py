"""The merge rule of merge-phase (GX-22, from BD1): pure decisions, a fake forge port, throwaway git checkouts and the in-memory
event log; no network."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import merge_behind  # noqa: E402

MAX = config.get('merge.max_behind_base')
OVERLAP = config.get('merge.regate_on_overlap')
SOME = MAX + 1

sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from test_plan_tick import REPO, SHA, FixedClock, gate_passed  # noqa: E402 - the plan-tick verdict fixtures, shared

PR = gate_passed(SHA)['pr']
OTHER = 'b' * len(SHA)


class DecideTest(unittest.TestCase):
    def test_not_behind_merges(self):
        self.assertTrue(merge_behind.decide(0, [], MAX, OVERLAP)[0])

    def test_within_max_without_overlap_merges(self):
        self.assertTrue(merge_behind.decide(MAX, [], MAX, OVERLAP)[0])

    def test_beyond_max_is_refused_with_the_reason(self):
        self.assertEqual(merge_behind.decide(SOME, [], MAX, True), (False, f're-gate: {SOME} behind, limit {MAX}'))

    def test_overlap_is_refused_even_within_max(self):
        self.assertEqual(merge_behind.decide(1, ['a/b.ts'], MAX, True),
                         (False, f're-gate: 1 behind, limit {MAX}, overlapping changes (a/b.ts)'))

    def test_overlap_ignored_when_the_rule_is_off(self):
        self.assertTrue(merge_behind.decide(1, ['a/b.ts'], MAX, False)[0])

    def test_the_limit_is_the_registered_one_and_never_looser_than_the_practice_of_regating_on_overlap(self):
        self.assertIs(OVERLAP, True)
        self.assertFalse(merge_behind.decide(SOME, [], MAX, OVERLAP)[0])
        self.assertTrue(merge_behind.decide(MAX, [], MAX, OVERLAP)[0])

    def test_the_paths_named_in_the_reason_are_capped_by_the_registry(self):
        room = config.get('merge.paths_shown')
        names = [f'p{n}' for n in range(room + 1)]
        reason = merge_behind.decide(1, names, MAX, True)[1]
        self.assertIn(f'+{len(names) - room} more', reason)


    def test_the_verdict_line_names_the_registry_limit(self):
        self.assertEqual(merge_behind.decide(MAX, [], MAX, OVERLAP), (True, f'{MAX} behind, limit {MAX}, no overlapping changes'))
        self.assertEqual(merge_behind.limit_line(SOME, MAX), f'{SOME} behind, limit {MAX}')


class Journal(forge_events.MemoryAdapter):
    """The memory journal with merge_behind's whole surface: the evidence read never asks the compare."""

    def compare(self, *args):
        raise AssertionError('the evidence read asked the forge for a compare')


class EvidenceTest(unittest.TestCase):
    """The proof is the GX-37 event log of the PR channel: a gate.passed of the exact head, per plan; no local file."""

    def setUp(self):
        # the memory journal is a test double with no compatibility proof; merge_behind's demand (compare) is the
        # port's to check against a real forge, not this read's (the pattern of test_pr_ready)
        patcher = unittest.mock.patch.object(forge_events, '_require_compatibility')
        patcher.start()
        self.addCleanup(patcher.stop)

    def port(self, adapter):
        return forge_events.ForgeEvents(adapter, FixedClock(), config.get('forge-events.gate_producer'), 'gate:dev:run')

    def test_a_pass_of_the_exact_head_is_the_proof_per_plan(self):
        port = self.port(Journal())
        dev = port.emit('gate.passed', gate_passed(SHA, 'dev', PR))
        db = port.emit('gate.passed', gate_passed(SHA, 'db', PR))
        port.emit('gate.passed', gate_passed(OTHER, 'noite', PR))
        port.emit('gate.failed', gate_passed(SHA, 'noite', PR))
        found = merge_behind.evidence(merge_behind.read_log(REPO, PR, port=port), PR, SHA)
        self.assertEqual(found, {'db': db['event_id'], 'dev': dev['event_id']})

    def test_another_prs_pass_or_a_later_failure_is_no_proof(self):
        port = self.port(Journal())
        port.emit('gate.passed', gate_passed(SHA, 'dev', PR + 1))
        self.assertEqual(merge_behind.evidence(port.read(REPO, PR), PR, SHA), {})
        port.emit('gate.passed', gate_passed(SHA, 'dev', PR))
        port.emit('gate.failed', gate_passed(SHA, 'dev', PR))
        self.assertEqual(merge_behind.evidence(port.read(REPO, PR), PR, SHA), {})


class ComparePort:
    """The forge port's compare: one standing for every span, and the spans it was asked for."""

    def __init__(self, behind_by, merge_base='mb'):
        self.standing, self.seen = {'behind_by': behind_by, 'merge_base': merge_base}, []

    def compare(self, repo, base, head):
        self.seen.append((repo, base, head))
        return dict(self.standing)


class MeasureTest(unittest.TestCase):
    """measure() against a fake port: the overlap is what both sides changed since the merge base; an unreadable side refuses."""

    def diff(self, spans):
        return lambda old, new: spans.get(f'{old}...{new}')

    def test_overlap_is_the_intersection_of_the_paths_each_side_changed(self):
        port = ComparePort(SOME)
        found = merge_behind.measure(port, REPO, 'head', 'base', self.diff({'mb...head': {'p0', 'p1'}, 'mb...base': {'p1', 'z'}}))
        self.assertEqual(found, (SOME, ['p1']))
        self.assertEqual(port.seen, [(REPO, 'base', 'head')])

    def test_a_head_not_behind_reads_no_paths(self):
        self.assertEqual(merge_behind.measure(ComparePort(0), REPO, 'head', 'base', self.diff({})), (0, []))

    def test_a_side_the_checkout_cannot_read_cannot_be_proven_and_raises(self):
        with self.assertRaises(RuntimeError):
            merge_behind.measure(ComparePort(1), REPO, 'head', 'base', self.diff({'mb...head': {'p'}}))

    def test_the_local_diff_names_the_paths_between_two_commits_and_none_for_an_unknown_one(self):
        root = Path(tempfile.mkdtemp())
        git = lambda *args: subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
        git('init', '-q')
        identity = ['-c', 'user.name=t', '-c', 'user.email=t@t.invalid', '-c', 'commit.gpgsign=false']
        (root / 'a').write_text('1')
        git('add', 'a')
        git(*identity, 'commit', '-q', '-m', 'one')
        first = git('rev-parse', 'HEAD')
        (root / 'b').write_text('2')
        git('add', 'b')
        git(*identity, 'commit', '-q', '-m', 'two')
        diff = merge_behind.local_diff(root)
        self.assertEqual(diff(first, git('rev-parse', 'HEAD')), {'b'})
        self.assertIsNone(diff(first, 'f' * len(SHA)))

    def test_the_cli_measures_through_the_port_of_this_consumer(self):
        port = ComparePort(0)
        with mock.patch.object(merge_behind, 'forge', return_value=port) as built, mock.patch('builtins.print'):
            code = merge_behind.main(['behind', '--pr', str(PR), '--sha', 'head', '--base-sha', 'base', '--repo', REPO])
        self.assertEqual((code, port.seen), (0, [(REPO, 'base', 'head')]))
        built.assert_called_once_with(PR)

    def test_the_default_port_names_this_module_as_its_consumer(self):
        with mock.patch.object(forge_events, 'ForgeEvents', side_effect=lambda *args, **kwargs: kwargs), \
                mock.patch.object(forge_events, 'adapter_from_config'), mock.patch.object(forge_events, 'clock_from_config'):
            self.assertEqual(merge_behind.forge(PR)['consumer'], 'scripts/lib/merge_behind.py')




if __name__ == '__main__':
    unittest.main()
