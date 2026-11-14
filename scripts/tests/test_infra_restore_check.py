"""RESTORE-DRILL (tower_infra.restore_check; architecture review, finding 25): the reading of a database restored from
tower-data's backup, and its comparison with production's.

On a throwaway database of the toolchain's PostgreSQL migrated by the service's runner (TI1), with the world of the
mechanisms' test: the reading is one statement in a read-only session and says what the engine's database holds; a
second database plays the restored one. Local PostgreSQL only, no network.
"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import deploy_classify  # noqa: E402
from infra_db import psql  # noqa: E402
from test_infra_mechanisms import World  # noqa: E402
from tower_infra import __main__ as main, mechanisms, restore_check  # noqa: E402


class TheReading(World):
    def test_it_says_what_the_engine_s_database_holds(self):
        done = self.job('a-check', selector={'adapter': 'container'})
        [made] = mechanisms.dispatch(self.db)
        mechanisms.end(self.db, made['run'], made['fence'], 'succeeded', result={'exit': 0})
        self.job('still-queued', executor='claude-sub')
        found = restore_check.facts(self.db)
        counted = {name: int(self.db.rows(f'select count(*) from {table}')[0][0]) for name, table in (
            ('tenants', 'work.tenant'), ('jobs', 'work.job'), ('runs', 'work.run'), ('events', 'log.event'),
            ('settings', 'work.config_value'))}
        self.assertEqual({name: found[name] for name in counted}, counted)
        self.assertEqual((found['tenants'], found['jobs'], found['runs'], found['jobs_open']), (2, 2, 1, 1))
        self.assertEqual(found['database'], self.name)
        self.assertEqual(found['migrations'], len(list((ROOT / 'infra/db/migrations').glob('*.sql'))))
        self.assertEqual(found['newest_migration'], sorted(path.stem for path in (ROOT / 'infra/db/migrations').glob('*.sql'))[-1])
        self.assertGreater(found['size_bytes'], 0)
        self.assertLessEqual(found['newest_job_at'], found['at'])
        self.assertLessEqual(found['newest_event_at'], found['at'])
        self.assertEqual(self.state(done), 'succeeded')

    def test_it_is_one_statement_in_a_read_only_session_and_writes_nothing(self):
        sent = []
        db = mock.Mock(rows=mock.Mock(side_effect=lambda sql, params=None: sent.append(sql) or [('{"events": 1}',)]))
        self.assertEqual(restore_check.facts(db), {'events': 1})
        self.assertEqual(sent, [restore_check.READ_ONLY, restore_check.FACTS])  # read only first, then the one reading
        for word in ('insert ', 'update ', 'delete ', 'create ', 'alter ', 'drop ', 'truncate '):
            self.assertNotIn(word, restore_check.FACTS.lower())
        # and a real session set so refuses a write: what the reading runs in
        refused = psql.Psql(self.db.url + '?options=-c%20default_transaction_read_only%3Don')
        with self.assertRaises(psql.DatabaseError) as denied:
            refused.rows("insert into work.tenant (name) values ('written')")
        self.assertEqual(denied.exception.sqlstate, '25006')  # read_only_sql_transaction
        self.assertEqual(json.loads(refused.rows(restore_check.FACTS)[0][0])['read_only'], 'on')


class TheComparison(unittest.TestCase):
    PRODUCTION = {'database': 'tower', 'server': '18.1', 'migrations': 19, 'tenants': 1, 'jobs': 9000, 'runs': 9100,
                  'events': 400000, 'newest_event_at': 2000.0}

    def test_a_restored_database_is_production_s_backup_when_it_holds_no_more_and_not_nothing(self):
        restored = {**self.PRODUCTION, 'jobs': 8990, 'runs': 9088, 'events': 399100, 'newest_event_at': 1700.0}
        self.assertEqual(restore_check.compared(restored, self.PRODUCTION), [])
        self.assertEqual(restore_check.compared(self.PRODUCTION, self.PRODUCTION), [])  # a restore point of this instant

    def test_what_is_not_production_s_backup_is_said(self):
        for change, word in (({'database': 'postgres'}, 'database'), ({'server': '17.5'}, 'server'), ({'events': 0}, 'events'),
                             ({'jobs': 9001}, 'jobs'), ({'tenants': None}, 'tenants'), ({'migrations': 20}, 'migrations'),
                             ({'newest_event_at': 2001.0}, 'newest_event_at')):
            why = restore_check.compared({**self.PRODUCTION, **change}, self.PRODUCTION)
            self.assertEqual(len(why), 1, (change, why))
            self.assertTrue(why[0].startswith(word), why)


class TheCommand(unittest.TestCase):
    def test_restore_check_is_the_init_container_s_command_with_the_owner_s_credentials(self):
        said, connection = [], mock.Mock()
        with mock.patch.dict(os.environ, {'TOWER_DB_HOST': 'restored.example', 'TOWER_DB_PORT': '5432', 'TOWER_DB_NAME': 'tower',
                                          'TOWER_DB_OWNER': 'the-owner', 'TOWER_DB_OWNER_PASSWORD': 'only the init has it',
                                          'AWS_REGION': 'us-east-1'}), \
                mock.patch('tower_infra.database.password_connection', return_value=connection) as connect, \
                mock.patch.object(restore_check, 'facts', return_value={'events': 3}):
            self.assertEqual(main.restore_check(out=said.append), 0)
        (where, user, password), how = connect.call_args
        self.assertEqual((where['host'], user, password, how), ('restored.example', 'the-owner', 'only the init has it',
                                                              {'purpose': 'restore-check'}))
        self.assertEqual(json.loads(said[0]), {'restore_check': {'events': 3}, 'host': 'restored.example'})
        self.assertNotIn('only the init has it', said[0])
        connection.close.assert_called_once_with()
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("if command == 'restore-check':", source)

    def test_it_runs_from_the_image_so_a_head_that_changes_it_is_not_code_only(self):
        self.assertIn(deploy_classify.CODE_ONLY + 'restore_check.py', deploy_classify.IMAGE_RUN)
        self.assertFalse(deploy_classify.code_only(['infra/service/tower_infra/restore_check.py'])[0])


if __name__ == '__main__':
    if not os.environ.get('TEST_DATABASE_URL'):
        raise SystemExit('TEST_DATABASE_URL is not set (source scripts/cloud/env.sh)')
    unittest.main()
