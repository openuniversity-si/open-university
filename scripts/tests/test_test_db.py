"""The shared throwaway test-database helper (TI1). Local toolchain PostgreSQL only (TEST_DATABASE_URL), no network;
every tunable comes from the registry (config.get).
"""
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import test_db  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


class NameTests(unittest.TestCase):
    def test_new_names_are_unique_and_valid(self):
        names = {test_db.new_name() for _ in range(16)}
        self.assertEqual(len(names), 16)
        for name in names:
            self.assertEqual(test_db.validate(name), name)
            self.assertTrue(name.startswith(config.get('test-db.name_prefix')))
            self.assertLessEqual(len(name), 63)

    def test_names_never_collide_with_gate_isolation_or_integration_databases(self):
        for _ in range(16):
            name = test_db.new_name()
            self.assertIsNone(re.fullmatch(r'tower_test_[0-9a-f]{10}', name))
            self.assertFalse(name.startswith('tower_test_g'))
            self.assertNotEqual(name, 'tower_test_f02')

    def test_foreign_or_malformed_names_are_refused(self):
        prefix = config.get('test-db.name_prefix')
        for name in ('tower_test_0123456789', 'tower_test_gabc', 'tower_test_f02', 'postgres', '', None,
                     prefix, prefix + 'XYZ', prefix + '0' * 4 + '"; drop database postgres; --',
                     prefix + '0' * (2 * config.get('test-db.name_token_bytes') + 2)):
            with self.subTest(name=name), self.assertRaises(test_db.TestDatabaseError):
                test_db.validate(name)

    def test_destroy_refuses_a_foreign_name_before_any_sql(self):
        with self.assertRaises(test_db.TestDatabaseError):
            test_db.destroy('postgresql://postgres@127.0.0.1:1/x', 'tower_test_0123456789')

    def test_remote_urls_are_refused(self):
        for url in ('postgresql://u@db.example.test/x', 'mysql://u@127.0.0.1/x'):
            with self.subTest(url=url), self.assertRaises(test_db.TestDatabaseError):
                test_db.maintenance_url(url)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not URL:
            raise RuntimeError('TEST_DATABASE_URL is required (source scripts/cloud/env.sh); no database mocks')

    def _url(self, name):
        return URL.rsplit('/', 1)[0] + '/' + name

    def _backends(self, name):
        return test_db._psql(URL, f"select pid from pg_stat_activity where datname = '{name}'").split()

    def test_create_then_destroy_with_a_lingering_backend(self):
        name = test_db.create(URL)
        self.addCleanup(test_db.destroy, URL, name)
        self.assertTrue(test_db.exists(URL, name))
        psql = test_db.psql_binary()
        lingering = subprocess.Popen([str(psql), self._url(name), '-qtA'], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lingering.stderr.close)
        self.addCleanup(lingering.stdout.close)
        self.addCleanup(lingering.kill)
        lingering.stdin.write('select pg_backend_pid();\n')
        lingering.stdin.flush()
        pid = lingering.stdout.readline().strip()
        self.assertTrue(pid.isdigit(), pid)
        self.assertIn(pid, self._backends(name))
        test_db.destroy(URL, name)
        self.assertFalse(test_db.exists(URL, name))
        self.assertEqual(self._backends(name), [])
        self.assertEqual(test_db._psql(URL, f'select count(*) from pg_stat_activity where pid = {pid}'), '0')
        lingering.stdin.write('select 1;\n')
        lingering.stdin.close()
        self.assertNotEqual(lingering.wait(timeout=config.get('test-db.psql_timeout_s')), 0)

    def test_destroy_is_idempotent(self):
        name = test_db.create(URL)
        test_db.destroy(URL, name)
        test_db.destroy(URL, name)
        test_db.destroy(URL, test_db.new_name())
        self.assertFalse(test_db.exists(URL, name))

    def test_a_failed_destroy_raises(self):
        with self.assertRaises(test_db.TestDatabaseError):
            test_db.destroy('postgresql://postgres@127.0.0.1:1/' + test_db.new_name(), test_db.new_name())

    def test_shell_wrapper_creates_and_destroys(self):
        name = test_db.new_name()
        self.addCleanup(test_db.destroy, URL, name)
        script = str(ROOT / 'scripts' / 'lib' / 'test_db.py')
        made = subprocess.run([sys.executable, script, 'create', name], capture_output=True, text=True, check=False)
        self.assertEqual((made.returncode, made.stdout.strip()), (0, name), made.stderr)
        self.assertTrue(test_db.exists(URL, name))
        gone = subprocess.run([sys.executable, script, 'destroy', name], capture_output=True, text=True, check=False)
        self.assertEqual(gone.returncode, 0, gone.stderr)
        self.assertFalse(test_db.exists(URL, name))
        refused = subprocess.run([sys.executable, script, 'destroy', 'postgres'], capture_output=True, text=True,
                                 check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('refusing database name', refused.stderr)

    def _dead_pid(self):
        ended = subprocess.Popen(['true'])
        ended.wait()
        return ended.pid

    def test_sweep_drops_idle_fixture_and_bootstrap_databases_only(self):
        # idle's owner has exited (a fixture that died before destroy); owned's owner is this live test.
        idle, busy, bootstrap = test_db.create(URL, owner=self._dead_pid()), test_db.create(URL), 'tower_test_zzboot'
        owned = test_db.create(URL)
        self.addCleanup(test_db.destroy, URL, idle)
        self.addCleanup(test_db.destroy, URL, busy)
        self.addCleanup(test_db.destroy, URL, owned)
        test_db._psql(URL, f'create database "{bootstrap}"')
        self.addCleanup(test_db._drop, URL, bootstrap)
        real = config.get
        patched = lambda key: bootstrap if key == 'cloud.postgres_database' else real(key)  # noqa: E731
        holder = subprocess.Popen([str(test_db.psql_binary()), self._url(busy), '-qtA'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(holder.stderr.close)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.stdin.close)
        self.addCleanup(holder.kill)
        holder.stdin.write('select pg_backend_pid();\n')
        holder.stdin.flush()
        holder.stdout.readline()
        with mock.patch.object(test_db.config, 'get', side_effect=patched):
            found = test_db.residue(URL)
            self.assertIn(idle, found)
            self.assertIn(bootstrap, found)
            self.assertNotIn(busy, found)
            self.assertNotIn(owned, found)
            self.assertNotIn(URL.rsplit('/', 1)[1], found)
            self.assertEqual(test_db.residue(URL, keep=(idle,)).count(idle), 0)
            dropped = test_db.sweep(URL, keep=tuple(n for n in found if n not in (idle, bootstrap)))
        self.assertEqual(sorted(dropped), sorted((idle, bootstrap)))
        self.assertFalse(test_db.exists(URL, idle))
        self.assertTrue(test_db.exists(URL, busy))
        self.assertTrue(test_db.exists(URL, owned))
        self.assertEqual(test_db._psql(URL, f"select count(*) from pg_database where datname = '{bootstrap}'"), '0')

    def test_the_ddl_lock_is_opened_as_a_lock_shared_across_users(self):
        # CHECK-USER-SHARED: as tower-check, open(path, 'a') of root's /tmp lock was refused (21 red tests of the full run
        # of 13/11 15:51 UTC); identity.open_lock opens another user's lock without O_CREAT
        opened = []
        import session_identity
        with mock.patch.object(session_identity, 'open_lock', side_effect=lambda path: opened.append(path) or open(os.devnull, 'r')):
            with test_db._one_ddl_at_a_time():
                pass
        self.assertEqual(opened, [test_db.config.get('test-db.ddl_lock_path')])

    def test_sweep_decides_again_under_the_ddl_lock(self):
        # A listing taken before create() recorded the owner (CREATE DATABASE, then the comment, in one lock) is stale;
        # the sweep decides again under that lock, so it never drops a database whose owner is alive.
        owned = test_db.create(URL)
        self.addCleanup(test_db.destroy, URL, owned)
        real, stale = test_db.residue, [[owned]]
        listing = lambda url=None, keep=(): stale.pop() if stale else real(url, keep)  # noqa: E731
        with mock.patch.object(test_db, 'residue', side_effect=listing):
            dropped = test_db.sweep(URL, keep=tuple(n for n in real(URL) if n != owned))
        self.assertNotIn(owned, dropped)
        self.assertTrue(test_db.exists(URL, owned))


class ContentionTests(unittest.TestCase):
    def test_ddl_waits_for_the_machine_wide_lock_and_gives_up_at_the_registered_wait(self):
        real = config.get
        patched = lambda key: 1 if key == 'test-db.ddl_lock_wait_s' else real(key)  # noqa: E731
        with open(real('test-db.ddl_lock_path'), 'a') as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            with mock.patch.object(test_db.config, 'get', side_effect=patched):
                with self.assertRaisesRegex(test_db.TestDatabaseError, 'DDL lock not free'):
                    test_db.create(URL)

    def test_a_psql_timeout_names_what_the_server_was_waiting_on(self):
        real_run = subprocess.run
        calls = []

        def run(cmd, *args, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(cmd, 1)
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(test_db.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(test_db.TestDatabaseError, 'pg_stat_activity'):
                test_db._psql(URL, 'select 1')


if __name__ == '__main__':
    unittest.main(verbosity=1)
