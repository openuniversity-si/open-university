"""Repository hygiene (OU-DECOUPLE F2, D-105): the two repo-wide rules ported from Open University's vitest suite."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import repo_hygiene  # noqa: E402

DOMAIN = 'thetower' + '.si'  # assembled at run time, so this file holds no legacy address itself
NO_PCRE = 1 + 1  # any exit but 0 (a match) and 1 (none) is git refusing -P; built from 1, no new literal


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)

    def errors(self):
        return repo_hygiene.check(self.root)

    def registry(self, **values):
        """Patch the named registry entries (dots spelled `__`) for this test: the checkout's own allowlist and
        exemptions are empty since Open University left (OU-DECOUPLE F4 (D-111)), so the test supplies its own."""
        real = config.get
        values = {name.replace('__', '.'): value for name, value in values.items()}
        patcher = mock.patch.object(repo_hygiene.config, 'get',
                                    side_effect=lambda name, root=None: values[name] if name in values else real(name, root))
        patcher.start()
        self.addCleanup(patcher.stop)


class LegacyAddress(Repo):
    def test_the_pattern_finds_legacy_addresses_and_nothing_else(self):
        pattern = config.get('structure.legacy_email_pattern')
        found = sorted(match for _, match in repo_hygiene.addresses(self.root, pattern, []))
        self.assertEqual(found, [])
        self.write('docs/a.md', f'write to contact@{DOMAIN} or a@mail.{DOMAIN}\n')
        self.write('docs/b.md', f'contact@example.org and https://{DOMAIN}\n')
        self.assertEqual(self.errors(), [
            f'docs/a.md: holds a@mail.{DOMAIN}, an address on the legacy domain (structure.legacy_email_pattern)',
            f'docs/a.md: holds contact@{DOMAIN}, an address on the legacy domain (structure.legacy_email_pattern)'])

    def test_an_exempt_path_and_a_binary_file_are_not_scanned(self):
        self.registry(structure__legacy_email_exempt=['products/demo/src/no-legacy-email.test.ts'])
        self.write('products/demo/src/no-legacy-email.test.ts', f'"a@{DOMAIN}"\n')
        self.write('docs/blob.bin', b'\x00\xff' + f'a@{DOMAIN}'.encode())
        self.assertEqual(self.errors(), [])

    def test_a_git_without_pcre_gets_the_same_answer_from_python(self):
        self.write('scripts/x.py', f'ADDRESS = "Contact@{DOMAIN.upper()}"\n')
        pattern = config.get('structure.legacy_email_pattern')
        fast = repo_hygiene.addresses(self.root, pattern, ['scripts/x.py'])
        failed = subprocess.CompletedProcess([], NO_PCRE, b'', b'fatal: cannot use Perl-compatible regexes')
        with mock.patch.object(repo_hygiene.subprocess, 'run', return_value=failed):
            slow = repo_hygiene.addresses(self.root, pattern, ['scripts/x.py'])
        self.assertEqual(fast, slow)
        self.assertEqual(slow, {('scripts/x.py', f'Contact@{DOMAIN.upper()}')})


class GitMessageArgv(Repo):
    VERBS, FLAGS = config.get('structure.git_write_verbs'), ('-m', '--message')

    def found(self, source):
        return repo_hygiene.argv_message_errors('scripts/lib/x.py', source, self.VERBS, self.FLAGS)

    def test_a_variable_message_on_a_git_write_is_refused_in_a_call_and_in_a_list(self):
        self.assertEqual(len(self.found("def f(git, text):\n    git('commit-tree', tree, '-p', parent, '-m', text)\n")), 1)
        self.assertEqual(len(self.found("def f(text):\n    run(['git', 'commit', '--message', text.strip()])\n")), 1)

    def test_a_literal_an_f_string_stdin_and_a_command_that_stores_nothing_pass(self):
        self.assertEqual(self.found("git('commit-tree', tree, '-m', 'merge')\ngit('tag', '-m', f'claim {number}')\n"), [])
        self.assertEqual(self.found("git('commit-tree', tree, stdin=text)\n"), [])
        self.assertEqual(self.found("run(['python3', '-m', module])\ngit('log', '-m', name)\n"), [])

    def test_a_listed_path_is_not_scanned_and_an_unlisted_one_is_refused_through_check(self):
        self.write('scripts/lib/a.py', "def f(git, text):\n    git('commit', '-m', text)\n")
        self.write('scripts/lib/b.py', "def f(git, text):\n    git('commit', '-m', text)\n")
        self.registry(structure__git_message_argv_allowed=['scripts/lib/b.py'])
        errors = [line for line in self.errors() if 'command-line argument' in line]
        self.assertEqual([line.split(':')[0] for line in errors], ['scripts/lib/a.py'])

    def test_a_record_is_committed_through_stdin_whatever_its_size(self):
        import forge_git_ref
        refs = forge_git_ref.GitRefs(self.root, remote='origin')
        subprocess.run(['git', '-C', str(self.root), 'init', '-q', '--bare', str(self.root / 'o.git')], check=True)
        subprocess.run(['git', '-C', str(self.root), 'remote', 'add', 'origin', str(self.root / 'o.git')], check=True)
        record = {'body': 'x' * os.sysconf('SC_ARG_MAX')}
        self.assertTrue(refs.advance('big', record, None))
        self.assertEqual(refs.read('big')[1], record)


class ConflictMarkers(Repo):
    OPEN, MIDDLE, CLOSE = '<<<<<<<', '=======', '>>>>>>>'  # quoted, never at the start of a line of this file

    def test_a_committed_conflict_block_is_refused_in_docs_and_scripts(self):
        self.write('docs/domain/D.md', f'| D-1 |\n{self.OPEN} HEAD\n| D-2 |\n{self.MIDDLE}\n| D-3 |\n{self.CLOSE} origin/base\n')
        self.write('scripts/x.sh', f'{self.OPEN}\n')
        errors = self.errors()
        self.assertTrue(all('merge conflict marker' in line for line in errors))
        self.assertEqual(sorted(line.split(':')[0] for line in errors), ['docs/domain/D.md', 'docs/domain/D.md', 'scripts/x.sh'])

    def test_a_heading_underline_an_indented_mark_and_a_path_outside_the_roots_are_not_conflicts(self):
        self.write('docs/h.md', f'Title\n{self.MIDDLE}\n  {self.OPEN} quoted\n')
        self.write('config/x.txt', f'{self.OPEN} HEAD\n')
        self.assertEqual(self.errors(), [])


class RasterImages(Repo):
    def test_a_raster_image_outside_the_allowlist_is_refused_and_an_allowed_one_is_not(self):
        self.registry(structure__raster_allowed=['^products/demo/public/icons/', '^products/demo/public/brand/logo\\.png$'])
        self.write('products/demo/public/icons/favicon.ico', b'\x00')
        self.write('products/demo/public/brand/logo.png', b'\x00')
        self.write('docs/photo.JPG', b'\x00')
        self.write('scripts/diagram.svg', '<svg/>\n')
        self.assertEqual(self.errors(), [
            'docs/photo.JPG: a tracked raster image; images live in object storage, never in git (structure.raster_allowed)'])

    def test_this_checkout_is_clean(self):
        self.assertEqual(repo_hygiene.check(ROOT), [])


class TowerStore(Repo):
    """D-335: a forced add of the change store (`git add -f .tower/config`) is refused, whatever file it holds."""
    def test_a_tracked_file_of_the_change_store_is_refused_and_a_lookalike_path_is_not(self):
        store = config.get('config.store_dir')
        self.write(f'{store}/events.jsonl', '{}\n')
        self.write(f'docs/{store}/note.md', 'a path that only ends like the store\n')
        self.assertEqual(len(repo_hygiene.tower_store_errors(repo_hygiene.tracked(self.root), store)), 1)
        self.assertTrue(any(error.startswith(f'{store}/events.jsonl: a tracked file of the change store')
                            for error in self.errors()))

    def test_a_tracked_link_of_the_store_name_is_refused(self):
        """A symlink named like the store's top directory, to a tracked directory that holds a store, is listed by git
        as the link's own path, not under it; the refusal names it too (the confirming review of 19/11)."""
        top = Path(config.get('config.store_dir')).parts[0]
        self.assertEqual(len(repo_hygiene.tower_store_errors([top, f'docs/{top}', 'elsewhere/config'], top)), 1)
        self.assertEqual(len(repo_hygiene.tower_store_errors([f'{top}x', f'{top}.md'], top)), 0)


if __name__ == '__main__':
    unittest.main()
