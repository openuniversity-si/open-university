"""scripts/padrao-metrics (PADRAO-DEV F1): the gate selection's completeness from strace traces. Hermetic: no network,
no strace run (the runner is injected), no repository but a temporary one."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import padrao_metrics  # noqa: E402

FAKE_ROOT = Path('/work/repo')
FILES = {'scripts/lib/a.py', 'scripts/lib/b.py', 'scripts/lib/c.py', 'scripts/tool', 'scripts/tests/test_a.py',
         'scripts/tests/a.test.sh', 'scripts/tests/b.test.sh', 'config/registry/gate.json', 'docs/x.md'}


def opened(*paths):
    """A strace -f output in which every path was opened with success, plus failed calls that must not count."""
    lines = [f'101   openat(AT_FDCWD, "{FAKE_ROOT}/{path}", O_RDONLY|O_CLOEXEC) = 3' for path in paths]
    lines.append(f'101   openat(AT_FDCWD, "{FAKE_ROOT}/scripts/lib/c.py", O_RDONLY) = -1 ENOENT (No such file or directory)')
    lines.append('102   openat(AT_FDCWD, "/usr/lib/python3.12/os.py", O_RDONLY|O_CLOEXEC) = 4')
    return '\n'.join(lines)


MAPPING = {
    'fallback': ('scripts/lib/gate_script_tests.py',),
    'scripts': ('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'),
    'tests': (
        {'script': 'scripts/tests/a.test.sh', 'covers': ('scripts/tests/test_a.py', 'scripts/lib/a.py')},
        {'script': 'scripts/tests/b.test.sh', 'covers': ('scripts/lib/b.py', 'scripts/tool')},
    ),
}
SETTINGS = {'gate-trace.covers_trace_ignore': ['config/registry/**'], 'gate.test_cache_common_inputs': [],
            'rules.metrics_scanner_files': 1, 'gate-trace.covers_trace_max_listed': 1, 'rules.metrics_trace_timeout_s': 1}


def fake_setting(name, root=None):
    return SETTINGS[name]


class ParseTrace(unittest.TestCase):
    def test_only_successful_opens_and_execs_of_tracked_files_under_the_root_count(self):
        text = opened('scripts/lib/a.py', 'docs/x.md', 'scripts/lib/untracked.py') + \
            f'\n103   execve("{FAKE_ROOT}/scripts/tool", ["scripts/tool"], 0x7ffd /* 9 vars */) = 0' + \
            '\n104   openat(AT_FDCWD, "scripts/lib/b.py", O_RDONLY) = 5'
        self.assertEqual(padrao_metrics.parse_trace(text, FAKE_ROOT, FILES),
                         {'scripts/lib/a.py', 'docs/x.md', 'scripts/tool', 'scripts/lib/b.py'})

    def test_a_module_imported_from_its_cached_bytecode_counts_as_its_source(self):
        text = f'101   openat(AT_FDCWD, "{FAKE_ROOT}/scripts/lib/__pycache__/c.cpython-312.pyc", O_RDONLY|O_CLOEXEC) = 3'
        self.assertEqual(padrao_metrics.parse_trace(text, FAKE_ROOT, FILES), {'scripts/lib/c.py'})

    def test_code_is_source_or_an_extensionless_script_under_the_code_roots_and_never_a_test_file(self):
        self.assertTrue(padrao_metrics.is_code('scripts/lib/a.py'))
        self.assertTrue(padrao_metrics.is_code('scripts/tool'))
        self.assertTrue(padrao_metrics.is_code('infra/service/x.py'))
        self.assertFalse(padrao_metrics.is_code('scripts/tests/test_a.py'))
        self.assertFalse(padrao_metrics.is_code('docs/x.md'))
        self.assertFalse(padrao_metrics.is_code('config/registry/gate.json'))


@mock.patch.object(padrao_metrics, 'setting', fake_setting)
class Selection(unittest.TestCase):
    def measure(self, traces, select=None):
        return padrao_metrics.selection(traces, FAKE_ROOT, MAPPING, FILES, select)

    def test_a_file_the_test_runs_but_its_covers_omits_is_a_silent_skip_when_the_gate_selects_others_for_it(self):
        found = self.measure({'scripts/tests/a.test.sh': opened('scripts/lib/a.py', 'scripts/lib/b.py')},
                             select=lambda path: {'scripts/tests/b.test.sh'})
        test = found['per_test'][0]
        self.assertEqual((test['opened'], test['outside'], test['skipped']), (len(['a', 'b']), 1, ['scripts/lib/b.py']))
        self.assertEqual(found['files_skipping'], {'scripts/lib/b.py': 1})

    def test_a_file_whose_change_still_selects_the_test_is_outside_its_covers_but_not_a_skip(self):
        found = self.measure({'scripts/tests/a.test.sh': opened('scripts/lib/a.py', 'scripts/lib/b.py')},
                             select=lambda path: set(MAPPING['scripts']))
        self.assertEqual((found['outside'], found['skipped'], found['tests_skipped']), (1, 0, 0))

    def test_the_gates_own_selection_decides_and_the_ignored_paths_never_count(self):
        traces = {'scripts/tests/a.test.sh': opened('scripts/lib/a.py', 'scripts/lib/b.py', 'config/registry/gate.json')}
        with mock.patch.object(padrao_metrics.gate_script_tests, 'by_readers', lambda paths, root=None: paths):
            found = self.measure(traces)
        self.assertEqual(found['per_test'][0]['skipped'], ['scripts/lib/b.py'])
        self.assertEqual(found['pairs'], len(['a', 'b']))

    def test_a_test_opening_more_code_than_the_limit_is_a_scanner_counted_apart(self):
        traces = {'scripts/tests/a.test.sh': opened('scripts/lib/a.py', 'scripts/lib/b.py'),
                  'scripts/tests/b.test.sh': opened('scripts/lib/b.py')}
        found = self.measure(traces, select=lambda path: set())
        self.assertEqual((found['scanners'], found['tests_skipped'], found['plain_tests_skipped']), (1, 1, 0))

    def test_a_trace_of_a_test_with_no_covers_manifest_is_left_out(self):
        self.assertEqual(self.measure({'scripts/tests/zzz.test.sh': opened('scripts/lib/a.py')})['tests'], 0)

    def test_the_summary_names_the_share_and_the_file_that_skips_most(self):
        found = self.measure({'scripts/tests/a.test.sh': opened('scripts/lib/a.py', 'scripts/lib/b.py')},
                             select=lambda path: set())
        text = padrao_metrics.summary(found)
        self.assertIn('outside the test\'s covers (50 %)', text)
        self.assertIn('scripts/lib/b.py', text)


@mock.patch.object(padrao_metrics, 'setting', fake_setting)
class Trace(unittest.TestCase):
    def test_a_test_runs_under_strace_with_the_hermetic_harness_and_its_status_is_written(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 1)

        with tempfile.TemporaryDirectory() as out:
            status = padrao_metrics.trace_one('scripts/tests/a.test.sh', out, FAKE_ROOT, run)
            self.assertEqual((Path(out) / 'a.exit').read_text(), '1\n')
        command, kwargs = calls[0]
        self.assertEqual(status, '1')
        self.assertEqual(command[:2], ['strace', '-f'])
        self.assertEqual(command[-1], f'{FAKE_ROOT}/scripts/tests/a.test.sh')
        self.assertTrue(kwargs['env']['PYTHONPATH'].startswith(f'{FAKE_ROOT}/scripts/lib/hermetic'))
        self.assertEqual(kwargs['timeout'], SETTINGS['rules.metrics_trace_timeout_s'])

    def test_a_test_stopped_at_the_limit_is_written_as_cut(self):
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])

        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(padrao_metrics.trace(['scripts/tests/b.test.sh'], out, FAKE_ROOT, 1, run),
                             {'scripts/tests/b.test.sh': 'cut'})
            self.assertEqual((Path(out) / 'b.exit').read_text(), 'cut\n')

    def test_a_trace_refuses_an_argument_that_is_not_a_script_test(self):
        with mock.patch('sys.stderr'), self.assertRaises(SystemExit) as stopped:
            padrao_metrics.main(['trace', 'model', '--out', tempfile.mkdtemp(prefix='metrics-out-')])
        self.assertEqual(stopped.exception.code, len('ab'))

    def test_the_traces_of_a_directory_are_read_back_by_test_script(self):
        with tempfile.TemporaryDirectory() as out:
            (Path(out) / 'a.strace').write_text('x')
            self.assertEqual(padrao_metrics.read_traces(out), {'scripts/tests/a.test.sh': 'x'})


if __name__ == '__main__':
    unittest.main()
