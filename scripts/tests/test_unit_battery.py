"""The unit battery, tier 1 for units (P-12, veto V5): its steps from battery.unit_steps, the per-unit types project,
the contract, the time limit battery.unit_time_limit and the engine.step.measured events.

The registry's steps are the engine's (its script tests); the TypeScript steps of a product are the fixture's own
(FIXTURE_STEPS), written into the fixture's copy of battery.json, since the engine has no TypeScript product (D-298).

Fixture git repositories in a temporary directory with copies of the registry and the contracts; the commands run
through an injected runner and the time comes from an injected clock, so no tool, network or wall clock is used.
"""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import unit_battery  # noqa: E402
import units  # noqa: E402

COPIED = ('contracts/units/unit.v1.json', 'contracts/config/registry.v1.json', 'config/registry/units.json',
          'config/registry/config.json', 'config/registry/forge-events.json', 'config/registry/generate.json',
          'config/registry/battery.json')
OWNER = config.get('units.owners')[0]
LIMIT_S = config.get('battery.unit_time_limit')
STEPS = {step['name']: step for step in config.get('battery.unit_steps')}
SCRIPTS = next(name for name, step in STEPS.items() if step['mode'] == 'each')
# The fixture's TypeScript project is a generic product: the registry's project folder is rewritten to it in the
# fixture's copy of battery.json (OU-DECOUPLE F4 (D-111)), and its steps are the fixture's (D-298).
REGISTRY_PROJECT = Path(config.get('battery.project_tsconfig')).parent.as_posix()
PROJECT = 'products/demo'
TYPES = 'types'
FIXTURE_STEPS = [
    {'name': TYPES, 'mode': 'types', 'cwd': PROJECT,
     'include': [f'{PROJECT}/**/*.ts', f'{PROJECT}/**/*.tsx'],
     'commands': [['node_modules/.bin/tsc', '--noEmit', '-p', '{project}']]},
    {'name': 'unit-tests', 'mode': 'files', 'cwd': PROJECT,
     'include': [f'{PROJECT}/**/*.test.ts', f'{PROJECT}/**/*.test.tsx'], 'exclude': ['**/*.int.test.ts'],
     'commands': [['node_modules/.bin/vitest', 'run', '--project', 'unit', '{files}']]},
    {'name': 'int-tests', 'mode': 'files', 'cwd': PROJECT, 'include': [f'{PROJECT}/**/*.int.test.ts'],
     'commands': [['node_modules/.bin/vitest', 'run', '--project', 'int', '{files}']]},
]
TSCONFIG = f'{PROJECT}/tsconfig.json'
PROJECT_TSCONFIG = config.get('battery.project_tsconfig').replace(REGISTRY_PROJECT, PROJECT, 1)


def manifest(unit, paths, **extra):
    return {'id': unit, 'purpose': f'The {unit} unit.', 'cell': 'demo', 'owner': OWNER, 'paths': paths, **extra}


class Clock:
    """Each reading is `step` later than the previous one."""

    def __init__(self, step_ms=1):
        self.moment, self.step, self.lock = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc), step_ms, threading.Lock()

    def now(self):
        with self.lock:
            self.moment += timedelta(milliseconds=self.step)
            return self.moment


class Runner:
    def __init__(self, failing=()):
        self.calls, self.failing, self.lock = [], failing, threading.Lock()

    def __call__(self, argv, cwd, log):
        with self.lock:
            self.calls.append((tuple(argv), cwd))
        if any(word in ' '.join(argv) for word in self.failing):
            log.write(b'error: it broke\n')
            return 1
        return 0


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        battery = json.loads((ROOT / 'config/registry/battery.json').read_text().replace(f'"{REGISTRY_PROJECT}', f'"{PROJECT}'))
        battery['properties']['battery.unit_steps']['default'] = FIXTURE_STEPS + list(STEPS.values())
        self.write('config/registry/battery.json', battery)
        self.write('docs/domain/DECISIONS.md', '| Id | Date |\n|---|---|\n| D-067 | today |\n')
        self.write(TSCONFIG, '{"compilerOptions": {"paths": {}}}\n')
        self.unit(manifest('progress', [f'{PROJECT}/src/progress/**']))
        self.unit(manifest('reader', [f'{PROJECT}/src/reader/**'], requires={'progress': '^1'}))
        self.unit(manifest('engine-x', ['scripts/lib/x.py', 'scripts/tests/x.test.sh']))
        for name in ('src/progress/rules.ts', 'src/progress/rules.test.ts', 'src/progress/store.int.test.ts',
                     'src/reader/view.ts', 'src/reader/view.test.ts', 'src/reader/progress.contract.test.ts'):
            self.write(f'{PROJECT}/{name}', 'export const x = 1;\n')
        self.write('scripts/lib/x.py', '')
        self.write('scripts/tests/x.test.sh', '')
        self.write('scripts/tests/covers/x.json', {'script': 'scripts/tests/x.test.sh',
                                                 'covers': ['scripts/lib/x.py']})
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def unit(self, data):
        self.write(f'units/{data["id"]}/unit.json', data)

    def plan(self, unit='progress'):
        return {step['name']: step for step in unit_battery.plan(unit, self.root)}

    def run_battery(self, unit='progress', runner=None, clock=None):
        return unit_battery.run(unit, self.root, clock or Clock(), runner or Runner())


class Plan(Fixture):
    def test_p12_each_test_file_goes_to_the_step_of_its_kind(self):
        steps = self.plan()
        by_file = {Path(path).name: name for name, step in steps.items() if name != TYPES for path in step['files']}
        self.assertNotEqual(by_file['rules.test.ts'], by_file['store.int.test.ts'])  # each kind runs in its own project
        self.assertEqual(by_file['progress.contract.test.ts'], by_file['rules.test.ts'])  # a consumer's contract test
        self.assertNotIn('view.test.ts', by_file)  # the consumer's own tests are its battery, not this one
        self.assertNotIn(SCRIPTS, steps)

    def test_a_step_takes_globs_from_registry_entries(self):
        files = [f'{PROJECT}/src/reader/view.test.ts', f'{PROJECT}/src/reader/progress.contract.test.ts']
        step = {'name': 'x', 'mode': 'files', 'cwd': PROJECT, 'commands': [['true']]}
        chosen = unit_battery.select(dict(step, include_entries=['battery.contract_test_globs']), files, self.root)
        self.assertEqual(chosen, files[1:])
        chosen = unit_battery.select(dict(step, include=['**/*.test.ts'], exclude_entries=['battery.contract_test_globs']),
                                     files, self.root)
        self.assertEqual(chosen, files[:1])

    def test_the_registry_steps_are_the_engines_script_tests(self):
        self.assertEqual([step['cwd'] for step in STEPS.values()], ['.'] * len(STEPS))  # D-298: no products/web step

    def test_p12_test_commands_name_the_files_relative_to_their_cwd(self):
        step = next(step for name, step in self.plan().items() if 'src/progress/rules.test.ts' in ' '.join(
            step['commands'][0]))
        self.assertIn('src/progress/rules.test.ts', step['commands'][0])
        self.assertEqual(step['cwd'], PROJECT)

    def test_plan_v3_7_2_the_types_project_is_the_unit_files_only(self):
        step = self.plan()[TYPES]
        path, text = step['project']
        document = json.loads(text)
        self.assertEqual(document['extends'], str(self.root / PROJECT_TSCONFIG))
        include = document['include']
        self.assertIn(str(self.root / PROJECT / 'src/progress/rules.ts'), include)
        self.assertNotIn(str(self.root / PROJECT / 'src/reader/view.ts'), include)
        self.assertTrue(str(path).startswith(str(self.root / config.get('battery.unit_types_dir', self.root))))
        self.assertIn(str(path), step['commands'][-1])

    def test_p12_an_engine_unit_runs_its_shell_tests_one_by_one(self):
        steps = self.plan('engine-x')
        self.assertEqual(list(steps), [SCRIPTS])
        self.assertEqual(steps[SCRIPTS]['commands'], [[part.replace('{file}', 'scripts/tests/x.test.sh')
                                                       for part in STEPS[SCRIPTS]['commands'][0]]])

    def test_production_gets_the_matching_suite_without_owning_tests(self):
        self.unit(manifest('engine-x', ['scripts/lib/x.py']))
        self.write('scripts/tests/unrelated.test.sh', '')
        self.write('scripts/tests/covers/unrelated.json', {'script': 'scripts/tests/unrelated.test.sh',
                                                         'covers': ['scripts/lib/other.py']})
        units.reset()
        step = self.plan('engine-x')[SCRIPTS]
        self.assertEqual(step['files'], ['scripts/tests/x.test.sh'])
        self.assertEqual(step['commands'], [[part.replace('{file}', 'scripts/tests/x.test.sh')
                                            for part in STEPS[SCRIPTS]['commands'][0]]])

    def test_origin_production_derives_its_forge_events_proof_from_covers(self):
        paths = ['scripts/lib/forge_origin.py', 'scripts/lib/forge_origin_client.py']
        self.unit(manifest('engine-forge-origin', paths))
        for path in paths:
            self.write(path, '')
        self.write('scripts/tests/forge-events.test.sh', '')
        self.write('scripts/tests/covers/forge-events.json', {'script': 'scripts/tests/forge-events.test.sh',
                                                            'covers': paths})
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        steps = self.plan('engine-forge-origin')
        self.assertEqual(list(steps), [SCRIPTS])
        self.assertEqual(steps[SCRIPTS]['files'], ['scripts/tests/forge-events.test.sh'])

    def test_production_without_any_association_cannot_pass_empty(self):
        self.unit(manifest('engine-x', ['scripts/lib/x.py']))
        self.write('scripts/tests/covers/x.json', {'script': 'scripts/tests/x.test.sh',
                                                 'covers': ['docs/**']})
        units.reset()
        report = self.run_battery('engine-x')
        self.assertEqual(report['result'], 'fail')
        self.assertIn('engine-x: production file scripts/lib/x.py has no proof in covers',
                      unit_battery.text(report))

    def test_each_unassociated_production_file_refuses_the_battery(self):
        self.write('scripts/lib/orphan.py', '')
        self.unit(manifest('engine-x', ['scripts/lib/x.py', 'scripts/lib/orphan.py']))
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        report = self.run_battery('engine-x')
        self.assertEqual(report['result'], 'fail')
        output = unit_battery.text(report)
        self.assertIn('engine-x: production file scripts/lib/orphan.py has no proof in covers', output)
        self.assertIn(SCRIPTS, self.plan('engine-x'))

    def test_docs_do_not_select_a_suite_even_when_declared_in_covers(self):
        self.write('docs/example.md', '')
        self.unit(manifest('docs-only', ['docs/example.md']))
        self.write('scripts/tests/covers/x.json', {'script': 'scripts/tests/x.test.sh',
                                                 'covers': ['docs/**']})
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        self.assertEqual(self.plan('docs-only'), {})

    def test_p12_a_contract_entry_outside_the_unit_is_red(self):
        self.unit(manifest('progress', [f'{PROJECT}/src/progress/**'], contract={'entry': 'contract.ts',
                                                                                 'version': '1.0.0'}))
        units.reset()
        report = self.run_battery()
        self.assertEqual(report['result'], 'fail')
        self.assertIn('contract', report['failing'])
        self.write(f'{PROJECT}/src/progress/contract.ts', 'export {};\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        self.assertEqual(self.run_battery()['result'], 'ok')


class Run(Fixture):
    def test_v5_every_step_runs_and_the_battery_is_green(self):
        runner = Runner()
        report = self.run_battery(runner=runner)
        self.assertEqual((report['result'], report['failing'], report['over_limit']), ('ok', [], False))
        self.assertEqual(len(runner.calls), sum(len(step['commands']) for step in self.plan().values()))
        self.assertTrue((self.root / config.get('battery.unit_types_dir', self.root) / 'progress.tsconfig.json').is_file())

    def test_v5_a_failing_step_makes_the_battery_red_with_its_output(self):
        report = self.run_battery(runner=Runner(failing=('--noEmit',)))
        self.assertEqual((report['result'], report['failing']), ('fail', [TYPES]))
        self.assertIn('error: it broke', next(step['output'] for step in report['steps'] if step['name'] == TYPES))

    def test_d069_14_a_battery_over_its_time_limit_is_red(self):
        report = self.run_battery(clock=Clock(step_ms=int(LIMIT_S * 1000)))
        self.assertEqual((report['result'], report['failing'], report['over_limit']), ('fail', [], True))
        self.assertIn('battery.unit_time_limit', unit_battery.text(report))

    def test_an_unknown_unit_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(unit_battery.main(['nope', '--root', str(self.root)]), 2)
        self.assertIn('unknown unit nope', err.getvalue())


class Emit(Fixture):
    def test_d069_6_one_measured_step_per_step_and_one_for_the_battery(self):
        port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), Clock(), config.get('battery.unit_producer'),
                                        'test')
        report = unit_battery.emit('progress', self.root, pr=7, port=port, sha='a' * 40, premises=['P-12'],
                                   runner=Runner())
        events = port.read(config.get('forge-events.repo'), 7, strict=True)
        name = config.get('battery.unit_step')
        self.assertEqual([event['payload']['step'] for event in events],
                         [f'{name}.{step["name"]}' for step in report['steps']] + [name])
        self.assertEqual({event['payload']['unit'] for event in events}, {'progress'})
        self.assertEqual(events[-1]['payload']['result'], 'ok')
        unit_battery.emit('progress', self.root, pr=7, port=port, sha='a' * 40, premises=['P-12'], runner=Runner())
        self.assertEqual(len(port.read(config.get('forge-events.repo'), 7)), len(events))  # idempotent


if __name__ == '__main__':
    unittest.main()
