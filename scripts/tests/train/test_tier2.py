"""The merge train v0 (plan v3 M3): tier2 (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import train  # noqa: E402
import train_git  # noqa: E402

config_get = train_git.config.get


class Tier2(unittest.TestCase):
    def test_failing_test_files_from_the_gate_output(self):
        output = ('FAIL unit tests (3.1s; exit 1; log: /tmp/gate-local-unit_tests.log)\n'
                  ' FAIL  src/catalog/a.test.ts > lists courses\n'
                  ' FAIL  src/catalog/a.test.ts > other\n'
                  '  ✘  2 [chromium] › e2e/home.spec.ts:12:3 › renders\n'
                  ' ✓ src/ok.test.ts\n')
        self.assertEqual(train_git.failing_test_files(output), ('src/catalog/a.test.ts', 'e2e/home.spec.ts'))
        self.assertEqual(train_git.Tier2Result(True, None, '').tests, ())


    def test_the_real_gate_runs_the_registry_command_with_a_fresh_cache(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        command = engine_role.setting('train.tier2_command')
        script = directory / command[0]
        script.parent.mkdir(parents=True)
        prefix = engine_role.setting('gate.class_line_prefix')
        script.write_text('#!/usr/bin/env bash\necho "cache=$GATE_BUILD_CACHE_DIR args=$*"\n'
                          f'[[ "${{@: -1}}" == good ]] || {{ echo "FAIL lint"; printf "{prefix} lint\\tcode\\n"; exit 1; }}\n')
        script.chmod(0o755)
        gate = train_git.Tier2Gate(directory)
        ok, bad = gate.run('good'), gate.run('bad')
        self.assertEqual((ok.ok, ok.stage, ok.kind), (True, None, None))
        self.assertEqual((bad.ok, bad.stage, bad.kind), (False, 'lint', 'code'))
        self.assertIn(' '.join(command[1:] + ['good']), ok.log)
        self.assertNotIn(os.environ.get('GATE_BUILD_CACHE_DIR', '<unset>'), ok.log.split('args=')[0])
        self.assertEqual(engine_role.setting('train.tier2_test_cache'), 'box', 'the box cache by default since F70 (#190)')

    def cache_script(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        script = directory / engine_role.setting('train.tier2_command')[0]
        script.parent.mkdir(parents=True)
        script.write_text('#!/usr/bin/env bash\necho "build=${GATE_BUILD_CACHE_DIR:-box} test=${GATE_TEST_CACHE_DIR:-box}"\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return directory

    def test_the_box_cache_leaves_the_command_its_own_caches(self):
        """D-297 (c): under train.tier2_test_cache box the run gets no fresh folder, so gate-dev's box content cache
        (its defaults, or what the environment names) answers what the batch did not change."""
        directory = self.cache_script()
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for name in ('GATE_BUILD_CACHE_DIR', 'GATE_TEST_CACHE_DIR'):
                os.environ.pop(name, None)
            with unittest.mock.patch.object(train_git.config, 'get', side_effect=lambda key, *a, **k: (
                    'box' if key == 'train.tier2_test_cache' else config_get(key, *a, **k))):
                box = train_git.Tier2Gate(directory).run('head')
            with unittest.mock.patch.object(train_git.config, 'get', side_effect=lambda key, *a, **k: (
                    'fresh' if key == 'train.tier2_test_cache' else config_get(key, *a, **k))):
                fresh = train_git.Tier2Gate(directory).run('head')
        self.assertIn('build=box test=box', box.log)
        self.assertNotIn('build=box', fresh.log)
        self.assertNotIn('test=box', fresh.log)

    def test_an_unknown_cache_is_refused(self):
        with self.assertRaises(ValueError):
            engine_role.CommandGate(self.cache_script(), ['x'], 1, 1, 'tier 2', 'train.tier2_timeout_s', 'warm')


    def test_the_real_gate_hands_the_batch_variables_to_the_command(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        script = directory / engine_role.setting('train.tier2_command')[0]
        script.parent.mkdir(parents=True)
        script.write_text(f'#!/usr/bin/env bash\necho "members=${train.BATCH_MEMBERS_ENV} base=${train.BATCH_BASE_ENV}"\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        done = train_git.Tier2Gate(directory).run('head', env={train.BATCH_MEMBERS_ENV: 'a b',
                                                                train.BATCH_BASE_ENV: 'c'})
        self.assertIn('members=a b base=c', done.log)

    def gate(self, output):
        """A Tier2Gate whose command prints `output` and fails."""
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        script = directory / engine_role.setting('train.tier2_command')[0]
        script.parent.mkdir(parents=True)
        (directory / 'output').write_text(output)
        script.write_text(f'#!/usr/bin/env bash\ncat {directory / "output"}\nexit 1\n')
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return train_git.Tier2Gate(directory).run('head')

    def test_the_class_line_names_the_stage_and_class_not_the_first_fail_line(self):
        prefix = engine_role.setting('gate.class_line_prefix')
        result = self.gate('FAIL gate preflight\nFAIL local postgres did not start\n'
                           f'{prefix} local database\tenv\nFAIL unit tests\n{prefix} unit tests\tcode\n')
        self.assertEqual((result.stage, result.kind), ('local database', 'env'))

    def test_the_class_comes_from_the_whole_output_never_the_log_tail(self):
        prefix = engine_role.setting('gate.class_line_prefix')
        tail = engine_role.setting('train.tier2_log_chars')  # the class line falls outside the log excerpt
        result = self.gate(f'FAIL db schema\n{prefix} db schema\tcontract\n' + '.' * tail)
        self.assertEqual((result.stage, result.kind, len(result.log)), ('db schema', 'contract', tail))
        self.assertNotIn(prefix, result.log)

    def test_a_red_run_without_a_class_line_is_classified_over_its_whole_output(self):
        result = self.gate('FAIL local postgres did not start\n' + '.' * engine_role.setting('train.tier2_log_chars'))
        self.assertEqual((result.stage, result.kind), (engine_role.setting('train.tier2_command')[0], 'env'))
        self.assertEqual(self.gate('FAIL lint\n').kind, 'code')


if __name__ == '__main__':
    unittest.main()
