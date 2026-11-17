"""pr.ready after a passed gate (EVENTS.md, D-065): pr_ready.ready_after_gate and the gate_report hook. Fixtures, temporary
repositories and the in-memory forge adapter, no network."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / 'lib'))

import config  # noqa: E402
import forge_events  # noqa: E402
import gate_report  # noqa: E402
import plan_tick  # noqa: E402
import pr_ready  # noqa: E402

sys.path.insert(0, str(TESTS))
from test_plan_tick import SHA, FixedClock, gate_passed, git  # noqa: E402,F401 - the plan-tick fixtures, shared
from test_gate_v4_readers import V4, v4_payload  # noqa: E402 - the v4 verdict fixture, shared

REPO = config.get('forge-events.repo')
PR = gate_passed(SHA)['pr']  # the plan-tick fixture's PR
PLAN = config.get('plan-tick.required_gate_kind')
BODY = '## Commit plan\n- [ ] 1. Add the parser.\n- [ ] 2. Add the reader.\n- [ ] 3. Wire the CLI.\n\nPremises: P-18\n'
def make_repo(root, messages):
    """A checkout with base-ref and one commit per message; returns the HEAD sha."""
    git(root, 'init', '-q', '-b', 'main')
    (root / 'f').write_text('base\n')
    git(root, 'add', 'f')
    git(root, 'commit', '-q', '-m', 'Base')
    git(root, 'branch', 'base-ref')
    for index, message in enumerate(messages):
        (root / 'f').write_text(f'{index}\n')
        git(root, 'commit', '-qam', message)
    return git(root, 'rev-parse', 'HEAD').strip()


TICKED = ['One\n\nPlan: 1\n', 'Two\n\nPlan: 2, 3\n']


def verdict_payload(sha, plan=PLAN):
    return gate_passed(sha, plan, PR)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.adapter = forge_events.MemoryAdapter({(REPO, PR): {'body': BODY}})
        self.gate = forge_events.ForgeEvents(self.adapter, FixedClock(), config.get('forge-events.gate_producer'),
                                             'gate:dev:run')
        self.port = forge_events.ForgeEvents(self.adapter, FixedClock(), config.get('plan-tick.event_producer'),
                                             f'pr-{PR}')

    def head(self, messages=TICKED):
        sha = make_repo(self.root, messages)
        self.adapter.changes[(REPO, PR)] = {'body': BODY, 'base': git(self.root, 'rev-parse', 'base-ref').strip()}
        return sha

    def ready(self, sha, body=BODY, plan=None):
        return pr_ready.ready_after_gate(self.port, REPO, PR, sha, body, self.root, plan=plan, base='base-ref')

    def readies(self):
        return [event for event in self.port.read(REPO, PR) if event['type'] == 'pr.ready']


class ReadyAfterGate(Fixture):
    def test_a_pass_on_the_exact_head_with_a_ticked_plan_emits_pr_ready(self):
        sha = self.head()
        passed = self.gate.emit('gate.passed', verdict_payload(sha))
        event, reason = self.ready(sha)
        self.assertEqual(reason, 'ready')
        self.assertEqual(event['type'], 'pr.ready')
        self.assertEqual(event['producer'], config.get('plan-tick.event_producer'))
        self.assertEqual(event['payload']['evidence'], passed['event_id'])
        self.assertEqual(event['payload']['premises'], ['P-18'])

    def test_the_unit_of_the_change_rides_on_pr_ready_and_is_null_without_one(self):
        sha = self.head()
        self.gate.emit('gate.passed', verdict_payload(sha))
        named = pr_ready.emit_ready(self.port, REPO, PR, sha, [], config.get('plan-tick.required_gate_kind'),
                                    unit='gx-05', events=self.gate.read(REPO, PR))
        self.assertEqual(named['payload']['unit'], 'gx-05')
        self.assertIsNone(pr_ready.unit_of(self.root, 'base-ref', sha), 'the fixture repository has no unit manifest')

    def test_a_second_call_is_a_no_op(self):
        sha = self.head()
        self.gate.emit('gate.passed', verdict_payload(sha))
        first, _ = self.ready(sha)
        second, _ = self.ready(sha)
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(len(self.readies()), 1)

    def test_an_unticked_plan_is_not_ready(self):
        sha = self.head(['One\n\nPlan: 1\n'])
        self.gate.emit('gate.passed', verdict_payload(sha))
        event, reason = self.ready(sha)
        self.assertIsNone(event)
        self.assertIn('items not ticked by a commit: 2, 3', reason)
        self.assertEqual(self.readies(), [])

    def test_a_head_the_checkout_does_not_hold_is_not_ready(self):
        self.head()
        other = 'b' * len(SHA)
        self.gate.emit('gate.passed', verdict_payload(other))
        event, reason = self.ready(other)
        self.assertIsNone(event)
        self.assertIn('is not a commit of the checkout', reason)
        self.assertEqual(self.readies(), [])

    def test_a_gate_run_from_a_checkout_not_on_the_head_emits_pr_ready(self):
        sha = self.head()
        git(self.root, 'checkout', '-q', '--detach', 'base-ref')  # the subject checkout is not on the head either
        tool = tempfile.TemporaryDirectory()
        self.addCleanup(tool.cleanup)
        make_repo(Path(tool.name), ['Tool\n'])  # the tool checkout: another repository, its own HEAD
        self.gate.emit('gate.passed', verdict_payload(sha))
        with unittest.mock.patch.dict('os.environ', {'OU_SUBJECT_ROOT': str(self.root)}):
            event, reason = pr_ready.ready_after_gate(self.port, REPO, PR, sha, BODY, pr_ready.ROOT, base='base-ref')
        self.assertEqual(reason, 'ready')
        self.assertEqual(event['payload']['sha'], sha)
        self.assertEqual(len(self.readies()), 1)

    def test_an_explicit_root_wins_over_the_exported_subject_root(self):
        sha = self.head()
        self.gate.emit('gate.passed', verdict_payload(sha))
        with unittest.mock.patch.dict('os.environ', {'OU_SUBJECT_ROOT': str(self.root / 'missing')}):
            event, reason = self.ready(sha)
        self.assertEqual(reason, 'ready')

    def test_a_stale_local_base_ref_changes_nothing(self):
        sha = self.head()
        git(self.root, 'branch', '-f', 'base-ref', sha)  # stale: the local ref now equals the head, base..HEAD is empty
        self.gate.emit('gate.passed', verdict_payload(sha))
        event, reason = self.ready(sha)
        self.assertEqual(reason, 'ready')

    def test_the_lane_is_derived_at_the_recorded_base(self):
        sha = self.head()
        recorded = self.adapter.changes[(REPO, PR)]['base']
        self.gate.emit('gate.passed', verdict_payload(sha))
        seen = []
        with unittest.mock.patch.object(pr_ready, 'lane_of', lambda root, base, head: seen.append((base, head)) or 'lane-x'):
            event, _ = self.ready(sha)
        self.assertEqual(seen, [(recorded, sha)])
        self.assertEqual(event['payload']['lane_id'], 'lane-x')

    def test_a_forge_without_a_base_falls_back_to_the_configured_ref_and_reports_it(self):
        sha = self.head()
        self.adapter.changes[(REPO, PR)] = {'body': BODY}
        self.gate.emit('gate.passed', verdict_payload(sha))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            event, reason = self.ready(sha)
        self.assertIsNotNone(event)
        self.assertIn('records no base', reason)
        self.assertIn('records no base', err.getvalue())

    def test_another_plan_or_no_passed_gate_is_not_ready(self):
        sha = self.head()
        self.gate.emit('gate.failed', verdict_payload(sha))
        event, reason = self.ready(sha)
        self.assertIsNone(event)
        self.assertIn('no passed', reason)
        other = 'noite' if PLAN != 'noite' else 'db'
        event, reason = self.ready(sha, plan=other)
        self.assertIsNone(event)
        self.assertIn(f'not the {PLAN} gate', reason)
        self.assertEqual(self.readies(), [])


RETRO_BODY = BODY.replace('\n\nPremises', '\n- [ ] 4. Write the retro.\n\nPremises')
RETRO_FILE = 'docs/retro.md'


class CarriedProof(Fixture):
    """GX-20: a head whose passed v4 verdict carries the proof of an earlier head (carried_from)."""
    def retro(self):
        """(green head, its v4 gate.passed, RETRO head): the RETRO commit adds a docs file and ticks item 4."""
        green = self.head()
        passed = self.gate.emit('gate.passed', v4_payload(green), version=V4)
        (self.root / 'docs').mkdir()
        (self.root / RETRO_FILE).write_text('retro\n')
        git(self.root, 'add', RETRO_FILE)
        git(self.root, 'commit', '-qm', 'Retro\n\nPlan: 4\n')
        return green, passed, git(self.root, 'rev-parse', 'HEAD').strip()

    def carry(self, sha, origin, event_id, files=(RETRO_FILE,)):
        payload = v4_payload(sha)
        payload['carried_from'] = {'event_id': event_id, 'sha': origin, 'delta_files': list(files)}
        return self.gate.emit('gate.passed', payload, version=V4)

    def test_the_retro_item_is_satisfied_by_the_carried_proof(self):
        green, passed, head = self.retro()
        verdict = self.carry(head, green, passed['event_id'])
        event, reason = self.ready(head, body=RETRO_BODY)
        self.assertEqual(reason, f'ready (item 4 satisfied by the carried proof of {passed["event_id"]})')
        self.assertEqual(event['payload']['evidence'], verdict['event_id'])
        self.assertEqual(len(self.readies()), 1)

    def test_a_carried_proof_whose_delta_differs_from_git_is_refused(self):
        green, passed, head = self.retro()
        self.carry(head, green, passed['event_id'], files=(RETRO_FILE, 'docs/other.md'))
        event, reason = self.ready(head, body=RETRO_BODY)
        self.assertIsNone(event)
        self.assertTrue(reason.startswith('carried proof'), reason)
        self.assertIn('does not match the delta', reason)
        self.assertEqual(self.readies(), [])

    def test_a_carried_proof_from_a_head_that_is_not_an_ancestor_is_refused(self):
        green, passed, head = self.retro()
        git(self.root, 'checkout', '-q', '-b', 'side', 'base-ref')
        (self.root / 'side').write_text('side\n')
        git(self.root, 'add', 'side')
        git(self.root, 'commit', '-qm', 'Side')
        side = git(self.root, 'rev-parse', 'HEAD').strip()
        self.carry(head, side, passed['event_id'])
        event, reason = self.ready(head, body=RETRO_BODY)
        self.assertIsNone(event)
        self.assertEqual(reason, f'carried proof: {pr_ready.short(side)} is not an ancestor of {pr_ready.short(head)}')
        self.assertEqual(self.readies(), [])

    def test_a_passed_v4_verdict_that_carries_nothing_is_unchanged(self):
        sha = self.head()
        passed = self.gate.emit('gate.passed', v4_payload(sha), version=V4)
        event, reason = self.ready(sha)
        self.assertEqual(reason, 'ready')
        self.assertEqual(event['payload']['evidence'], passed['event_id'])
        self.assertIsNone(pr_ready.carried_proof(pr_ready.gate_events(self.port, REPO, PR), PR, sha, PLAN))


class RecordedBase(Fixture):
    def record(self, base):
        self.adapter.changes[(REPO, PR)] = {'body': BODY, 'base': base}

    def test_the_base_is_the_sha_the_forge_records(self):
        self.head()
        recorded = git(self.root, 'rev-parse', 'base-ref').strip()
        self.record(recorded)
        self.assertEqual(pr_ready.recorded_base(self.port, REPO, PR, self.root, fallback='base-ref'), (recorded, None))

    def test_a_stale_local_ref_changes_nothing(self):
        sha = self.head()
        recorded = git(self.root, 'rev-parse', 'base-ref').strip()
        self.record(recorded)
        git(self.root, 'branch', '-f', 'base-ref', sha)  # the local remote-tracking ref has gone stale
        base, note = pr_ready.recorded_base(self.port, REPO, PR, self.root, fallback='base-ref')
        self.assertEqual((base, note), (recorded, None))
        self.assertEqual(len(plan_tick.commit_messages(base, self.root, sha)), len(TICKED))

    def test_a_forge_that_records_no_base_falls_back_and_says_so(self):
        self.head()
        self.adapter.changes[(REPO, PR)] = {'body': BODY}
        base, note = pr_ready.recorded_base(self.port, REPO, PR, self.root, fallback='base-ref')
        self.assertEqual(base, 'base-ref')
        self.assertIn('records no base', note)

    def test_an_unreachable_forge_falls_back_and_says_so(self):
        # A local double stands in for the forge; compatibility is proved by test_forge_events.
        self.enterContext(unittest.mock.patch.object(forge_events, '_require_compatibility'))

        class Down(forge_events.MemoryAdapter):
            def change(self, repo, number):
                raise RuntimeError('forge down')
        self.head()
        port = forge_events.ForgeEvents(Down(), FixedClock(), config.get('plan-tick.event_producer'), f'pr-{PR}')
        base, note = pr_ready.recorded_base(port, REPO, PR, self.root, fallback='base-ref')
        self.assertEqual(base, 'base-ref')
        self.assertIn('forge unreachable (forge down)', note)

    def test_a_recorded_base_missing_from_the_checkout_falls_back_and_says_so(self):
        self.head()
        self.record('c' * len(SHA))
        base, note = pr_ready.recorded_base(self.port, REPO, PR, self.root, fallback='base-ref')
        self.assertEqual(base, 'base-ref')
        self.assertIn('is not in the checkout', note)

    def test_the_default_fallback_is_plan_tick_base_ref(self):
        self.head()
        self.adapter.changes[(REPO, PR)] = {'body': BODY}
        base, _ = pr_ready.recorded_base(self.port, REPO, PR, self.root)
        self.assertEqual(base, config.get('plan-tick.base_ref'))


def run_hook(*args, **options):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = gate_report.ready_hook(*args, **options)
    return result, out.getvalue().strip()


class GateReportHook(Fixture):
    def setUp(self):
        super().setUp()
        import train_trigger
        self.started = []
        patcher = unittest.mock.patch.object(
            train_trigger, 'trigger', lambda root, event, label: self.started.append((root, event, label))
            or 'started in the background, output in train.log')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_passed_verdict_emits_one_line(self):
        sha = self.head()
        verdict = self.gate.emit('gate.passed', verdict_payload(sha))
        event, printed = run_hook(verdict, 'dev', PR, sha, root=self.root, adapter=self.adapter, clock=FixedClock(),
                                  base='base-ref')
        self.assertEqual(printed.splitlines(), [f'pr.ready: emitted #{PR} head={pr_ready.short(sha)}'])
        self.assertEqual(event['payload']['evidence'], verdict['event_id'])
        self.assertEqual(self.started, [], 'pr.ready starts no train: no job path follows it (D-290/D-291)')

    def test_a_failed_verdict_is_not_announced(self):
        sha = self.head()
        verdict = self.gate.emit('gate.failed', verdict_payload(sha))
        event, printed = run_hook(verdict, 'dev', PR, sha, root=self.root, adapter=self.adapter, clock=FixedClock())
        self.assertIsNone(event)
        self.assertEqual(printed, 'pr.ready: not emitted (verdict is gate.failed, not gate.passed)')

    def test_any_exception_is_swallowed_and_printed(self):
        # A local double stands in for the forge; compatibility is proved by test_forge_events.
        self.enterContext(unittest.mock.patch.object(forge_events, '_require_compatibility'))

        class Broken(forge_events.MemoryAdapter):
            def change(self, repo, number):
                raise RuntimeError('forge down')
        sha = self.head()
        verdict = self.gate.emit('gate.passed', verdict_payload(sha))
        event, printed = run_hook(verdict, 'dev', PR, sha, root=self.root, adapter=Broken(), clock=FixedClock())
        self.assertIsNone(event)
        self.assertEqual(printed, 'pr.ready: not emitted (forge down)')


if __name__ == '__main__':
    unittest.main()
