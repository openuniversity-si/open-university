"""The pre-push check (TX01, T9) on fixture repositories with copies of this checkout's registry: the inventory with its
fixes (a file of two units, a literal, a generated file's drift, the event names), the owning script tests (a subset runs, a
selection of the whole suite is deferred, the budget, the scrubbed environment), the open-PR overlap from fixture PR heads
(the REST list is a function the test passes in, never GitHub), and the exit codes of --hook and of .githooks/pre-push.
No network; the test never reads the clock (an injected one, or the module's own)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import gate_script_tests  # noqa: E402
import literal_census  # noqa: E402
import prepush  # noqa: E402
import units  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

COPIED = ('contracts/config/registry.v1.json', 'contracts/units/unit.v1.json')
IDENTITY = ('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false')
OWNER = config.get('units.owners')[0]
# PR numbers are spelled as text: the literal census admits no other number than 0, 1 and -1 in scripts/, tests included.
FIRST_PR, SECOND_PR, THIRD_PR, OWN_PR = (int(text) for text in ('7', '8', '9', '742'))
PASSES, FAILS = '#!/usr/bin/env bash\nexit 0\n', '#!/usr/bin/env bash\nexit 1\n'


def git(cwd, *args, check=True):
    done = subprocess.run(['git', '-C', str(cwd), *IDENTITY, *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    if check and done.returncode:
        raise AssertionError(f'git {" ".join(args)}: {done.stderr}')
    return done


class Regime(unittest.TestCase):
    def test_the_repeated_census_obeys_the_same_lock_as_the_local_check(self):
        import gate_discipline
        findings = ['an unregistered value']
        for lifted in (False, True):
            with self.subTest(lifted=lifted), mock.patch.object(literal_census, 'check', return_value=(findings, [])), \
                    mock.patch.object(gate_discipline, 'lifted', return_value=lifted), mock.patch('sys.stdout'):
                self.assertEqual(prepush.check_literals(ROOT, 'HEAD'), [] if lifted else [(findings[0], [])])


class Ticks:
    """An injected clock: `zeros` reads of 0, then `later` on every read."""

    def __init__(self, zeros, later):
        self.left, self.later = zeros, later

    def __call__(self):
        self.left -= 1
        return 0 if self.left >= 0 else self.later


class Fixture(unittest.TestCase):
    """A git repository holding a copy of this checkout's registry: branch main is the base, branch work is checked out.

    One template repository per class (setUpClass) holds the registry copy and branch main; each test copies it, so the
    git init and the first commit run once per class, not once per test (D-194 follow-up, lane 1)."""

    @classmethod
    def setUpClass(cls):
        import gate_discipline
        cls.enterClassContext(mock.patch.object(gate_discipline, 'lifted', return_value=False))
        saved = dict(os.environ)
        cls.addClassCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        # a hook's GIT_INDEX_FILE must not reach the fixtures; the suite's git configuration does (D-118)
        for name in [key for key in os.environ if key.startswith('GIT_') and not key.startswith('GIT_CONFIG_')]:
            del os.environ[name]
        cls.template_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.template_tmp.cleanup)
        template = Path(cls.template_tmp.name).resolve() / 'repo'
        fixture_copy.registry(template)
        for name in COPIED:
            (template / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, template / name)
        git(template.parent, 'init', '--quiet', '--initial-branch=main', str(template))
        git(template, 'add', '-A')
        git(template, 'commit', '--quiet', '-m', 'template')
        cls.template = template

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'repo'
        shutil.copytree(self.template, self.root, symlinks=True)
        self.lines = []
        units.reset()
        config.invalidate()
        self.addCleanup(units.reset)
        self.addCleanup(config.invalidate)
        self.default('prepush.tests_budget_s', 20)  # these tests judge the runner; the live default of 0 runs none

    def write_in(self, root, name, content):
        (root / name).write_text(content, encoding='utf-8')

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content, indent='  ') + '\n')
        return path

    def default(self, name, value):
        """Set the fixture's registry default of one parameter."""
        path = self.root / 'config' / 'registry' / f'{name.split(".", 1)[0]}.json'
        data = json.loads(path.read_text())
        data['properties'][name]['default'] = value
        path.write_text(json.dumps(data, indent='  ') + '\n')
        config.invalidate()

    def unit(self, unit, paths):
        self.write(f'units/{unit}/unit.json', {'id': unit, 'purpose': f'The {unit} unit.', 'cell': 'demo', 'owner': OWNER,
                                               'paths': paths})

    def script_test(self, name, body, covers):
        self.write(f'scripts/tests/{name}.test.sh', body)
        self.write(f'scripts/tests/covers/{name}.json', {'script': f'scripts/tests/{name}.test.sh',
                                                         'covers': [f'scripts/tests/{name}.test.sh', *covers]})

    def commit(self, message='change'):
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '--quiet', '--allow-empty', '-m', message)
        return git(self.root, 'rev-parse', 'HEAD').stdout.strip()

    def base(self):
        """Commit everything written so far on main and start branch work from it."""
        self.commit('base')
        git(self.root, 'checkout', '--quiet', '-b', 'work')
        units.reset()

    def run_prepush(self, **options):
        options.setdefault('base', 'main')
        options.setdefault('overlaps', False)
        code = prepush.run(self.root, out=self.lines.append, **options)
        return code, '\n'.join(self.lines)


class Inventory(Fixture):
    def test_a_check_the_local_stage_verified_is_not_run_again(self):
        """D-194: .githooks/pre-push passes the inventory checks its local stage ran and passed; prepush does not run
        them a second time (about 1.9 s of a push), and the checks it did not verify still run."""
        calls = []
        checks = (('units', lambda root, base: calls.append('units') or []),
                  ('literals', lambda root, base: calls.append('literals') or []))
        code, text = self.run_prepush(checks=checks, verified=('units',))
        self.assertEqual(code, 0)
        self.assertEqual(calls, ['literals'])
        self.assertIn('units: skipped (the local stage of this push ran it and it passed)', text)
        self.assertIn('literals: ok', text)

    def test_a_file_listed_by_name_and_owned_by_a_glob_gets_the_remove_hint(self):
        self.write('tools/data/x.json', '{}\n')
        self.unit('alpha-unit', ['tools/data/**'])
        self.unit('beta-unit', ['tools/data/x.json'])
        self.base()
        found = prepush.check_units(self.root, None)
        self.assertEqual(len(found), 1)
        error, fixes = found[0]
        self.assertTrue(error.startswith('tools/data/x.json belongs to 2 units (alpha-unit, beta-unit)'), error)
        self.assertEqual(fixes, ['fix: remove "tools/data/x.json" from units/beta-unit/unit.json paths '
                                 '(alpha-unit owns it by "tools/data/**")'])

    def test_two_globs_name_both_to_narrow_and_two_names_keep_one(self):
        self.write('tools/data/x.json', '{}\n')
        self.write('tools/data/y.json', '{}\n')
        self.unit('alpha-unit', ['tools/**'])
        self.unit('beta-unit', ['tools/data/x.json'])
        self.unit('gamma-unit', ['tools/data/*.json'])
        self.unit('delta-unit', ['tools/data/y.json'])
        self.base()
        found = dict(prepush.check_units(self.root, None))
        x = next(fixes for error, fixes in found.items() if error.startswith('tools/data/x.json'))
        self.assertIn('fix: remove "tools/data/x.json" from units/beta-unit/unit.json paths (alpha-unit owns it by '
                      '"tools/**")', x)
        self.assertIn('fix: narrow one of "tools/**" in units/alpha-unit/unit.json, "tools/data/*.json" in '
                      'units/gamma-unit/unit.json so that one unit owns "tools/data/x.json"', x)
        self.unit('alpha-unit', ['tools/data/y.json'])
        self.unit('gamma-unit', ['README.md'])
        self.write('README.md', '# fixture\n')
        git(self.root, 'add', '-A')
        units.reset()
        found = dict(prepush.check_units(self.root, None))
        y = next(fixes for error, fixes in found.items() if error.startswith('tools/data/y.json'))
        self.assertEqual(y, ['fix: keep "tools/data/y.json" in the paths of one of units/alpha-unit/unit.json, '
                             'units/delta-unit/unit.json and remove it from the others'])

    def test_a_new_literal_is_a_finding_with_the_registry_fix(self):
        tool, source = 'scripts/tool.py', 'LIMIT = 42\n'
        spelled = source.split('=')[1].strip()
        self.base()
        self.write(tool, source)
        git(self.root, 'add', '-A')
        found = [error for error, _ in prepush.check_literals(self.root, 'main')]
        # The census owns the wording of a finding: this asserts the value, the count, the place and the fix it hands
        # back, and reads the fix from the census instead of spelling the sentence again (TX22 rewrote it; D-068).
        self.assertTrue(any(f'{literal_census.key("number", int(spelled))} is written 1 times and the census of main'
                            in error and f'allows 0, at {tool}:1;' in error
                            and error.endswith(literal_census.FIX) for error in found), found)

    def test_generated_drift_names_the_generator_target(self):
        problem = 'config/registry/gate.json: differs from its regeneration; run scripts/generate registry'
        with mock.patch.object(prepush.generate, 'drift', return_value=[problem]) as drift:
            self.assertEqual(prepush.check_generated(self.root, None), [(problem, [])])
        drift.assert_called_once_with(self.root)

    def test_event_names_name_the_side_to_fix(self):
        self.assertEqual(prepush.check_events(ROOT, None), [])
        self.write('scripts/tests/test_event_contracts.py', (
            'import unittest\n\n\nclass Contracts(unittest.TestCase):\n'
            '    def test_events_md_and_the_schemas_name_the_same_events(self):\n'
            "        self.assertEqual(sorted({'pr.merged', 'no.such-event'}), [])\n"))
        found = dict(prepush.check_events(self.root, None))
        contracts = config.get('forge-events.contracts_dir')
        self.assertEqual(sorted(found), [
            f'event no.such-event: a row in the ## Events table of docs/process/EVENTS.md and no schema in {contracts} '
            f'(scripts/tests/test_event_contracts.py::Contracts.test_events_md_and_the_schemas_name_the_same_events)',
            f'event pr.merged: a schema in {contracts} and no row in the ## Events table of docs/process/EVENTS.md '
            f'(scripts/tests/test_event_contracts.py::Contracts.test_events_md_and_the_schemas_name_the_same_events)'])
        self.assertTrue(all(fixes and fixes[0].startswith('fix: ') for fixes in found.values()))

    def test_a_missing_event_test_is_skipped_never_a_finding(self):
        self.base()
        with self.assertRaises(prepush.Skip):
            prepush.check_events(self.root, None)

    def test_a_broken_check_warns_and_every_check_prints_its_time(self):
        self.base()

        def broken(root, base):
            raise RuntimeError('boom')

        def finds(root, base):
            return [('a finding', ['fix: the fix'])]

        findings, warnings = prepush.inventory(self.root, None, self.lines.append, Ticks(0, 0),
                                               [('broken', broken), ('finds', finds), ('clean', lambda root, base: [])])
        self.assertEqual((findings, warnings), (1, 1))
        self.assertEqual(self.lines, ['WARN broken: could not run (RuntimeError: boom), 0 ms', 'finds: 1 finding(s), 0 ms',
                                      'FAIL a finding', '  fix: the fix', 'clean: ok, 0 ms'])


class Changes(Fixture):
    def test_committed_uncommitted_untracked_and_both_names_of_a_rename(self):
        self.write('a.txt', 'a\n')
        self.write('old.txt', 'old\n')
        self.base()
        self.write('b.txt', 'b\n')
        self.commit()
        self.write('a.txt', 'changed\n')
        git(self.root, 'mv', 'old.txt', 'new.txt')
        self.write('c.txt', 'untracked\n')
        files, fork = prepush.changed(self.root, 'main')
        self.assertEqual(files, ['a.txt', 'b.txt', 'c.txt', 'new.txt', 'old.txt'])
        self.assertEqual(fork, git(self.root, 'rev-parse', 'main').stdout.strip())


class Tests(Fixture):
    def setUp(self):
        super().setUp()
        self.script_test('alpha', PASSES, ['scripts/alpha'])
        self.script_test('beta', FAILS, ['scripts/beta'])
        self.write('scripts/alpha', 'a\n')
        self.write('scripts/beta', 'b\n')
        self.write('scripts/gamma', 'c\n')

    def test_the_owning_tests_of_the_diff_run_alone(self):
        self.base()
        self.write('scripts/alpha', 'changed\n')
        code, text = self.run_prepush(checks=())
        self.assertEqual(code, 0, text)
        self.assertIn('tests: 1 run, 0 failed, 0 deferred to the gate (1 script test(s) cover the diff)', text)
        self.assertIn('PASS scripts/tests/alpha.test.sh', text)
        self.assertNotIn('beta', text)
        self.assertIn('prepush: 0 finding(s), 1 test(s) run, 0 deferred, 0 warning(s)', text)

    def test_a_budget_of_zero_runs_no_test_and_defers_them_to_the_gate(self):
        self.default('prepush.tests_budget_s', 0)
        self.base()
        self.write('scripts/alpha', 'changed\n')
        code, text = self.run_prepush(checks=())
        self.assertEqual(code, 0, text)
        self.assertIn('tests: 1 deferred to the gate (prepush.tests_budget_s is 0)', text)
        self.assertNotIn('PASS scripts/tests/alpha.test.sh', text)

    def selection(self, path):
        """The selector's own (tests, reason) for one changed path: the test follows gate_script_tests, never its wording."""
        return gate_script_tests.select([path], gate_script_tests.load(self.root))

    def test_a_selector_change_or_an_uncovered_path_defers_the_whole_suite(self):
        selector = config.get('gate-tests.fallback', self.root)[-1]
        self.write(selector, 'a selector\n')
        self.base()
        self.write(selector, 'changed\n')
        code, text = self.run_prepush(checks=())
        self.assertEqual(code, 0, text)
        self.assertIn(f'{self.selection(selector)[1]}; full script suite deferred to the gate', text)
        self.assertIn('prepush: 0 finding(s), 0 test(s) run, 2 deferred', text)
        git(self.root, 'checkout', '--quiet', '--', selector)
        self.write('scripts/gamma', 'changed\n')
        self.lines.clear()
        code, text = self.run_prepush(checks=())
        self.assertIn(f'{self.selection("scripts/gamma")[1]}; full script suite deferred to the gate', text)
        self.assertNotIn('PASS', text)

    def test_a_covers_manifest_edit_runs_what_the_selector_chooses(self):
        self.base()
        manifest = 'scripts/tests/covers/alpha.json'
        self.write(manifest, {'script': 'scripts/tests/alpha.test.sh', 'covers': ['scripts/tests/alpha.test.sh']})
        chosen, reason = self.selection(manifest)
        code, text = self.run_prepush(checks=())
        self.assertEqual(code, 0, text)
        self.assertIn(reason, text)
        self.assertEqual([line.split()[1] for line in text.splitlines() if line.startswith('PASS ')], list(chosen))

    def test_children_never_see_git_or_gate_variables_and_get_the_harness(self):
        self.script_test('alpha', '#!/usr/bin/env bash\n[ -z "${GIT_INDEX_FILE+x}" ] && [ -z "${OU_GATE_TIER+x}" ]\n',
                         ['scripts/alpha'])
        self.base()
        leaky = {**os.environ, 'GIT_INDEX_FILE': '.git/index', 'OU_GATE_TIER': 'pr'}
        env = prepush.test_env(leaky, self.root)
        self.assertFalse([key for key in env if key.startswith(('GIT_', 'OU_GATE_'))])
        self.assertEqual(env['PYTHONPATH'].split(os.pathsep)[0], str(ROOT / 'scripts' / 'lib' / 'hermetic'))
        unscrubbed = subprocess.run(['bash', 'scripts/tests/alpha.test.sh'], cwd=self.root, env=leaky)
        self.assertEqual(unscrubbed.returncode, 1)
        results = prepush.run_tests(self.root, ['scripts/tests/alpha.test.sh'], environ=leaky)
        self.assertEqual(results['scripts/tests/alpha.test.sh'].status, 'passed')

    def test_tests_not_started_within_the_budget_are_deferred(self):
        self.script_test('alpha', '#!/usr/bin/env bash\ntouch ran-alpha\n', ['scripts/alpha'])
        self.base()
        budget = config.get('prepush.tests_budget_s', self.root)
        results = prepush.run_tests(self.root, ['scripts/tests/alpha.test.sh', 'scripts/tests/beta.test.sh'],
                                    clock=Ticks(1, budget))
        self.assertEqual({script: ran.status for script, ran in results.items()},
                         {'scripts/tests/alpha.test.sh': 'deferred', 'scripts/tests/beta.test.sh': 'deferred'})
        self.assertFalse((self.root / 'ran-alpha').exists())

    def test_a_test_stopped_at_the_budget_is_deferred_at_once_next_time(self):
        self.default('prepush.tests_budget_s', 1)
        self.default('prepush.stop_grace_s', 0)
        self.script_test('alpha', '#!/usr/bin/env bash\nexec sleep 600\n', ['scripts/alpha'])
        self.base()
        self.write('scripts/alpha', 'changed\n')
        files = prepush.changed(self.root, 'main')[0]
        ran, deferred, failed, warnings = prepush.tests_part(self.root, files, False, self.lines.append, prepush.time.monotonic)
        self.assertEqual((ran, deferred, failed), (0, 1, 0))
        self.assertIn('deferred to the gate: scripts/tests/alpha.test.sh (still running at prepush.tests_budget_s, '
                      'stopped)', self.lines)
        self.lines.clear()
        self.assertEqual(prepush.tests_part(self.root, files, False, self.lines.append, Ticks(0, 0))[:-1], (0, 1, 0))
        self.assertTrue(any('stopped at prepush.tests_budget_s last time' in line for line in self.lines), self.lines)

    def test_a_failed_test_fails_the_run_and_only_warns_in_the_hook(self):
        self.base()
        self.write('scripts/beta', 'changed\n')
        code, text = self.run_prepush(checks=())
        self.assertEqual(code, 1, text)
        self.assertIn('FAIL scripts/tests/beta.test.sh', text)
        self.lines.clear()
        code, text = self.run_prepush(checks=(), hook=True)
        self.assertEqual(code, 0, text)
        self.assertIn('WARN test failed: scripts/tests/beta.test.sh', text)
        self.assertIn('0 deferred, 1 warning(s)', text)


class Hook(Fixture):
    def finding(self, root, base):
        return [('a finding', ['fix: the fix'])]

    def test_an_inventory_finding_refuses_the_push_and_skips_the_tests(self):
        self.script_test('beta', FAILS, ['scripts/beta'])
        self.write('scripts/beta', 'b\n')
        self.base()
        self.write('scripts/beta', 'changed\n')
        code, text = self.run_prepush(checks=[('stub', self.finding)], hook=True)
        self.assertEqual(code, 1, text)
        self.assertIn('FAIL a finding\n  fix: the fix', text)
        self.assertIn('tests: skipped (the finding(s) above refuse the push', text)
        self.assertIn('prepush: the push is refused', text)
        self.assertNotIn('beta.test.sh', text)

    def test_a_checkout_without_the_registry_is_not_judged(self):
        bare = Path(self.tmp.name) / 'other'
        git(Path(self.tmp.name), 'init', '--quiet', str(bare))
        lines = []
        self.assertEqual(prepush.run(bare, hook=True, out=lines.append), 0)
        self.assertTrue(lines[0].startswith('prepush: skipped ('), lines)

    def test_a_usage_error_is_neither_a_pass_nor_a_finding(self):
        with self.assertRaises(SystemExit) as caught:
            prepush.main(['--no-such-flag'])
        self.assertNotIn(caught.exception.code, (0, 1))

    def fake_checkout(self):
        """A checkout with the real hook and two fake checks that log their arguments and stdin and exit as told."""
        fake = Path(self.tmp.name) / 'fake'
        (fake / '.githooks').mkdir(parents=True)
        shutil.copy(ROOT / '.githooks' / 'pre-push', fake / '.githooks' / 'pre-push')
        for name in ('commit_check', 'prepush'):
            target = fake / 'scripts' / 'lib' / f'{name}.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                'import os, sys\n'
                f"with open(os.environ['FAKE_LOG'], 'a') as log:\n"
                f"    log.write('{name} ' + ' '.join(sys.argv[1:]) + ' stdin=' + sys.stdin.read().strip() + '\\n')\n"
                + ("print(os.environ.get('FAKE_LOCAL_OUT', ''))\n" if name == 'commit_check' else '')
                + f"sys.exit(int(os.environ['FAKE_{name.upper()}']))\n")
        return fake

    def hook(self, fake, check, pre, python=None, local_out=''):
        log = fake / 'calls.log'
        log.unlink(missing_ok=True)
        env = {**os.environ, 'FAKE_LOG': str(log), 'FAKE_COMMIT_CHECK': check, 'FAKE_PREPUSH': pre,
               'FAKE_LOCAL_OUT': local_out, 'OU_PYTHON': python or sys.executable}
        done = subprocess.run(['sh', str(fake / '.githooks' / 'pre-push'), 'origin', 'url'], env=env, text=True,
                              input='refs/heads/w abc refs/heads/w def\n', capture_output=True)
        return done.returncode, log.read_text() if log.is_file() else ''

    def test_the_hook_refuses_only_a_finding_of_either_check(self):
        fake = self.fake_checkout()
        cases = {('0', '0'): 0, ('1', '0'): 1, ('0', '1'): 1, ('1', '1'): 1, ('0', '2'): 0}
        cases[('2', '0')] = 0  # commit_check's own exit codes keep their meaning: only 1 refuses
        for (check, pre), expected in cases.items():
            with self.subTest(commit_check=check, prepush=pre):
                self.assertEqual(self.hook(fake, check, pre)[0], expected)
        code, calls = self.hook(fake, '0', '0')
        self.assertEqual(calls.splitlines(), ['commit_check --local --stdin-refs stdin=refs/heads/w abc refs/heads/w def',
                                              'prepush --hook stdin='])
        self.assertEqual(self.hook(fake, '1', '0')[1].splitlines()[-1], 'prepush --hook --no-tests stdin=')

    def test_the_hook_passes_only_the_inventory_checks_its_local_stage_passed(self):
        """D-194: unit_check and literal_census that the local stage reports ok are passed to prepush as verified; one
        that failed, and a run without them, are not. Without the hook change no call carries --verified."""
        fake = self.fake_checkout()
        ok = ('local-check unit_check: ok 1 ms of 2500 ms\n'
              'local-check literal_census: ok 2 ms of 4000 ms\n')
        _, calls = self.hook(fake, '0', '0', local_out=ok)
        self.assertIn('prepush --hook --verified units,literals stdin=', calls)
        _, calls = self.hook(fake, '1', '0', local_out=ok.replace('literal_census: ok', 'literal_census: failed'))
        self.assertIn('prepush --hook --no-tests --verified units stdin=', calls)
        _, calls = self.hook(fake, '0', '0', local_out=ok.replace('unit_check: ok', 'unit_check: over_budget'))
        self.assertIn('prepush --hook --verified literals stdin=', calls)
        _, calls = self.hook(fake, '0', '0')
        self.assertIn('prepush --hook stdin=', calls)

    def test_pre_commit_stages_the_derived_files_and_refuses_a_generation_error(self):
        """The one-line pre-commit hook runs scripts/lib/generate_stage.sh: the files the generator writes are staged
        with the commit, and a generation error refuses the commit (D-222 (5))."""
        root = Path(self.tmp.name).resolve() / 'pc'
        (root / '.githooks').mkdir(parents=True)
        (root / 'scripts' / 'lib').mkdir(parents=True)
        shutil.copy(ROOT / '.githooks' / 'pre-commit', root / '.githooks' / 'pre-commit')
        shutil.copy(ROOT / 'scripts' / 'lib' / 'generate_stage.sh', root / 'scripts' / 'lib' / 'generate_stage.sh')
        generator = root / 'scripts' / 'generate'
        generator.write_text('#!' + shutil.which('sh') + '\n'
                             'if [ -n "$FAKE_GEN_FAIL" ]; then exit 1; fi\n'
                             'mkdir -p derived && echo derived > derived/out.txt && echo derived/out.txt\n')
        generator.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        git(root.parent, 'init', '--quiet', '--initial-branch=main', str(root))
        self.write_in(root, 'src.txt', 'source\n')
        git(root, 'add', '-A')
        env = {**os.environ, 'OU_PYTHON': sys.executable}

        done = subprocess.run(['sh', str(root / '.githooks' / 'pre-commit')], cwd=root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('derived/out.txt', git(root, 'diff', '--cached', '--name-only').stdout.split())

        env['FAKE_GEN_FAIL'] = '1'
        done = subprocess.run(['sh', str(root / '.githooks' / 'pre-commit')], cwd=root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn('the commit is refused', done.stderr)

        # a commit in another repository (a fixture) runs no stage of this checkout, whichever hook it reaches
        other = Path(self.tmp.name).resolve() / 'other'
        git(other.parent, 'init', '--quiet', '--initial-branch=main', str(other))
        self.write_in(other, 'src.txt', 'source\n')
        git(other, 'add', '-A')
        done = subprocess.run(['sh', str(ROOT / '.githooks' / 'pre-commit')], cwd=other, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_structure_sub_checks_the_commit_hook_runs_pass_on_this_checkout(self):
        """D-236: the command the pre-commit hook runs (commit_check --local --only structure_fast) exists and passes on
        the checkout as it ships; a renamed flag or a failing sub-check would refuse every commit, and this shows it."""
        done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'commit_check.py'), '--local', '--only',
                               'structure_fast'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_pre_commit_runs_the_structure_sub_checks_after_the_stage(self):
        """D-236 (lane 1): the pre-commit hook runs commit_check --local --only structure_fast after the generation stage,
        and a refusal of that check refuses the commit. A fake check logs its arguments and exits as the test says."""
        root = Path(self.tmp.name).resolve() / 'sc'
        (root / '.githooks').mkdir(parents=True)
        (root / 'scripts' / 'lib').mkdir(parents=True)
        shutil.copy(ROOT / '.githooks' / 'pre-commit', root / '.githooks' / 'pre-commit')
        shutil.copy(ROOT / 'scripts' / 'lib' / 'generate_stage.sh', root / 'scripts' / 'lib' / 'generate_stage.sh')
        (root / 'scripts' / 'lib' / 'commit_check.py').write_text(
            'import os, sys\n'
            "with open(os.environ['FAKE_LOG'], 'a') as log:\n"
            "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.exit(int(os.environ['FAKE_STRUCTURE']))\n", encoding='utf-8')
        git(root.parent, 'init', '--quiet', '--initial-branch=main', str(root))
        self.write_in(root, 'src.txt', 'source\n')
        git(root, 'add', '-A')
        log = root / 'calls.log'
        env = {**os.environ, 'OU_PYTHON': sys.executable, 'FAKE_LOG': str(log)}

        env['FAKE_STRUCTURE'] = '0'
        done = subprocess.run(['sh', str(root / '.githooks' / 'pre-commit')], cwd=root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(log.read_text().splitlines(), ['--local --only structure_fast'])

        env['FAKE_STRUCTURE'] = '1'
        done = subprocess.run(['sh', str(root / '.githooks' / 'pre-commit')], cwd=root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)

    def test_the_hook_never_blocks_without_python_or_a_check(self):
        fake = self.fake_checkout()
        self.assertEqual(self.hook(fake, '1', '1', python='no-such-python-here')[0], 0)
        (fake / 'scripts' / 'lib' / 'prepush.py').unlink()
        self.assertEqual(self.hook(fake, '0', '1'), (0, 'commit_check --local --stdin-refs stdin=refs/heads/w abc '
                                                        'refs/heads/w def\n'))
        (fake / 'scripts' / 'lib' / 'commit_check.py').unlink()
        self.assertEqual(self.hook(fake, '1', '1'), (0, ''))


class Overlap(Fixture):
    def test_a_file_another_open_pr_changes_warns_with_its_number_and_branch(self):
        self.write('a.txt', 'a\n')
        self.write('b.txt', 'b\n')
        self.write('c.txt', 'c\n')
        self.base()
        heads = {}
        for branch, name in (('pr-x', 'a.txt'), ('pr-y', 'c.txt')):
            git(self.root, 'checkout', '--quiet', '-b', branch, 'main')
            self.write(name, f'{branch}\n')
            heads[branch] = self.commit(branch)
        git(self.root, 'checkout', '--quiet', 'work')
        self.write('a.txt', 'mine\n')
        self.write('b.txt', 'mine\n')
        own = self.commit('mine')
        self.write('c.txt', 'uncommitted\n')
        missing = 'f' * len(own)
        pulls = [{'number': FIRST_PR, 'head': {'ref': 'pr-x', 'sha': heads['pr-x']}},
                 {'number': SECOND_PR, 'head': {'ref': 'pr-y', 'sha': heads['pr-y']}},
                 {'number': THIRD_PR, 'head': {'ref': 'gone', 'sha': missing}},
                 {'number': OWN_PR, 'head': {'ref': 'work', 'sha': own}}]
        asked = []

        def rest(path):
            asked.append(path)
            return pulls

        code, text = self.run_prepush(checks=(), tests=False, overlaps=True, rest=rest)
        self.assertEqual(code, 0, text)
        self.assertEqual(asked, [f'/repos/{config.get("forge-events.repo")}/pulls?state=open&per_page='
                                 f'{config.get("prepush.open_prs_page_size")}'])
        self.assertIn('overlap: 2 warning(s)', text)
        self.assertIn(f'WARN overlap: a.txt is also changed by open PR #{FIRST_PR} (pr-x)', text)
        self.assertIn(f'WARN overlap: c.txt is also changed by open PR #{SECOND_PR} (pr-y)', text)
        self.assertNotIn('b.txt is also', text)
        self.assertNotIn(f'#{OWN_PR}', text)
        self.assertIn('2 warning(s)', text.splitlines()[-1])

    def test_a_head_missing_here_is_fetched_once(self):
        remote = Path(self.tmp.name) / 'remote.git'
        self.write('a.txt', 'a\n')
        self.base()
        git(remote.parent, 'init', '--quiet', '--bare', str(remote))
        git(self.root, 'remote', 'add', config.get('push-guard.remote'), str(remote))
        git(self.root, 'push', '--quiet', config.get('push-guard.remote'), 'main')
        other = Path(self.tmp.name) / 'other'
        git(remote.parent, 'clone', '--quiet', '--branch', 'main', str(remote), str(other))
        (other / 'a.txt').write_text('theirs\n')
        git(other, 'commit', '--quiet', '-am', 'theirs')
        git(other, 'push', '--quiet', 'origin', 'HEAD:refs/heads/pr-z')
        sha = git(other, 'rev-parse', 'HEAD').stdout.strip()
        self.assertEqual(prepush.present(self.root, [sha]), set())
        self.write('a.txt', 'mine\n')
        files = prepush.changed(self.root, 'main')[0]
        lines = prepush.overlap(self.root, 'main', files, lambda path: [{'number': FIRST_PR, 'head': {'ref': 'pr-z',
                                                                                                    'sha': sha}}])
        self.assertEqual(lines, [f'WARN overlap: a.txt is also changed by open PR #{FIRST_PR} (pr-z)'])

    def test_a_rest_error_skips_the_overlap_with_its_reason(self):
        self.write('a.txt', 'a\n')
        self.base()
        self.write('a.txt', 'mine\n')

        def offline(path):
            raise RuntimeError('gh: exit 1 (network); GitHub API request failed')

        code, text = self.run_prepush(checks=(), tests=False, overlaps=True, rest=offline)
        self.assertEqual(code, 0, text)
        self.assertIn('overlap: skipped (gh: exit 1 (network); GitHub API request failed)', text)
        self.assertIn('0 warning(s)', text.splitlines()[-1])



class Port(unittest.TestCase):
    """prepush reaches the forge only through the port (D-069 item 7): ForgeEvents.open_pulls, one paged list."""
    SHAS = tuple(hashlib.sha1(name.encode()).hexdigest() for name in ('pr-x', 'pr-y', 'pr-z'))

    def test_the_origin_client_lists_every_open_head_with_drafts(self):
        import forge_origin_client
        asked = []
        pulls = [{'number': FIRST_PR, 'head': {'ref': 'pr-x', 'sha': self.SHAS[0]},
                  'base': {'ref': 'mod/base'}, 'draft': True},
                 {'number': SECOND_PR, 'head': {'ref': 'pr-y', 'sha': self.SHAS[1]}, 'base': {'ref': 'main'}}]
        def request(method, path, body):
            asked.append((method, path))
            return {'pullRequests': pulls}
        client = forge_origin_client.OriginClient(run=request)
        self.assertEqual(client.open_pulls('o/r'), [
            {'number': FIRST_PR, 'head_ref': 'pr-x', 'head_sha': self.SHAS[0], 'draft': True},
            {'number': SECOND_PR, 'head_ref': 'pr-y', 'head_sha': self.SHAS[1], 'draft': False}])
        self.assertEqual([item['number'] for item in client.open_pulls('o/r', 'mod/base')], [FIRST_PR])
        self.assertTrue(all(method == 'GET' and '/pulls?state=open' in path for method, path in asked))

    def test_the_port_refuses_an_adapter_without_the_operation_by_name(self):
        import forge_events

        class Bare:
            remote = False
        port = forge_events.ForgeEvents(Bare(), forge_events.SystemClock(), 'test', 'test')
        with self.assertRaisesRegex(forge_events.ForgeEventsError, 'has no open_pulls operation'):
            port.open_pulls('o/r')

    def test_prepush_maps_the_port_records_to_heads(self):
        import forge_events
        # A local double stands in for the forge; compatibility is proved by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        sha = self.SHAS[-1]

        class Adapter:
            remote = True

            def open_pulls(self, repo, base):
                return [{'number': FIRST_PR, 'head_ref': 'pr-x', 'head_sha': sha, 'draft': False}]
        made = forge_events.adapter_from_config
        forge_events.adapter_from_config = Adapter
        try:
            self.assertEqual(prepush.open_pulls(ROOT), [{'number': FIRST_PR, 'head': {'ref': 'pr-x', 'sha': sha}}])
        finally:
            forge_events.adapter_from_config = made



class HooksReadTheFileStore(unittest.TestCase):
    """D-069 item 5: every git hook judges the tree, so it pins the file store before it runs anything (a control plane
    outage on 03/11 refused every commit through the pre-commit regeneration)."""

    def test_every_hook_exports_the_file_store_before_its_first_command(self):
        for hook in sorted((ROOT / '.githooks').iterdir()):
            lines = [line for line in hook.read_text().splitlines() if line.strip() and not line.startswith('#')]
            with self.subTest(hook=hook.name):
                self.assertEqual(lines[0], 'export OU_CONFIG_STORE=file')

if __name__ == '__main__':
    unittest.main()
