"""PSQL-SESSIONS (docs/operations/aws.md 22.9): the infrastructure's Postgres tests on psql sessions that stay up.

A migrated() database takes each one-line statement to an idle session and ends it with DISCARD ALL (what a statement
leaves, an advisory lock, a LISTEN, a setting, ends with it, as when its process ended); a refusal keeps its SQLSTATE;
anything psql's lexer would split goes through `psql -c`, one Query message, as before. Needs TEST_DATABASE_URL.
"""
import os
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from infra_db import psql  # noqa: E402
import test_db  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


class OneStatement(unittest.TestCase):
    def test_what_goes_to_a_session(self):
        for sql in ("select 1", "select 'a;b'", 'select "x;y" from t;', "select 1;  "):
            self.assertTrue(psql.one_statement(sql), sql)
        for sql in ("select 1; select 2", "select 1 -- c", "select /* c */ 1", "select $$a$$", "select 1 \\gx", "",
                    "select 'open"):
            self.assertFalse(psql.one_statement(sql), sql)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        self.name, self.db = psql.migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.addCleanup(self.db.close)

    def test_a_statement_on_a_session_reads_as_before_and_leaves_nothing_behind(self):
        self.assertTrue(self.db.keep)
        self.assertEqual(self.db.rows("select 'a''b', null, %(n)s::int + 1", {'n': 1}), [("a'b", None, '2')])
        self.assertEqual(self.db.rows('select 1 where false'), [])
        with self.assertRaises(psql.DatabaseError) as refused:
            self.db.rows('select 1/0')
        self.assertEqual(refused.exception.sqlstate, '22012')
        self.assertEqual(self.db.rows('select 7'), [('7',)])  # the session goes on after a refusal
        self.assertEqual(self.db.rows('select pg_try_advisory_lock(7)'), [('t',)])
        self.assertEqual(self.db.rows("select count(*) from pg_locks where locktype = 'advisory'"), [('0',)])
        self.assertEqual(self.db.rows('select 1; select 2'), [('1',), ('2',)])  # psql -c, as before
        self.assertEqual(len(self.db.idle), 1)  # one session served them all

    def test_threads_take_their_own_sessions(self):
        hold = threading.Barrier(3)
        seen = []

        def work():
            hold.wait()
            seen.append(self.db.rows('select pg_sleep(0.2), pg_backend_pid()')[0][1])
        threads = [threading.Thread(target=work) for _ in range(3)]
        for each in threads:
            each.start()
        for each in threads:
            each.join()
        self.assertEqual(len(set(seen)), 3)  # three at once: three backends, as three processes were

    def test_a_psql_on_any_other_address_opens_one_a_statement(self):
        other = psql.Psql(psql.database_url(URL, self.name))
        self.assertFalse(other.keep)
        self.assertEqual(other.rows('select 1'), [('1',)])
        self.assertEqual(other.idle, [])


if __name__ == '__main__':
    unittest.main()
