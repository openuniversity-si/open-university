"""GATE-SPEED's diagnóstico (D-115, D-116): scripts/test-suite --metrics measures the main metric and the guards the same
way every phase. The suite pass and the coverage pass are replaced by doubles: no test runs a test suite here."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import hermetic  # noqa: E402
import test_metrics  # noqa: E402


def result(name, passed=True, cached=False):
    return {'test': name, 'result': 'PASS' if passed else 'FAIL', 'cached': cached, 'key': None, 'source': 's', 'tail': []}


class Counts(unittest.TestCase):
    def test_test_functions_counts_def_test_lines_under_scripts_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp) / 'scripts' / 'tests'
            (tests / 'train').mkdir(parents=True)
            (tests / 'test_a.py').write_text('def test_one():\n    pass\n\ndef helper():\n    pass\n')
            (tests / 'train' / 'test_b.py').write_text('class T:\n    def test_two(self):\n        pass\n')
            (tests / 'notes.txt').write_text('def test_not_python():\n')
            self.assertEqual(test_metrics.test_functions(tmp), len(['test_one', 'test_two']))

    def test_this_checkout_has_test_functions(self):
        self.assertGreater(test_metrics.test_functions(ROOT), 0)


class Passes(unittest.TestCase):
    def test_a_pass_points_the_store_at_the_given_directory_and_restores_the_environment(self):
        seen = {}

        def run(scripts, root, location, source, tool_root, concurrency=None, timings=None):
            seen['location'], seen['workers'] = location, concurrency
            timings.update({name: 0 for name in scripts})
            return [result(name) for name in scripts]
        with tempfile.TemporaryDirectory() as store, \
                mock.patch.object(test_metrics.gate_script_tests, 'discover', return_value=['a.test.sh', 'b.test.sh']), \
                mock.patch.object(test_metrics.gate_test_cache, 'run', side_effect=run), \
                mock.patch.dict(os.environ, {test_metrics.gate_test_cache.STORE_ENV: 'kept'}):
            results, wall, cpu, timings = test_metrics.suite_pass(ROOT, ROOT, store, workers=len('ab'))
            self.assertEqual(os.environ[test_metrics.gate_test_cache.STORE_ENV], 'kept')
        self.assertEqual(seen['location'], Path(store))
        self.assertEqual(seen['workers'], len('ab'))
        self.assertEqual([item['test'] for item in results], ['a.test.sh', 'b.test.sh'])
        self.assertEqual(sorted(timings), ['a.test.sh', 'b.test.sh'])
        self.assertGreaterEqual(wall, 0)
        self.assertGreaterEqual(cpu, 0)

    def test_a_pass_takes_no_pass_from_the_shared_results_and_restores_them(self):
        """VAZÃO F40: scripts/test-suite exports OU_SHARED_RESULTS=1; a cold pass that kept it answered 20 of 136 tests
        from another box's results and timed none of them."""
        seen = {}

        def run(scripts, root, location, source, tool_root, concurrency=None, timings=None):
            seen['shared'] = os.environ.get(test_metrics.shared_results.ENV)
            seen['enabled'] = test_metrics.shared_results.enabled()
            timings.update({name: 0 for name in scripts})
            return [result(name) for name in scripts]
        with tempfile.TemporaryDirectory() as store, \
                mock.patch.object(test_metrics.gate_script_tests, 'discover', return_value=['a.test.sh']), \
                mock.patch.object(test_metrics.gate_test_cache, 'run', side_effect=run), \
                mock.patch.dict(os.environ, {test_metrics.shared_results.ENV: '1'}):
            test_metrics.suite_pass(ROOT, ROOT, store)
            self.assertEqual(os.environ[test_metrics.shared_results.ENV], '1')
        self.assertIsNone(seen['shared'])
        self.assertFalse(seen['enabled'])

    def test_write_costs_holds_every_judged_test_and_refuses_a_pass_that_answered_one_by_key(self):
        whole = {'guards': {'script_tests': len('ab'), 'by_key': []}, 'slowest': [['b.test.sh', 2.04], ['a.test.sh', 1]]}
        partial = {'guards': {'script_tests': len('ab'), 'by_key': ['b.test.sh']}, 'slowest': [['a.test.sh', 1]]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'costs.json'
            test_metrics.write_costs(whole, path)
            self.assertEqual(json.loads(path.read_text()), {'a.test.sh': 1, 'b.test.sh': 2.0})
            with self.assertRaisesRegex(ValueError, 'timed 1 of 2 .*b.test.sh'):
                test_metrics.write_costs(partial, path)
            self.assertEqual(json.loads(path.read_text()), {'a.test.sh': 1, 'b.test.sh': 2.0})

    def test_write_costs_takes_each_tests_least_wall_over_the_cold_passes(self):
        """VAZÃO F52: one pass wrote 32-34 s for budgets, gate-select, lessons and gate-runner-grace, which take 2-4 s
        alone; a wait only adds to a wall, so the least wall of two passes is the test's own cost."""
        stalled = {'timed': {'budgets.test.sh': 33.9, 'train.test.sh': 21.4}, 'by_key': []}
        calm = {'timed': {'budgets.test.sh': 1.42, 'train.test.sh': 22.0}, 'by_key': []}
        document = {'guards': {'script_tests': len('ab'), 'by_key': []}, 'slowest': [], 'cold_passes': [stalled, calm]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'costs.json'
            path.write_text(json.dumps({'budgets.test.sh': 3.8, 'train.test.sh': 21.4}))
            test_metrics.write_costs(document, path)
            self.assertEqual(json.loads(path.read_text()), {'budgets.test.sh': 1.4, 'train.test.sh': 21.4})

    def test_write_costs_refuses_when_any_cold_pass_left_a_test_untimed(self):
        whole = {'timed': {'a.test.sh': 1, 'b.test.sh': 2}, 'by_key': []}
        for later in ({'timed': {'a.test.sh': 1}, 'by_key': ['b.test.sh']},
                      {'timed': {'a.test.sh': 1, 'c.test.sh': 2}, 'by_key': []}):
            document = {'guards': {'script_tests': len('ab'), 'by_key': []}, 'slowest': [], 'cold_passes': [whole, later]}
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'costs.json'
                with self.assertRaisesRegex(ValueError, 'untimed: b.test.sh'):
                    test_metrics.write_costs(document, path)
                self.assertFalse(path.exists())

    def test_one_pass_is_refused_a_jump_above_the_ratio_and_two_passes_confirm_it(self):
        held = {'budgets.test.sh': 3.8, 'quick.test.sh': 0.1, 'new.test.sh': 0.5}
        one = {'timed': {'budgets.test.sh': 33.9, 'quick.test.sh': 0.6, 'new.test.sh': 0.5}, 'by_key': []}
        again = {'timed': {'budgets.test.sh': 30.2, 'quick.test.sh': 0.7, 'new.test.sh': 0.5}, 'by_key': []}
        tests = len(one['timed'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'costs.json'
            path.write_text(json.dumps(held))
            single = {'guards': {'script_tests': tests, 'by_key': []}, 'slowest': [], 'cold_passes': [one]}
            with self.assertRaisesRegex(ValueError, r'1 hint\(s\) above 3x .*budgets.test.sh 3.8 -> 33.9 s'):
                test_metrics.write_costs(single, path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text()), held)
            # the quick test jumped 6x but stays under the floor: it moves no order
            calm = {'timed': {**one['timed'], 'budgets.test.sh': 4.1}, 'by_key': []}
            test_metrics.write_costs({**single, 'cold_passes': [calm]}, path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text())['quick.test.sh'], 0.6)
            path.write_text(json.dumps(held))
            test_metrics.write_costs({**single, 'cold_passes': [one, again]}, path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text())['budgets.test.sh'], 30.2)

    def test_one_cost_runs_only_that_test_each_pass_on_its_own_store(self):
        """VAZÃO F67: a new test gets its hint without a whole-suite measure."""
        seen = []

        def run(scripts, root, location, source, tool_root, concurrency=None, timings=None):
            seen.append((list(scripts), location))
            timings.update({name: 1.25 + len(seen) for name in scripts})
            return [result(name) for name in scripts]
        with mock.patch.object(test_metrics.gate_script_tests, 'discover', return_value=('a.test.sh', 'b.test.sh')), \
                mock.patch.object(test_metrics.gate_test_cache, 'run', side_effect=run):
            test, walls = test_metrics.one_cost(ROOT, ROOT, 'b.test.sh', passes=len('ab'))
            self.assertEqual((test, walls), ('b.test.sh', [2.25, 3.25]))
            self.assertEqual([scripts for scripts, _ in seen], [['b.test.sh'], ['b.test.sh']])
            self.assertNotEqual(seen[0][1], seen[1][1])
            self.assertEqual(test_metrics.one_cost(ROOT, ROOT, str(ROOT / 'a.test.sh'), passes=1)[0], 'a.test.sh')
            with self.assertRaisesRegex(ValueError, 'c.test.sh is not a script test'):
                test_metrics.one_cost(ROOT, ROOT, 'c.test.sh', passes=1)

    def test_one_cost_refuses_a_failed_or_keyed_run(self):
        for failed in (result('a.test.sh', passed=False), result('a.test.sh', cached=True)):
            def run(scripts, root, location, source, tool_root, concurrency=None, timings=None, outcome=failed):
                return [outcome]
            with self.subTest(failed=failed), \
                    mock.patch.object(test_metrics.gate_script_tests, 'discover', return_value=('a.test.sh',)), \
                    mock.patch.object(test_metrics.gate_test_cache, 'run', side_effect=run), \
                    self.assertRaisesRegex(ValueError, 'did not run to a PASS'):
                test_metrics.one_cost(ROOT, ROOT, 'a.test.sh', passes=1)

    def test_write_one_cost_merges_the_least_wall_and_keeps_every_other_hint(self):
        held = {'a.test.sh': 1.6, 'b.test.sh': 0.5}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'costs.json'
            self.assertEqual(test_metrics.write_one_cost('new.test.sh', [2.34], path), 2.3)
            self.assertEqual(json.loads(path.read_text()), {'new.test.sh': 2.3})
            path.write_text(json.dumps(held))
            test_metrics.write_one_cost('new.test.sh', [33.9, 2.04], path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text()), {**held, 'new.test.sh': 2.0})
            self.assertEqual(list(json.loads(path.read_text())), sorted({**held, 'new.test.sh': 0}))
            with self.assertRaisesRegex(ValueError, r'a.test.sh 1.6 -> 9.0 s, above 3x'):
                test_metrics.write_one_cost('a.test.sh', [9.0], path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text())['a.test.sh'], 1.6)
            test_metrics.write_one_cost('a.test.sh', [9.0, 8.8], path, ratio=len('abc'), floor=1)
            self.assertEqual(json.loads(path.read_text())['a.test.sh'], 8.8)

    def test_the_registry_holds_the_passes_and_the_guard(self):
        setting = test_metrics.gate_test_cache.setting
        self.assertGreaterEqual(setting('cost_hint_passes'), len('ab'))
        self.assertGreater(setting('cost_hint_jump_ratio'), 1)
        self.assertGreaterEqual(setting('cost_hint_jump_floor_s'), 0)

    def test_extra_cold_passes_run_after_the_main_one_each_on_its_own_store(self):
        stores = []

        def suite_pass(root, tool_root, store, workers=None):
            stores.append(str(store))
            seconds = len(stores)
            return [result('a.test.sh')], seconds, 0, {'a.test.sh': seconds}
        with mock.patch.object(test_metrics, 'suite_pass', side_effect=suite_pass):
            out = test_metrics.measure(ROOT, ROOT, workers=1, cold=len('abc'))
        self.assertEqual(out['main']['value'], 1)
        self.assertEqual(len(set(stores)), len('abc'))
        self.assertEqual([one['timed']['a.test.sh'] for one in out['cold_passes']], [1, len('ab'), len('abc')])
        self.assertEqual(out['slowest'], [['a.test.sh', 1]])

    def test_the_document_holds_the_main_metric_the_guards_and_the_slowest_tests(self):
        short, long_, wall, cpu, warm_wall, covered_pct = (len('a') / len('abcd') * n for n in range(1, len('abcdefg')))
        cold = ([result('a.test.sh'), result('b.test.sh', passed=False)], wall, cpu,
                {'a.test.sh': short, 'b.test.sh': long_})
        warm = ([result('a.test.sh', cached=True), result('b.test.sh')], warm_wall, 0, {})
        with mock.patch.object(test_metrics, 'suite_pass', side_effect=[cold, warm, warm, warm]), \
                mock.patch.object(test_metrics, 'coverage_pass', return_value={'pct': covered_pct}) as covered:
            out = test_metrics.measure(ROOT, ROOT, workers=len('ab'), warm=len('abc'), coverage_library='lib')
        self.assertEqual(out['main'], {'name': 'cold_wall_s', 'better': 'lower', 'value': wall})
        guards = out['guards']
        self.assertEqual(guards['cpu_s'], cpu)
        self.assertEqual(guards['warm_wall_s'], warm_wall)
        self.assertEqual(guards['warm_walls'], [warm_wall] * len('abc'))
        self.assertEqual(guards['failed'], ['b.test.sh'])
        self.assertEqual(guards['by_key'], [])
        self.assertEqual(guards['script_tests'], len('ab'))
        self.assertEqual(guards['warm_by_key'], 1)
        self.assertEqual(guards['coverage'], {'pct': covered_pct})
        self.assertEqual([name for name, _ in out['slowest']], ['b.test.sh', 'a.test.sh'])
        covered.assert_called_once()

    def test_main_runs_the_registry_passes_only_when_it_writes_the_costs(self):
        document = {'box': {'cpus': 1, 'workers': 1}, 'main': {'name': 'cold_wall_s', 'better': 'lower', 'value': 1},
                    'guards': {'cpu_s': 1, 'script_tests': 1, 'test_functions': 1, 'failed': [], 'by_key': []},
                    'slowest': [['a.test.sh', 1]]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(test_metrics, 'measure', return_value=document) as measured, \
                redirect_stdout(io.StringIO()):
            args = types.SimpleNamespace(root=str(ROOT), workers=None, warm=False, coverage=None, json=None)
            self.assertEqual(test_metrics.main(args, tool_root=str(ROOT)), 0)
            self.assertEqual(measured.call_args.kwargs['cold'], 1)
            args.write_costs = str(Path(tmp) / 'costs.json')
            self.assertEqual(test_metrics.main(args, tool_root=str(ROOT)), 0)
            self.assertEqual(measured.call_args.kwargs['cold'], test_metrics.gate_test_cache.setting('cost_hint_passes'))
            self.assertEqual(json.loads(Path(args.write_costs).read_text()), {'a.test.sh': 1})

    def test_main_with_a_test_measures_only_that_test_and_merges_its_hint(self):
        """VAZÃO F67: `scripts/test-suite --metrics --write-costs FILE --test PATH` runs no suite pass."""
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(test_metrics, 'measure') as measured, \
                mock.patch.object(test_metrics, 'one_cost', return_value=('new.test.sh', [2.51, 2.38])) as one:
            path = Path(tmp) / 'costs.json'
            path.write_text(json.dumps({'a.test.sh': 1.6}))
            args = types.SimpleNamespace(root=str(ROOT), workers=None, warm=False, coverage=None, json=None,
                                         write_costs=str(path), test='scripts/tests/new.test.sh')
            printed = io.StringIO()
            with redirect_stdout(printed):
                self.assertEqual(test_metrics.main(args, tool_root=str(ROOT)), 0)
            self.assertFalse(measured.called)
            self.assertEqual(one.call_args.args[2], 'scripts/tests/new.test.sh')
            self.assertEqual(json.loads(path.read_text()), {'a.test.sh': 1.6, 'new.test.sh': 2.4})
            self.assertIn('new.test.sh 2.4 s', printed.getvalue())
            one.side_effect = ValueError('write-costs: new.test.sh did not run to a PASS (FAIL); no hint written')
            with redirect_stdout(io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(test_metrics.main(args, tool_root=str(ROOT)), 1)
                args.write_costs = None
                self.assertEqual(test_metrics.main(args, tool_root=str(ROOT)), len('ab'))
            self.assertEqual(json.loads(path.read_text()), {'a.test.sh': 1.6, 'new.test.sh': 2.4})

    def test_the_suite_command_takes_the_test_flag(self):
        import gate_test_cache
        with mock.patch.object(test_metrics, 'main', return_value=0) as main:
            self.assertEqual(gate_test_cache.main(['gate_test_cache', 'suite', '--metrics', '--write-costs', 'c.json',
                                                   '--test', 'scripts/tests/new.test.sh']), 0)
        self.assertEqual((main.call_args.args[0].write_costs, main.call_args.args[0].test),
                         ('c.json', 'scripts/tests/new.test.sh'))

    def test_main_prints_one_line_writes_the_document_and_fails_on_a_failed_test(self):
        document = {'box': {'cpus': 1, 'workers': 1}, 'main': {'name': 'cold_wall_s', 'better': 'lower', 'value': 1},
                    'guards': {'cpu_s': 1, 'script_tests': 1, 'test_functions': 1, 'failed': ['x.test.sh']},
                    'slowest': []}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(test_metrics, 'measure', return_value=document):
            args = types.SimpleNamespace(root=str(ROOT), workers=None, warm=False, coverage=None,
                                         json=str(Path(tmp) / 'out.json'))
            printed = io.StringIO()
            with redirect_stdout(printed):
                code = test_metrics.main(args, tool_root=str(ROOT))
            self.assertTrue((Path(tmp) / 'out.json').is_file())
        self.assertEqual(code, 1)
        self.assertIn('main cold_wall_s 1.00 on 1 CPUs', printed.getvalue())
        self.assertIn('failed 1', printed.getvalue())


class CoverageHook(unittest.TestCase):
    def test_the_hermetic_sitecustomize_survives_a_missing_coverage_module(self):
        """COVERAGE_PROCESS_START without coverage.py importable: the test process runs as before."""
        env = dict(os.environ, **hermetic.store_env(), COVERAGE_PROCESS_START=os.devnull,
                   PYTHONPATH=str(ROOT / 'scripts' / 'lib' / 'hermetic'))
        done = subprocess.run([sys.executable, '-c', 'print("ran")'], capture_output=True, text=True, env=env,
                              check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), 'ran')


if __name__ == '__main__':
    unittest.main()
