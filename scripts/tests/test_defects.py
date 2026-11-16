"""The known-defect registry (KD1). Fixture register in a temp directory, in-memory forge log, injected clock."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import defects  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_doubles  # noqa: E402

TEST, STAGE, SIGNATURE = 'scripts/tests/x.test.sh', 'script tests', 'AssertionError: boom N'
SHA_A, SHA_B = 'a' * 40, 'b' * 40
OWNED = ('engine-x', 'engine-lane', ['scripts/tests/x.test.sh'])


class FakeClock:
    def __init__(self):
        self.moment = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


class Fixture(unittest.TestCase):
    def setUp(self):
        # Consumer unit tests inject local doubles; compatibility is exercised by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'defects', self.tmp / 'contracts' / 'defects')
        self.clock = FakeClock()
        patch = mock.patch.object(defects, 'derive_owner', side_effect=lambda test, root=ROOT, files=None: OWNED)
        patch.start()
        self.addCleanup(patch.stop)
        self.port = forge_events.ForgeEvents(forge_doubles.journal('scripts/lib/defect_router.py'), self.clock, 'defects', 'test')

    def record(self, signature=SIGNATURE, sha=SHA_A, run='run-1', test=TEST):
        return defects.record(self.tmp, test, STAGE, signature, sha, run, 'gate', port=self.port, clock=self.clock)

    def types(self):
        return [event['type'] for event in self.port.adapter.read(forge_events.Channel(config.get('forge-events.repo'), None))]


class Registry(Fixture):
    def test_a_new_failure_opens_a_defect_with_the_derived_owner_and_a_registered_event(self):
        found, outcome = self.record()
        self.assertEqual(outcome, 'created')
        self.assertEqual((found['status'], found['owner'], found['unit']), ('open', 'engine-lane', 'engine-x'))
        self.assertEqual(self.types(), ['defect.registered'])
        self.assertEqual(defects.check(self.tmp)[1], [])

    def test_the_same_test_and_signature_is_the_same_defect(self):
        first, _ = self.record()
        second, outcome = self.record(sha=SHA_B, run='run-2')
        self.assertEqual((second['id'], outcome), (first['id'], 'observed'))
        self.assertEqual(len(defects.load(self.tmp)[0]), 1)
        self.assertEqual(len(second['evidence']), 2)
        again, outcome = self.record(sha=SHA_B, run='run-2')
        self.assertEqual((outcome, len(again['evidence'])), ('observed', 2))

    def test_another_signature_is_another_defect(self):
        first, _ = self.record()
        other, _ = self.record(signature='KeyError: N')
        self.assertNotEqual(first['id'], other['id'])
        self.assertEqual(len(defects.load(self.tmp)[0]), 2)

    def test_an_edited_or_removed_audit_entry_breaks_the_chain(self):
        found, _ = self.record()
        self.record(sha=SHA_B, run='run-2')
        _, trail = defects.paths(self.tmp, found['slug'])
        lines = trail.read_text().splitlines()
        trail.write_text('\n'.join([lines[0].replace('gate', 'someone'), lines[1]]) + '\n')
        self.assertTrue(any('edited' in error for error in defects.load(self.tmp)[1]))
        trail.write_text(lines[1] + '\n')
        self.assertTrue(any('chain' in error for error in defects.load(self.tmp)[1]))

    def test_a_stored_owner_is_refused_since_it_is_derived_on_load(self):
        found, _ = self.record()
        path, _ = defects.paths(self.tmp, found['slug'])
        text = path.read_text()
        for field in defects.DERIVED:
            self.assertNotIn(f'\n{field}:', text)
        path.write_text(text + 'owner: "someone-else"\n')
        self.assertTrue(any('owner' in error for error in defects.load(self.tmp)[1]))

    def test_a_unit_whose_paths_moved_leaves_no_record_stale(self):
        found, _ = self.record()
        path, trail = defects.paths(self.tmp, found['slug'])
        kept, text = trail.read_text(), path.read_text()
        moved = ('engine-y', 'engine-lane', ['scripts/tests/x.test.sh', 'scripts/lib/y.py'])
        with mock.patch.object(defects, 'derive_owner', return_value=moved):
            records, errors = defects.load(self.tmp)
        self.assertEqual(errors, [])
        self.assertEqual(tuple(records[found['id']][field] for field in defects.DERIVED), moved)
        self.assertEqual((path.read_text(), trail.read_text()), (text, kept))

    def test_a_status_change_outside_the_transitions_is_refused(self):
        found, _ = self.record()
        with self.assertRaises(defects.DefectError):
            defects.transition(self.tmp, found['id'], 'verified', 'x', 'skip ahead', clock=self.clock)
        moved = defects.transition(self.tmp, found['id'], 'fixing', 'router', 'fix unit opened',
                                   fix={'lane': 'engine-lane', 'item': 'fix', 'work_event': 'e1', 'pr': None, 'merge_sha': None},
                                   clock=self.clock)
        self.assertEqual([entry['to'] for entry in moved['trail']], ['open', 'fixing'])

    def test_resolve_needs_a_fix_unit_and_a_resolved_defect_failing_again_is_reopened(self):
        found, _ = self.record()
        with self.assertRaises(defects.DefectError):
            defects.resolve(self.tmp, found['id'], 7, SHA_B, 'merge', self.port, self.clock)
        defects.transition(self.tmp, found['id'], 'fixing', 'router', 'fix unit opened',
                           fix={'lane': 'engine-lane', 'item': 'fix', 'work_event': 'e1', 'pr': None, 'merge_sha': None},
                           clock=self.clock)
        done = defects.resolve(self.tmp, found['id'], 7, SHA_B, 'merge', self.port, self.clock)
        self.assertEqual((done['status'], done['fix']['pr']), ('resolved', 7))
        again, outcome = self.record(sha=SHA_B, run='run-3')
        self.assertEqual((outcome, again['status']), ('reopened', 'open'))
        self.assertEqual(self.types(), ['defect.registered', 'defect.resolved', 'defect.reopened'])

    def test_the_trail_may_only_grow_against_a_base(self):
        subprocess.run(['git', 'init', '-q', str(self.tmp)], check=True)
        found, _ = self.record()
        env = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-C', str(self.tmp)]
        subprocess.run(['git', *env, 'add', '-A'], check=True)
        subprocess.run(['git', *env, 'commit', '-qm', 'base'], check=True)
        self.record(sha=SHA_B, run='run-2')
        self.assertEqual(defects.check(self.tmp, 'HEAD')[1], [])
        _, trail = defects.paths(self.tmp, found['slug'])
        trail.write_text('')
        self.assertTrue(any('append-only' in error for error in defects.check(self.tmp, 'HEAD')[1]))


class Sync(Fixture):
    def detected(self, sha=SHA_A, run='run-1', signature=SIGNATURE):
        return self.port.build('defect.detected', {
            'repo': config.get('forge-events.repo'), 'pr': None, 'sha': sha, 'unit': None, 'premises': [],
            'defect': defects.defect_id(TEST, signature), 'test': TEST, 'signature': signature, 'owner': 'engine-lane',
            'base_sha': sha, 'stage': STAGE, 'run': run})

    def lifecycle(self, kind, **extra):
        return self.port.build(kind, dict({
            'repo': config.get('forge-events.repo'), 'pr': None, 'sha': SHA_B, 'unit': None, 'premises': [],
            'defect': defects.defect_id(TEST, SIGNATURE), 'test': TEST, 'signature': SIGNATURE, 'owner': 'engine-lane',
            'base_sha': SHA_B, 'run': 'run-9'}, **extra))

    def test_the_gates_events_are_applied_once_and_replay_changes_nothing(self):
        events = [self.detected()]
        self.assertEqual(defects.sync(self.tmp, events, self.port, self.clock), [(defects.defect_id(TEST, SIGNATURE), 'created')])
        trail = len(next(iter(defects.load(self.tmp)[0].values()))['trail'])
        defects.sync(self.tmp, events, self.port, self.clock)
        self.assertEqual(len(next(iter(defects.load(self.tmp)[0].values()))['trail']), trail)

    def test_verified_and_reopened_apply_only_to_a_defect_in_the_right_status(self):
        ident = defects.defect_id(TEST, SIGNATURE)
        defects.sync(self.tmp, [self.detected()], self.port, self.clock)
        verified = self.lifecycle('defect.verified')
        real = defects.setting
        with mock.patch.object(defects, 'setting', side_effect=lambda name: False if name == 'verify_open' else real(name)):
            defects.sync(self.tmp, [verified], self.port, self.clock)
        self.assertEqual(defects.load(self.tmp)[0][ident]['status'], 'open')  # GX-13 switch off: an open defect is not verified
        defects.transition(self.tmp, ident, 'fixing', 'router', 'x', fix={'lane': 'l', 'item': 'i', 'work_event': 'e', 'pr': None, 'merge_sha': None}, clock=self.clock)
        defects.resolve(self.tmp, ident, 3, SHA_B, 'merge', None, self.clock)
        self.assertEqual(defects.sync(self.tmp, [verified], self.port, self.clock), [(ident, 'verified')])
        self.assertEqual(defects.load(self.tmp)[0][ident]['status'], 'verified')
        reopened = self.lifecycle('defect.reopened', observed_signature='KeyError: x')
        self.assertEqual(defects.sync(self.tmp, [reopened], self.port, self.clock), [(ident, 'reopened')])
        self.assertEqual(defects.load(self.tmp)[0][ident]['status'], 'open')


class Ownership(unittest.TestCase):
    def test_the_owner_comes_from_the_unit_manifests(self):
        unit, owner, area = defects.derive_owner('scripts/tests/premises.test.sh', ROOT)
        self.assertEqual((unit, owner), ('engine-premises', 'engine-lane'))
        self.assertIn('scripts/lib/premises.py', area)

    def test_an_unowned_test_gets_the_registered_unknown_owner(self):
        self.assertEqual(defects.derive_owner('nowhere/none.test.sh', ROOT, files=set()),
                         (None, config.get('defects.unknown_owner'), []))

    def test_the_id_is_a_hash_of_test_and_signature(self):
        self.assertEqual(defects.defect_id('a', 'b'), defects.defect_id('a', 'b'))
        self.assertNotEqual(defects.defect_id('a', 'b'), defects.defect_id('a', 'c'))
        self.assertTrue(defects.defect_id('a', 'b').startswith(config.get('defects.id_prefix')))


class Cli(Fixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = defects.main(['--root', str(self.tmp), *args], port=self.port)
        return code, out.getvalue(), err.getvalue()

    def test_record_list_show_resolve_and_check(self):
        code, out, err = self.run_cli('record', '--test', TEST, '--stage', STAGE, '--signature', SIGNATURE,
                                      '--base-sha', SHA_A, '--run', 'r', '--by', 'cli')
        self.assertEqual((code, 'created' in out), (0, True), err)
        ident = out.split()[0]
        self.assertIn(ident, self.run_cli('list')[1])
        self.assertIn('registered', self.run_cli('show', ident)[1])
        self.assertEqual(self.run_cli('check')[1].strip(), 'defects: 1 record(s), 0 error(s)')
        self.assertEqual(self.run_cli('resolve', ident, '--pr', '3', '--merge-sha', SHA_B, '--by', 'x')[0], 2)
        self.assertEqual(self.types(), ['defect.registered'])


if __name__ == '__main__':
    unittest.main()
