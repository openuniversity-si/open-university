"""PS1: production entrypoints refused in cloud sessions and PR diffs (D-054, D-069 item 13).

Hermetic: a temporary git repository with the real registry, a fake PATH and copies of the entrypoints; no production
script is ever run, no network. Tests read the registry, never a copied value.

OU-DECOUPLE F4 (D-111): the engine has no production entrypoint left, so the repository's forbidden list is empty and
every case runs against a fixture registry naming fixture entrypoints (products/demo stand-ins) with their own
guarded scripts; the guard itself is unchanged.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import hermetic  # noqa: E402
import production_guard  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

ENTRYPOINTS = ['demo-deploy', 'demo-migrate', 'demo-verify', 'demo-check']
ALLOWED = ['scripts/demo-deploy', 'scripts/demo-migrate', 'scripts/demo-verify', 'scripts/demo-check',
           'scripts/lib/demo_deploy.py']
MARKERS = config.get('production.cloud_session_markers', ROOT)
MARKER = MARKERS[0]
REFUSED = config.get('production.refusal_exit_code', ROOT)


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                   capture_output=True)


def entrypoint(name):
    """A fixture production entrypoint: the guard first, as every real one did, then work the refusal never reaches."""
    return ('#!/usr/bin/env bash\n# Fixture production entrypoint.\nset -euo pipefail\n'
            f'"${{OU_PYTHON:-python3}}" "$(dirname "$0")/lib/production_guard.py" refuse {name}\n'
            'echo reached-production\n')


def fixture_registry(root):
    """The real registry with the fixture entrypoints forbidden and their own paths allowed."""
    fixture_copy.registry(root)
    path = root / 'config' / 'registry' / 'production.json'
    data = json.loads(path.read_text())
    data['properties']['production.forbidden_entrypoints']['default'] = ENTRYPOINTS
    allowed = data['properties']['production.invocation_allowed_paths']
    allowed['default'] = ALLOWED + allowed['default']
    path.write_text(json.dumps(data))


class Repo:
    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp())
        fixture_registry(self.dir)
        (self.dir / 'scripts').mkdir()
        (self.dir / 'scripts' / 'keep').write_text('x\n')
        git(self.dir, 'init', '-q')
        git(self.dir, 'add', '.')
        git(self.dir, 'commit', '-qm', 'base')
        return self

    def __exit__(self, *_):
        shutil.rmtree(self.dir)

    def add(self, path, text):
        target = self.dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.dir, 'add', '.')

    def errors(self):
        return production_guard.check(self.dir, 'HEAD')[0]


class CloudRefusal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fixture_registry(self.root)
        (self.root / 'scripts').mkdir()
        for name in ENTRYPOINTS:
            (self.root / 'scripts' / name).write_text(entrypoint(name))

    def test_the_repository_names_only_entrypoints_that_exist(self):
        for name in config.get('production.forbidden_entrypoints', ROOT):
            self.assertTrue((ROOT / 'scripts' / name).is_file(), name)

    def test_marker_set_refuses_every_entrypoint(self):
        for name in ENTRYPOINTS:
            message, code = production_guard.refusal(name, {MARKER: '1'}, self.root)
            self.assertIn(f'scripts/{name}', message)
            self.assertEqual(code, REFUSED)

    def test_host_shell_is_allowed(self):
        for name in ENTRYPOINTS:
            self.assertIsNone(production_guard.refusal(name, {}, self.root))
            self.assertIsNone(production_guard.refusal(name, {MARKER: ''}, self.root))

    def test_cli_exit_codes(self):
        guard = str(ROOT / 'scripts' / 'lib' / 'production_guard.py')
        clean = {k: v for k, v in os.environ.items() if k not in MARKERS}
        cloud = dict(clean, **{MARKER: '1'})
        self.assertEqual(subprocess.run([sys.executable, guard, 'refuse', 'demo-deploy'], env=cloud,
                                        capture_output=True).returncode, REFUSED)
        self.assertEqual(subprocess.run([sys.executable, guard, 'refuse', 'demo-deploy'], env=clean,
                                        capture_output=True).returncode, 0)

    def test_every_entrypoint_calls_the_guard_before_anything_else(self):
        for name in config.get('production.forbidden_entrypoints', self.root):
            source = (self.root / 'scripts' / name).read_text()
            self.assertIn('production_guard', source, name)
            if source.startswith('#!/usr/bin/env bash'):
                body = source.split('set -euo pipefail\n', 1)[1].lstrip()
                skipped = [line for line in body.splitlines() if not line.startswith('#')]
                self.assertIn(f'production_guard.py" refuse {name}', skipped[0], name)

    def test_entrypoint_copy_refuses_with_fake_path(self):
        """A copy of each bash entrypoint beside the real guard, with a fake PATH: exit status and message."""
        for name in config.get('production.forbidden_entrypoints', self.root):
            source = self.root / 'scripts' / name
            if not source.read_text().startswith('#!/usr/bin/env bash'):
                continue
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                (tmp / 'scripts').mkdir()
                (tmp / 'scripts' / 'lib').symlink_to(ROOT / 'scripts' / 'lib')
                copy = tmp / 'scripts' / name
                shutil.copy(source, copy)
                bin_dir = tmp / 'bin'
                bin_dir.mkdir()
                for tool in ('bash', 'dirname'):
                    (bin_dir / tool).symlink_to(shutil.which(tool))
                env = {'PATH': str(bin_dir), 'OU_PYTHON': sys.executable, MARKER: '1', 'HOME': str(tmp),
                       **hermetic.store_env()}
                run = subprocess.run([str(bin_dir / 'bash'), str(copy), '1'], env=env, capture_output=True, text=True)
                self.assertEqual(run.returncode, REFUSED, (name, run.stderr))
                self.assertIn('refused inside a cloud session', run.stderr)
                self.assertNotIn('reached-production', run.stdout)


class DiffRefusal(unittest.TestCase):
    def test_added_invocation_in_a_new_script_is_refused(self):
        for name in ENTRYPOINTS:
            with Repo() as repo:
                repo.add('scripts/new-tool', f'#!/usr/bin/env bash\nscripts/{name} 1\n')
                errors = repo.errors()
                self.assertEqual(len(errors), 1, (name, errors))
                self.assertIn(f'scripts/{name}', errors[0])

    def test_bare_command_word_and_quoted_name_and_module_are_refused(self):
        for text in ('demo-deploy 1', 'set -e; demo-migrate up 1', 'cmd = ["x", "demo-verify"]',
                     'python3 scripts/lib/demo_check.py 3'):
            with Repo() as repo:
                repo.add('scripts/lib/other.py', text + '\n')
                self.assertEqual(len(repo.errors()), 1, text)

    def test_allowed_cases(self):
        with Repo() as repo:
            repo.add('scripts/lib/demo_deploy.py', 'x = "scripts/demo-verify"\n')     # registry allowed path
            repo.add('scripts/tests/t.sh', 'scripts/demo-migrate up 1\n')              # hermetic test
            repo.add('scripts/other', '# scripts/demo-deploy is host-side only\n')     # comment
            repo.add('scripts/fine', 'echo "demo-deployer and demo-checks"\n')         # unrelated words
            repo.add('docs/process/x.md', 'run scripts/demo-deploy\n')                 # not a scanned root
            repo.add('scripts/data.txt', 'scripts/demo-deploy\n')                      # not a scanned suffix
            self.assertEqual(repo.errors(), [])

    def test_no_base_or_registry_is_a_noop(self):
        with Repo() as repo:
            self.assertEqual(production_guard.check(repo.dir, None), ([], []))
            shutil.rmtree(repo.dir / 'config')
            self.assertEqual(production_guard.check(repo.dir, 'HEAD'), ([], []))


if __name__ == '__main__':
    unittest.main()
