"""scripts/lint-ratchet (PADRAO-DEV F4b): the Python lint ratchet. Hermetic: the logic runs on a fake ruff; the
ratchet itself runs the toolchain's ruff over this checkout."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import lint_ratchet  # noqa: E402


def fake_ruff(found):
    """A runner answering every ruff call with `found` restricted to the rules it was asked to select."""
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        select = command[command.index('--select') + 1].split(',')
        ignore = command[command.index('--ignore') + 1].split(',') if '--ignore' in command else []
        chosen = [item for item in found if any(item['code'].startswith(rule) for rule in select)
                  and not any(item['code'].startswith(rule) for rule in ignore)]
        return subprocess.CompletedProcess(command, 0, json.dumps(chosen), '')
    return run, calls


def finding(code, name='scripts/lib/a.py'):
    return {'code': code, 'filename': str(ROOT / name), 'location': {'row': 1}, 'message': 'm'}


class Ratchet(unittest.TestCase):
    def test_a_finding_of_a_selected_rule_fails_and_one_of_an_ignored_rule_does_not(self):
        run, calls = fake_ruff([finding('F821'), finding('F401')])
        found = lint_ratchet.findings(ROOT, select=['F'], ignored=['F401'], run=run, binary='ruff', files=['x.py'])
        self.assertEqual(found, [{'rule': 'F821', 'file': 'scripts/lib/a.py', 'line': 1, 'message': 'm'}])
        self.assertIn('--isolated', calls[0])
        self.assertEqual(calls[0][-1], 'x.py')

    def test_an_ignored_rule_with_no_finding_left_is_stale(self):
        run, _ = fake_ruff([finding('F401')])
        self.assertEqual(lint_ratchet.stale(ROOT, ignored=['F401', 'B905'], run=run, binary='ruff', files=['x.py']),
                         ['B905'])

    def test_the_ignored_list_may_not_grow_past_its_budget(self):
        run, _ = fake_ruff([])
        values = {'rules.lint_select': ['F'], 'rules.lint_ignored': [], 'rules.lint_ignored_max': -1}
        with mock.patch.object(lint_ratchet.config, 'get', side_effect=lambda name, root=None: values[name]):
            self.assertEqual(lint_ratchet.judge(ROOT, run=run, binary='ruff', files=['x.py'])['ignored_over_max'], 1)

    def test_no_ruff_is_an_error_that_names_the_setup(self):
        with mock.patch.object(lint_ratchet, 'ruff_binary', return_value=None):
            with self.assertRaises(RuntimeError) as raised:
                lint_ratchet.findings(ROOT, select=['F'], ignored=[], files=['x.py'])
        self.assertIn('setup.sh', str(raised.exception))


class ThisCheckout(unittest.TestCase):
    def test_the_engines_python_has_no_lint_finding_and_no_stale_ignored_rule(self):
        result = lint_ratchet.judge(ROOT)
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['stale_ignored'], [])
        self.assertEqual(result['ignored_over_max'], 0)


if __name__ == '__main__':
    unittest.main()
