"""The hermetic-tests check (plan v3 H1, D-069 item 5): each refusal, the shrink-only allowlist and the gate maps
wiring. Fixture files in a temporary git repository with a copy of the registry; no network, no clock, no random source.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import hermetic_check  # noqa: E402

REGISTRY = ('config/registry/tests.json', 'config/registry/config.json', 'contracts/config/registry.v1.json')
# OU-DECOUPLE F5 (D-113): the fixture's TypeScript tests live in a generic product, a root of the fixture's registry.


def git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                   capture_output=True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in REGISTRY:
            (self.dir / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.dir / name)
        self.set_sites([])
        self.set_roots(['scripts/tests/', 'products/demo/src/'])  # a product's test root (OU-DECOUPLE F5, D-113)
        git(self.dir, 'init', '-q')

    def set_roots(self, roots):
        path = self.dir / 'config/registry/tests.json'
        data = json.loads(path.read_text())
        data['properties']['tests.check_roots']['default'] = roots
        path.write_text(json.dumps(data))

    def set_sites(self, sites):
        path = self.dir / 'config/registry/tests.json'
        data = json.loads(path.read_text())
        data['properties']['tests.unhermetic_sites']['default'] = sites
        path.write_text(json.dumps(data))

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self):
        git(self.dir, 'add', '-A')
        git(self.dir, 'commit', '-q', '-m', 'x')

    def errors(self, base=None):
        return hermetic_check.check(self.dir, base)


class Refusals(Fixture):
    def test_each_python_offence_is_refused(self):
        cases = {'wall_clock': 'import time\ntime.time()\n', 'wall_clock2': 'from datetime import datetime\ndatetime.now()\n',
                 'random': 'import random\nrandom.random()\n', 'random2': 'import os\nos.urandom(4)\n',
                 'socket': 'import socket\nsocket.socket()\n',
                 'socket2': 'from urllib.request import urlopen\nurlopen("https://example.com/x")\n'}
        for index, (key, text) in enumerate(cases.items()):
            self.write(f'scripts/tests/test_case{index}.py', text)
            self.assertEqual({s.rsplit(':', 1)[1] for s in hermetic_check.sites(self.dir, [f'scripts/tests/test_case{index}.py'])},
                             {key.rstrip('2')})

    def test_each_script_offence_is_refused(self):
        cases = {'wall_clock': 'const t = Date.now();', 'wall_clock2': 'const d = new Date();',
                 'wall_clock3': 'performance.now();', 'random': 'Math.random();', 'random2': 'randomUUID();',
                 'socket': 'await fetch("https://example.com");', 'socket2': 'net.connect(80, "example.com");'}
        for index, (key, text) in enumerate(cases.items()):
            self.write(f'products/demo/src/a/case{index}.test.ts', text)
            self.assertEqual({s.rsplit(':', 1)[1] for s in hermetic_check.sites(self.dir, [f'products/demo/src/a/case{index}.test.ts'])},
                             {key.rstrip('23')})

    def test_hermetic_forms_are_accepted(self):
        self.write('scripts/tests/test_ok.py',
                   'import random, hermetic\nrandom.Random(7)\nrandom.seed(1)\n"""time.time() in a string"""\n'
                   'clock = hermetic.clock()\nurlopen("http://127.0.0.1:1/x")\n'
                   'import socket\nsocket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)\nsocket.socket(family=socket.AF_UNIX)\n')
        self.write('products/demo/src/a/ok.test.ts',
                   '// Date.now() in a comment\nnew Date("2026-01-01");\nawait fetch(`http://127.0.0.1:${port}/x`);\nseeded()();\n')
        self.write('products/demo/src/a/ok.int.test.ts', 'Date.now();')
        self.write('products/demo/src/a/ok.perf.test.ts', 'Date.now();')
        self.write('products/demo/src/a/not_a_test.ts', 'Date.now();')
        self.commit()
        self.assertEqual(self.errors(), ([], []))

    def test_an_offender_in_a_new_file_fails_the_check(self):
        self.write('scripts/tests/test_bad.py', 'import time\ntime.time()\n')
        self.commit()
        errors, _ = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('scripts/tests/test_bad.py', errors[0])
        self.assertIn('wall_clock', errors[0])

    def test_a_file_outside_the_check_roots_is_not_judged(self):
        self.write('tools/test_bad.py', 'import time\ntime.time()\n')
        self.commit()
        self.assertEqual(self.errors(), ([], []))


class Allowlist(Fixture):
    def test_a_listed_site_passes_and_a_fixed_one_is_refused(self):
        self.write('scripts/tests/test_old.py', 'import time\ntime.time()\n')
        self.set_sites(['scripts/tests/test_old.py:wall_clock'])
        self.commit()
        self.assertEqual(self.errors(), ([], []))
        self.set_sites(['scripts/tests/test_old.py:wall_clock', 'scripts/tests/test_gone.py:random'])
        self.commit()
        errors, warnings = self.errors()
        self.assertEqual(warnings, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('lists scripts/tests/test_gone.py:random, which no longer offends', errors[0])

    def test_a_moved_offence_left_listed_under_its_old_file_is_refused_twice(self):
        """F51 moved the setup.sh bootstrap from test_root_identity.py to test_uid0_probe.py and kept the old site:
        the new file is an unlisted site and the old entry is stale; both are errors."""
        self.write('scripts/tests/test_new_home.py', 'import os, hermetic\nhermetic.without_harness(os.environ)\n')
        self.write('scripts/tests/test_old_home.py', 'import os\n')
        self.set_sites(['scripts/tests/test_old_home.py:harness'])
        self.commit()
        errors, warnings = self.errors()
        self.assertEqual(warnings, [])
        self.assertEqual(len(errors), len(['unlisted', 'stale']))
        self.assertTrue(any('test_new_home.py: a unit test breaks the hermetic rule harness' in e for e in errors))
        self.assertTrue(any('lists scripts/tests/test_old_home.py:harness' in e for e in errors))

    def test_the_list_only_shrinks_against_the_base(self):
        self.commit()
        git(self.dir, 'branch', 'base')
        self.write('scripts/tests/test_old.py', 'import time\ntime.time()\n')
        self.set_sites(['scripts/tests/test_old.py:wall_clock'])
        self.commit()
        errors, _ = self.errors('base')
        self.assertEqual(len(errors), 1)
        self.assertIn('only shrinks', errors[0])

    def test_an_unlisted_harness_site_is_refused(self):
        self.write('scripts/tests/test_x.py', 'import os, hermetic\nhermetic.without_harness(os.environ)\n')
        self.commit()
        errors, _ = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('harness', errors[0])
        self.assertIn('tests.unhermetic_sites', errors[0])

    def test_a_listed_harness_site_passes(self):
        self.write('scripts/tests/test_x.py', 'import os, hermetic\nhermetic.without_harness(os.environ)\n')
        self.set_sites(['scripts/tests/test_x.py:harness'])
        self.commit()
        self.assertEqual(self.errors(), ([], []))

    def test_listing_a_site_the_base_already_offended_passes(self):
        self.write('scripts/tests/test_x.py', 'import os, hermetic\nhermetic.without_harness(os.environ)\n')
        self.commit()
        git(self.dir, 'branch', 'base')
        self.set_sites(['scripts/tests/test_x.py:harness'])
        self.commit()
        self.assertEqual(self.errors('base'), ([], []))

    def test_gaining_a_site_the_base_did_not_offend_is_refused(self):
        self.write('scripts/tests/test_x.py', 'import os\n')
        self.commit()
        git(self.dir, 'branch', 'base')
        self.write('scripts/tests/test_x.py', 'import os, hermetic\nhermetic.without_harness(os.environ)\n')
        self.set_sites(['scripts/tests/test_x.py:harness'])
        self.commit()
        errors, _ = self.errors('base')
        self.assertEqual(len(errors), 1)
        self.assertIn('only shrinks', errors[0])

    def test_the_repository_itself_is_clean(self):
        self.assertEqual(hermetic_check.check(ROOT), ([], []))


class Wiring(unittest.TestCase):
    def test_the_check_is_a_gate_maps_module(self):
        # D-322: the gate's "gate maps" stage runs it; the structure check (planning) imports nothing of the gate
        self.assertIn('hermetic_check.check', (ROOT / 'scripts/lib/gate_maps.py').read_text())

    def test_the_registry_entries_are_registered(self):
        for name in ('tests.random_seed', 'tests.script_timeout_ms', 'tests.network_allowed', 'tests.clock_start'):
            config.get(name)
        self.assertEqual(config.check(ROOT), [])


class Selection(unittest.TestCase):
    def test_a_judged_test_file_selects_this_test(self):
        # HERMETIC-COVERS: #685 changed scripts/tests/test_infra_runner.py with a time.monotonic() and its gate never ran
        # hermetic.test.sh, whose repository check judges that file: the full runs of #686, #687 and #688 found it red. A
        # change of any file the check judges (tests.check_roots, PY_NAMES, JS_NAMES) selects this test
        import gate_script_tests
        for path in ('scripts/tests/test_infra_runner.py', 'scripts/tests/infra_db/test_psql.py', 'scripts/tests/sub/a_test.py',
                     'scripts/tests/web/x.test.ts', 'scripts/tests/web/y.test.mjs'):
            self.assertTrue(hermetic_check.judged(path, config.get('tests.check_roots', ROOT)), path)
            tests, _reason = gate_script_tests.select([path])
            self.assertIn('scripts/tests/hermetic.test.sh', tests, path)


if __name__ == '__main__':
    unittest.main()
