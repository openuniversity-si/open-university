"""GX-20 carry-over by delta (gate_carry.py, D-070, P-42): the decision, its fail-closed cases and the run record."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import gate_carry  # noqa: E402
import gate_policy  # noqa: E402
import gate_script_tests  # noqa: E402

TOOLCHAIN, VERSION = 'toolchain-a', 'gate-tree-a'
PR = 1
DIGEST = hashlib.sha256(b'proof').hexdigest()
STAGES = ['secret scan (history)', 'secret scan (tree)', 'no GitHub Actions workflows', 'structure check',
          'generated drift', 'schema compat', 'install (frozen lockfile)', 'lint', 'unit tests', 'typecheck']


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def commit(root, files, message):
    for path, text in files.items():
        target = Path(root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD')


_TEMPLATE = {}


def _build(root):
    git(root, 'init', '-q')
    shas = {'B': commit(root, {'README.md': 'x\n'}, 'base')}
    shas['H0'] = commit(root, {'scripts/lib/a.py': 'a = 1\n'}, 'code')
    shas['R'] = commit(root, {'docs/units/GX99/retro.md': '# retro\n'}, 'retro')
    shas['R2'] = commit(root, {'docs/process/EVENTS.md': '# events\n'}, 'events doc')
    shas['X'] = commit(root, {'scripts/lib/x.py': 'x = 1\n'}, 'script')
    git(root, 'checkout', '-q', '-b', 'side', shas['B'])
    shas['side'] = commit(root, {'docs/side.md': 'side\n'}, 'side')
    git(root, 'checkout', '-q', '-b', 'notes', shas['H0'])
    shas['N'] = commit(root, {'docs/notes/plain.md': 'a note\n'}, 'an uncovered doc')
    return shas


def tearDownModule():
    if _TEMPLATE:
        shutil.rmtree(_TEMPLATE['root'], ignore_errors=True)


def repo(test):
    """base B; H0 = B + code (the green head); R = H0 + RETRO; X = R + a script; side = B + docs (not H0's child);
    N = H0 + a doc no script test covers. The code is an engine script since OU-DECOUPLE F2 (D-108): the engine gate
    orders the always stages and the script tests only, so the script tests are what a docs-only delta carries.
    The history is built once per module and each test gets its own copy of it (the same commits, ~25 git processes
    fewer per test), so a test that changes its repository never reaches another's."""
    if not _TEMPLATE:
        template = Path(tempfile.mkdtemp())
        _TEMPLATE.update(root=template, shas=_build(template))
    root = Path(tempfile.mkdtemp()) / 'repo'
    test.addCleanup(subprocess.run, ['rm', '-rf', str(root.parent)])
    shutil.copytree(_TEMPLATE['root'], root, symlinks=True)
    return root, dict(_TEMPLATE['shas'])


def verdict(sha, base, kind='gate.passed', event_id=None, toolchain=TOOLCHAIN, version=VERSION, v4=True, **extra):
    payload = {'pr': PR, 'sha': sha, 'plan': 'dev', 'stages': [{'name': s, 'result': 'PASS'} for s in STAGES]}
    if v4:
        payload.update(input_digest=DIGEST, base_sha=base, toolchain_id=toolchain, gate_version=version)
    payload.update(extra)
    return {'type': kind, 'event_id': event_id or f'ev-{sha}-{kind}', 'payload': payload}


def other_sha(sha):
    """A well-formed sha no fixture commit has."""
    return 'f' * len(sha)


SHA = other_sha(hashlib.sha1().hexdigest())


def binding(sha, base, toolchain=TOOLCHAIN, version=VERSION):
    return {'sha': sha, 'base_sha': base, 'toolchain_id': toolchain, 'gate_version': version}


class Decide(unittest.TestCase):
    def setUp(self):
        self.root, self.s = repo(self)

    def decide(self, events, head, enabled=True, areas=('docs',), **bind):
        return gate_carry.decide(events, binding(self.s[head], self.s['B'], **bind), self.root, enabled, list(areas))

    def test_retro_after_green_carries(self):
        d = self.decide([verdict(self.s['H0'], self.s['B'])], 'R')
        self.assertTrue(d['carry'], d)
        self.assertEqual(d['delta_files'], ['docs/units/GX99/retro.md'])
        self.assertEqual(d['from'], {'event_id': f'ev-{self.s["H0"]}-gate.passed', 'sha': self.s['H0']})
        self.assertEqual(d['passed_stages'], STAGES)

    def test_switch_off_is_a_normal_gate(self):
        d = self.decide([verdict(self.s['H0'], self.s['B'])], 'R', enabled=False)
        self.assertEqual(d, {'carry': False, 'reason': 'gate-carry.carry_over_enabled is off'})

    def test_no_binding_is_a_normal_gate(self):
        d = gate_carry.decide([verdict(self.s['H0'], self.s['B'])], None, self.root, True, ['docs'])
        self.assertFalse(d['carry'])
        self.assertIn('no proof binding', d['reason'])

    def test_different_base_toolchain_or_gate_version(self):
        events = [verdict(self.s['H0'], self.s['B'])]
        for field, bind in (('base_sha', {}), ('toolchain_id', {'toolchain': 'other'}), ('gate_version', {'version': 'other'})):
            with self.subTest(field=field):
                b = binding(self.s['R'], other_sha(self.s['B']) if field == 'base_sha' else self.s['B'], **bind)
                d = gate_carry.decide(events, b, self.root, True, ['docs'])
                self.assertFalse(d['carry'])
                self.assertIn(f'different {field}', d['reason'])

    def test_code_in_the_delta_is_a_normal_gate(self):
        d = self.decide([verdict(self.s['H0'], self.s['B'])], 'X')
        self.assertFalse(d['carry'])
        self.assertIn('scripts/lib/x.py is outside docs', d['reason'])

    def test_not_an_ancestor_is_a_normal_gate(self):
        d = self.decide([verdict(self.s['H0'], self.s['B'])], 'side')
        self.assertFalse(d['carry'])
        self.assertIn('not an ancestor', d['reason'])

    def test_a_later_failure_on_the_head_withdraws_its_pass(self):
        events = [verdict(self.s['H0'], self.s['B']), verdict(self.s['H0'], self.s['B'], kind='gate.failed')]
        self.assertFalse(self.decide(events, 'R')['carry'])

    def test_a_v3_verdict_carries_nothing(self):
        d = self.decide([verdict(self.s['H0'], self.s['B'], v4=False)], 'R')
        self.assertFalse(d['carry'])
        self.assertIn('no passed v4 dev proof', d['reason'])

    def test_another_plan_carries_nothing(self):
        event = verdict(self.s['H0'], self.s['B'])
        event['payload']['plan'] = 'tier3'
        self.assertFalse(self.decide([event], 'R')['carry'])

    def test_no_change_is_a_normal_gate(self):
        d = gate_carry.decide([verdict(self.s['H0'], self.s['B'])], binding(self.s['H0'], self.s['B']), self.root, True, ['docs'])
        self.assertFalse(d['carry'])

    def test_a_carried_proof_chains_to_its_origin(self):
        origin = verdict(self.s['H0'], self.s['B'], event_id='origin')
        carried = verdict(self.s['R'], self.s['B'], event_id='carried',
                          carried_from={'event_id': 'origin', 'sha': self.s['H0'], 'delta_files': ['docs/units/GX99/retro.md']})
        d = self.decide([origin, carried], 'R2')
        self.assertTrue(d['carry'], d)
        self.assertEqual(d['from'], {'event_id': 'origin', 'sha': self.s['H0']})
        self.assertEqual(d['delta_files'], ['docs/process/EVENTS.md', 'docs/units/GX99/retro.md'])

    def test_a_git_error_fails_closed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            gate_carry.delta(self.root, other_sha(self.s['B']), self.s['R'])


class Record(unittest.TestCase):
    def test_record_writes_carried_stage_records(self):
        logs = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(logs)])
        decision = {'carry': True, 'reason': 'r', 'from': {'event_id': 'e', 'sha': SHA}, 'delta_files': ['docs/x.md']}
        gate_carry.record(logs, decision, ['lint', 'unit tests'])
        self.assertEqual(gate_carry.carried(logs), ['lint', 'unit tests'])
        self.assertEqual(gate_carry.carried_from(logs), {'event_id': 'e', 'sha': SHA, 'delta_files': ['docs/x.md']})
        self.assertEqual(gate_carry.fields(logs), {'carried_from': gate_carry.carried_from(logs)})
        stage = json.loads((logs / 'unit_tests.stage.json').read_text())
        self.assertEqual(stage, {'name': 'unit tests', 'result': 'PASS', 'exit': 0, 'seconds': 0, 'cached': True, 'carried': True})

    def test_nothing_carried(self):
        logs = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(logs)])
        self.assertEqual((gate_carry.carried(logs), gate_carry.carried_from(logs), gate_carry.fields(logs)), ([], None, {}))

    def test_load_decision_only_returns_a_carry(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(folder)])
        (folder / 'n.json').write_text(json.dumps({'carry': False, 'reason': 'x'}))
        (folder / 'c.json').write_text(json.dumps({'carry': True}))
        (folder / 'bad.json').write_text('{')
        self.assertIsNone(gate_carry.load_decision(str(folder / 'n.json')))
        self.assertIsNone(gate_carry.load_decision(str(folder / 'bad.json')))
        self.assertIsNone(gate_carry.load_decision(environ={}))
        self.assertEqual(gate_carry.load_decision(environ={gate_carry.DECISION_ENV: str(folder / 'c.json')}), {'carry': True})


DEV_PASSED = gate_policy.DEV_STAGES + ['script tests']


class Classify(unittest.TestCase):
    """gate_policy: the carry decision turns the base...head plan into the delta plan plus carried stages."""

    def setUp(self):
        self.root, self.s = repo(self)
        git(self.root, 'remote', 'add', 'origin', str(self.root))
        self.logs = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(self.logs)])

    def decision(self, head, passed=DEV_PASSED):
        event = verdict(self.s['H0'], self.s['B'])
        event['payload']['stages'] = [{'name': name, 'result': 'PASS'} for name in passed]
        d = gate_carry.decide([event], binding(self.s[head], self.s['B']), self.root, True, ['docs'])
        self.assertTrue(d['carry'], d)
        path = self.logs / 'carry-decision.json'
        path.write_text(json.dumps(d))
        return path

    def classify(self, head, decision_file):
        env = {gate_carry.DECISION_ENV: str(decision_file)}
        with unittest.mock.patch.dict(os.environ, env):
            return gate_policy.classify_pr(PR, self.s[head], root=self.root, base=self.s['B'], logs=self.logs)

    def test_retro_after_green_runs_the_delta_plan_and_carries_the_rest(self):
        result = self.classify('R', self.decision('R'))
        plan = result['devPlan']
        always = gate_carry_always()
        self.assertEqual([stage for stage in plan['stages'] if stage in always], always)  # structure check executes (D-B6)
        self.assertIn('structure check', plan['stages'])
        self.assertIn('script tests', plan['stages'])  # docs/units/*/retro.md is covered by the lessons test (GX-18)
        self.assertEqual(plan['paths'], ['docs/units/GX99/retro.md'])
        self.assertEqual(gate_carry.carried(self.logs), [])  # the delta plan already runs every stage the head owes
        self.assertEqual(gate_carry.carried_from(self.logs),
                         {'event_id': f'ev-{self.s["H0"]}-gate.passed', 'sha': self.s['H0'], 'delta_files': ['docs/units/GX99/retro.md']})
        tests, _reason = gate_script_tests.select_plan(plan)
        self.assertIn('scripts/tests/lessons.test.sh', tests)

    def test_an_uncovered_doc_after_green_carries_the_script_tests(self):
        plan = self.classify('N', self.decision('N'))['devPlan']
        self.assertEqual(plan['stages'], gate_carry_always())
        self.assertEqual(plan['paths'], ['docs/notes/plain.md'])
        carried = gate_carry.carried(self.logs)
        self.assertEqual(carried, ['script tests'])
        self.assertNotIn('structure check', carried)
        stage = json.loads((self.logs / 'script_tests.stage.json').read_text())
        self.assertEqual((stage['result'], stage['cached'], stage['carried']), ('PASS', True, True))

    def test_a_docs_commit_touching_events_md_runs_event_contracts(self):
        plan = self.classify('R2', self.decision('R2'))['devPlan']
        tests, _reason = gate_script_tests.select_plan(plan)
        self.assertIn('scripts/tests/event-contracts.test.sh', tests)
        self.assertLess(len(tests), len(gate_script_tests.load()['scripts']))

    def test_a_proof_that_does_not_cover_the_plan_is_a_normal_gate(self):
        # N's delta runs the always stages only, and the proof passed no script test: nothing may be carried.
        result = self.classify('N', self.decision('N', passed=['structure check']))
        self.assertIn('script tests', result['devPlan']['stages'])
        self.assertNotIn('carry', result['devPlan'])
        self.assertEqual(gate_carry.carried(self.logs), [])

    def test_a_decision_for_another_head_is_ignored(self):
        result = self.classify('R2', self.decision('R'))
        self.assertNotIn('carry', result['devPlan'])
        self.assertIn('script tests', result['devPlan']['stages'])

    def test_no_decision_is_the_normal_plan(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gate_carry.DECISION_ENV, None)
            result = gate_policy.classify_pr(PR, self.s['R'], root=self.root, base=self.s['B'], logs=self.logs)
        self.assertIn('script tests', result['devPlan']['stages'])
        self.assertEqual(gate_carry.carried(self.logs), [])


def gate_carry_always():
    import gate_areas
    return list(gate_areas.load().always)


class Registry(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(gate_carry.settings(), (True, ['docs']))


class Cli(unittest.TestCase):
    def test_decide_without_binding_writes_a_normal_decision(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(folder)])
        env = {k: v for k, v in os.environ.items() if k != 'OU_GATE_PROOF'}
        env['OU_CONFIG_STORE'] = 'file'
        out = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_carry.py'), 'decide', '--pr', str(PR),
                              '--root', str(ROOT), '--out', str(folder / 'd.json')], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('carry: normal gate (the run has no proof binding)', out.stdout)
        self.assertFalse(json.loads((folder / 'd.json').read_text())['carry'])


if __name__ == '__main__':
    unittest.main()
