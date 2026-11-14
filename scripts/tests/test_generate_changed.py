"""The regeneration after an edit (D-222 (5)): `scripts/generate --changed` regenerates the committed targets whose source globs
name a changed path, and nothing else. A contract feeds the python types, a registry file feeds its owner's
aggregate, a unit manifest feeds no committed target (CODEOWNERS left with D-295); a path no target names writes nothing; an on-demand target (docs, status,
census) is never written by a commit. The CLI prints what it wrote; it reads the paths from stdin only under --stdin (the
pre-commit stage), else from the checkout's own diff, so typed by hand it never waits on stdin (03/11: a lane's
`scripts/generate --changed` hung for more than 10 minutes). No network."""
from datetime import timedelta
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402

BOUND_S = timedelta(minutes=1).total_seconds()  # the hang this file guards against lasted more than 10 minutes


class Affected(unittest.TestCase):
    def test_a_contract_feeds_the_python_types(self):
        names = generate.affected(['contracts/events/pr.opened.v1.json'], ROOT)
        self.assertIn('python-types', names)

    def test_a_registry_file_feeds_its_owners_aggregate(self):
        self.assertIn('registry', generate.affected(['config/registry/gate/x.json'], ROOT))

    def test_a_unit_manifest_feeds_no_committed_target_and_not_the_on_demand_status(self):
        names = generate.affected(['units/engine-generate/unit.json'], ROOT)
        self.assertNotIn('codeowners', names)
        self.assertNotIn('status', names)

    def test_an_on_demand_target_is_never_selected(self):
        names = generate.affected(['contracts/events/pr.opened.v1.json', 'units/x/census.jsonl'], ROOT)
        self.assertNotIn('docs', names)
        self.assertNotIn('census', names)

    def test_a_path_no_target_names_selects_nothing(self):
        self.assertEqual(generate.affected(['README.md', 'scripts/tests/generate.test.sh'], ROOT), [])


class Changed(unittest.TestCase):
    def run_changed(self, stdin, out):
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'lib' / 'generate.py'), '--changed', '--stdin', '--out', str(out)],
            input=stdin, capture_output=True, text=True, check=True,
        )

    def test_a_contract_change_writes_its_derived_files_under_out(self):
        with tempfile.TemporaryDirectory() as out:
            result = self.run_changed('contracts/events/pr.opened.v1.json\n', out)
            written = result.stdout.splitlines()
            self.assertTrue(written, 'the contract must regenerate at least one derived file')
            self.assertTrue(all(line.startswith('scripts/lib/generated/') for line in written), written)
            for line in written:
                self.assertTrue((Path(out) / line).is_file(), line)

    def test_an_unrelated_change_writes_nothing(self):
        with tempfile.TemporaryDirectory() as out:
            result = self.run_changed('README.md\n', out)
            self.assertEqual(result.stdout, '')
            self.assertEqual(list(Path(out).iterdir()), [])


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout


class FromTheDiff(unittest.TestCase):
    """Without --stdin, --changed reads the checkout's diff and never stdin (03/11, the 10-minute hang)."""

    def cli(self, *args):
        return [sys.executable, str(ROOT / 'scripts' / 'lib' / 'generate.py'), '--changed', *args]

    def test_an_open_stdin_that_never_ends_does_not_hold_it(self):
        read, write = os.pipe()  # the write end stays open: stdin never reaches EOF, as in a lane's shell
        try:
            with tempfile.TemporaryDirectory() as out, tempfile.TemporaryFile() as err:
                process = subprocess.Popen(self.cli('--out', out), stdin=read,  # no --base: what a lane types
                                           stdout=subprocess.DEVNULL, stderr=err)
                os.close(read)
                try:
                    code = process.wait(timeout=BOUND_S)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    self.fail('scripts/generate --changed waited on an open stdin instead of reading the diff')
                err.seek(0)
                stderr = err.read().decode()
                # the default base may be absent in a bare checkout: then a clear error, never a wait
                self.assertTrue(code == 0 or 'cannot diff against' in stderr, (code, stderr))
        finally:
            os.close(write)

    def test_the_paths_are_the_committed_diff_plus_what_is_not_committed(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q', '-b', 'base')
            git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'base')
            git(repo, 'checkout', '-q', '-b', 'work')
            (Path(repo) / 'committed.json').write_text('{}')
            (Path(repo) / 'staged.json').write_text('{}')
            git(repo, 'add', 'committed.json')
            git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'work')
            git(repo, 'add', 'staged.json')
            (Path(repo) / 'untracked.json').write_text('{}')
            self.assertEqual(generate.changed_paths(repo, 'base'), ['committed.json', 'staged.json', 'untracked.json'])

    def test_an_absent_base_is_a_clear_error_at_once(self):
        result = subprocess.run(self.cli('--base', 'refs/heads/no-such-base-ref'), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=BOUND_S)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot diff against refs/heads/no-such-base-ref', result.stderr)

    def test_stdin_and_base_need_changed(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'generate.py'), '--stdin'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=BOUND_S)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('go with --changed', result.stderr)


if __name__ == '__main__':
    unittest.main()
