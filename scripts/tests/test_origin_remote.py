"""The session's origin is Origin (engine-cloud; Daniel 04/11 16:57 BRT).

scripts/lib/origin_remote.py, on a throwaway checkout: an origin on another forge is pointed at Origin's remote, and
one already on Origin, on a local path (the gate's fixtures and pinned worktrees) or absent is left alone; with the
origin CLI, git signs in to the Origin host through it, once; with none it says so and sets nothing; what it points at
is what the Origin adapter accepts; and scripts/cloud/setup.sh runs it after its own fetch, never failing on it. No
network.
"""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import origin_remote  # noqa: E402
import forge_origin  # noqa: E402

ELSEWHERE = '://'.join(('https', 'forge.example.invalid/openuniversity-si/open-university.git'))
CLI = 'an origin cli/origin'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False).stdout.strip()


def helpers(root, key):
    """The helpers git keeps for a key, in order, the empty one that resets them included."""
    return subprocess.run(['git', '-C', str(root), 'config', '--local', '--get-all', key], capture_output=True,
                          text=True, check=False).stdout.splitlines()


class Pointing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        git(self.root, 'init', '--quiet')
        self.key = f"credential.{'://'.join(('https', origin_remote.config.get('origin-client.git_hosts')[0]))}.helper"

    def test_an_origin_on_another_forge_is_pointed_at_origin_and_one_already_there_is_left_alone(self):
        git(self.root, 'remote', 'add', 'origin', ELSEWHERE)
        said = origin_remote.point(self.root, cli=CLI)
        self.assertEqual(git(self.root, 'remote', 'get-url', 'origin'), origin_remote.remote_url())
        self.assertIn(f'origin: {ELSEWHERE} -> {origin_remote.remote_url()}', said)
        self.assertEqual(origin_remote.point(self.root, cli=CLI), [])

    def test_an_origin_on_a_local_path_or_none_is_left_alone(self):
        self.assertEqual(origin_remote.point(self.root, cli=CLI)[:-1], [])
        self.assertEqual(git(self.root, 'remote'), '')
        local = str(self.root / 'the-forge-of-a-fixture.git')
        git(self.root, 'remote', 'add', 'origin', local)
        origin_remote.point(self.root, cli=CLI)
        self.assertEqual(git(self.root, 'remote', 'get-url', 'origin'), local)
        self.assertEqual([origin_remote.host_of(url) for url in (local, 'git@forge.example.invalid:o/n.git')],
                         ['', 'forge.example.invalid'])

    def test_with_the_cli_git_signs_in_through_it_once(self):
        origin_remote.point(self.root, cli=CLI)
        kept = helpers(self.root, self.key)
        self.assertEqual(kept, ['', origin_remote.helper(CLI)])
        self.assertIn("'an origin cli/origin' auth token", kept[-1])
        self.assertEqual(origin_remote.point(self.root, cli=CLI), [])

    def test_with_no_cli_it_says_so_and_sets_nothing(self):
        with mock.patch.object(origin_remote, 'cli_found', lambda: None):
            said = origin_remote.point(self.root)
        self.assertIn('no origin CLI', said[-1])
        self.assertEqual(helpers(self.root, self.key), [])

    def test_what_it_points_at_is_what_the_origin_adapter_accepts(self):
        forge_origin.refuse_remote(origin_remote.remote_url(), origin_remote.config.get('forge-events.repo'))

    def test_the_setup_runs_it_after_its_own_fetch_and_never_fails_on_it(self):
        setup = (ROOT / 'scripts' / 'cloud' / 'setup.sh').read_text(encoding='utf-8')
        call = '"$OU_PYTHON" "$ROOT/scripts/lib/origin_remote.py" "$ROOT" >>"$LOG" 2>&1 || true'
        self.assertIn(call, setup)
        self.assertLess(setup.index('fetch --unshallow origin'), setup.index(call))
        with contextlib.redirect_stderr(io.StringIO()) as said:
            self.assertEqual(origin_remote.main(['a checkout that is not there']), 0)
        self.assertIn('origin: not pointed at Origin', said.getvalue())


if __name__ == '__main__':
    unittest.main()
