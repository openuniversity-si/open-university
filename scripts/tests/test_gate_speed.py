"""Cache keys, the incremental secret scan, and the portable media copy."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import gate_speed


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)


class CacheKeyTests(unittest.TestCase):
    def _web(self, root, eslint='1.0.0', config='rule-a'):
        web = root / 'apps' / 'web'
        web.mkdir(parents=True, exist_ok=True)
        (web / 'package.json').write_text(json.dumps({
            'devDependencies': {'eslint': eslint, 'stylelint': '1', 'typescript': '6'},
        }))
        (web / 'eslint.config.mjs').write_text(config)
        (web / 'stylelint.config.mjs').write_text('style')
        (web / 'tsconfig.json').write_text('{"compilerOptions":{}}')
        return web

    def test_lint_key_tracks_eslint_version_config_and_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self._web(root)
            cache = root / 'cache'
            first = gate_speed.lint_dir(web, cache, node_version='v22.0.0')
            again = gate_speed.lint_dir(web, cache, node_version='v22.0.0')
            self.assertEqual(first, again)
            self.assertTrue(first.is_dir())
            bumped = gate_speed.lint_dir(self._web(root, eslint='2.0.0'), cache, node_version='v22.0.0')
            # _web writes into the same tree; rebuild a second tree for the config change.
            other = Path(directory) / 'other'
            changed = gate_speed.lint_dir(self._web(other, config='rule-b'), other / 'cache', node_version='v22.0.0')
            node = gate_speed.lint_dir(web, cache, node_version='v24.0.0')
            self.assertNotEqual(first.parent.name, bumped.parent.name)
            self.assertNotEqual(first.parent.name, changed.parent.name)
            self.assertNotEqual(first.parent.name, node.parent.name)

    def test_d064f_lint_cache_is_one_file_set_per_checkout_path(self):
        # eslint/stylelint caches key entries by absolute path; one shared file was rewritten by every checkout.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            slot1 = gate_speed.lint_dir(self._web(root / 'slot1'), cache, node_version='v22')
            slot2 = gate_speed.lint_dir(self._web(root / 'slot2'), cache, node_version='v22')
            self.assertEqual(slot1.parent, slot2.parent)
            self.assertNotEqual(slot1, slot2)
            self.assertEqual(slot1, gate_speed.lint_dir(self._web(root / 'slot1'), cache, node_version='v22'))

    def test_typecheck_key_includes_the_checkout_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self._web(root)
            cache = root / 'cache'
            first = gate_speed.typecheck_info(web, cache, node_version='v22')
            sibling = Path(directory) / 'checkout-b'
            other = gate_speed.typecheck_info(self._web(sibling), cache, node_version='v22')
            self.assertNotEqual(first.name, other.name)
            self.assertEqual(first, gate_speed.typecheck_info(web, cache, node_version='v22'))


class SecretScanTests(unittest.TestCase):
    def _repo(self, root):
        _git(root, 'init', '-q', '-b', 'main')
        _git(root, 'config', 'user.email', 'test@example.test')
        _git(root, 'config', 'user.name', 'test')
        _git(root, 'config', 'commit.gpgsign', 'false')  # no dependency on the session's signing service
        (root / '.gitleaks.toml').write_text('title = "one"\n')
        (root / 'README').write_text('a\n')
        _git(root, 'add', '-A')
        _git(root, 'commit', '-qm', 'one')
        return _git_head(root)

    def test_plan_is_full_then_incremental_then_skip_and_full_again_when_the_tool_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            base = self._repo(root)
            self.assertEqual(gate_speed.secret_plan(root, cache), 'HEAD')
            gate_speed.secret_record(root, cache)
            self.assertEqual(gate_speed.secret_plan(root, cache), 'skip')
            (root / 'README').write_text('b\n')
            _git(root, 'add', '-A')
            _git(root, 'commit', '-qm', 'two')
            head = _git_head(root)
            self.assertEqual(gate_speed.secret_plan(root, cache), f'{base}..{head}')
            (root / '.gitleaks.toml').write_text('title = "two"\n')
            self.assertEqual(gate_speed.secret_plan(root, cache), 'HEAD')

    def _branch(self, root):
        """main at the fork, then a PR branch with one changed file, one untracked file and a deleted file."""
        fork = self._repo(root)
        _git(root, 'checkout', '-qb', 'pr')
        (root / 'feature.py').write_text('x = 1\n')
        _git(root, 'add', '-A')
        _git(root, 'commit', '-qm', 'pr')
        (root / 'untracked.txt').write_text('u\n')
        return fork, _git_head(root)

    def test_change_scope_scans_the_prs_commits_and_full_scope_all_of_head(self):
        """GATE-SPEED R1 (D-092): with the PR's base and scope `change`, merge-base..HEAD; `full` or no base: HEAD."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fork, head = self._branch(root)
            cache = root / 'cache'
            self.assertEqual(gate_speed.secret_plan(root, cache, 'main', 'change'), f'{fork}..{head}')
            self.assertEqual(gate_speed.secret_plan(root, cache, 'main', 'full'), 'HEAD')
            self.assertEqual(gate_speed.secret_plan(root, cache, '', 'change'), 'HEAD')

    def test_a_gitleaks_config_change_scans_everything(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._branch(root)
            (root / '.gitleaks.toml').write_text('title = "loosened"\n')
            _git(root, 'commit', '-qam', 'config')
            self.assertEqual(gate_speed.secret_plan(root, root / 'cache', 'main', 'change'), 'HEAD')
            self.assertIsNone(gate_speed.changed_files(root, 'main', 'change'))

    def test_the_change_tree_is_the_prs_files_and_the_untracked_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._branch(root)
            self.assertEqual(gate_speed.changed_files(root, 'main', 'change'), ['feature.py', 'untracked.txt'])
            self.assertIsNone(gate_speed.changed_files(root, 'main', 'full'))
            listing = root / 'listing'
            self.assertEqual(gate_speed.main(['gate_speed.py', 'secret-files', str(root), 'main', 'change', str(listing)]), 0)
            self.assertEqual(listing.read_text().split('\0'), ['feature.py', 'untracked.txt', ''])


def _git_head(root):
    completed = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


class CopyTests(unittest.TestCase):
    def test_copy_if_absent_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'src'
            dest = root / 'dest'
            (source / 'keep').mkdir(parents=True)
            (source / 'keep' / 'new.txt').write_text('new')
            (source / 'keep' / 'old.txt').write_text('incoming')
            (dest / 'keep').mkdir(parents=True)
            (dest / 'keep' / 'old.txt').write_text('already')
            copied = gate_speed.copy_if_absent(source, dest)
            self.assertEqual(copied, 1)
            self.assertEqual((dest / 'keep' / 'old.txt').read_text(), 'already')
            self.assertEqual((dest / 'keep' / 'new.txt').read_text(), 'new')
            self.assertEqual(gate_speed.copy_if_absent(source, dest), 0)


class RegistryTimeoutTests(unittest.TestCase):
    """D-068 / D-069 item 3: the probe and git timeouts are registry values (seconds), read by name, never literals."""

    def _timeout_passed(self, call, registry_name, value):
        completed = subprocess.CompletedProcess([], 0, 'v22.0.0\n', '')
        with mock.patch.object(gate_speed.subprocess, 'run', return_value=completed) as run, \
                mock.patch.object(gate_speed.config, 'get', side_effect=lambda name, root=None: value
                                  if name == registry_name else 0) as get:
            call()
        self.assertIn(mock.call(registry_name), get.call_args_list)
        return run.call_args.kwargs['timeout']

    def test_node_probe_reads_the_tool_probe_timeout(self):
        self.assertEqual(self._timeout_passed(gate_speed._node_version, 'gate.tool_probe_timeout_s', 7), 7)

    def test_gitleaks_probe_reads_the_tool_probe_timeout(self):
        self.assertEqual(self._timeout_passed(gate_speed._gitleaks_version, 'gate.tool_probe_timeout_s', 7), 7)

    def test_git_reads_the_git_timeout(self):
        self.assertEqual(self._timeout_passed(lambda: gate_speed._git(ROOT, ['status']), 'gate.git_timeout_s', 9), 9)

    def test_the_registry_holds_the_values_the_gate_has_always_used(self):
        self.assertEqual(gate_speed.config.get('gate.tool_probe_timeout_s'), 10)
        self.assertEqual(gate_speed.config.get('gate.git_timeout_s'), 30)


if __name__ == '__main__':
    unittest.main()
