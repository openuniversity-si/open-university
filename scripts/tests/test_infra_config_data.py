"""Configuration as data (DEP9): the service's behaviour keys are rows of work.config_value, read at runtime, refreshed on
the tower_config event, with the compiled defaults as the fallback. Hermetic: fake database and fake notification (the
listener takes the wait as a function). The class that runs the SQL on a throwaway database needs TEST_DATABASE_URL
(Postgres, local port 54322 in the gate) and is skipped without it.
"""
import json
import os
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import autodeploy, config_data, http_port, port, wake  # noqa: E402
import test_infra_autodeploy as auto  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
TOKEN = 'torre-token'


class Table:
    """work.config_value for the one tenant: rows(sql, params) as the service's Config and the port's routes use it."""

    def __init__(self):
        self.rows_, self.reads, self.events, self.broken = {}, 0, [], False

    def scope(self):
        table = self

        class Scope:
            def __enter__(self):
                if table.broken:
                    raise RuntimeError('database down')
                return table

            def __exit__(self, *_):
                return False
        return Scope()

    def put(self, key, value, version=1):
        self.rows_[key] = (value, version)

    def rows(self, sql, params=None):
        if sql.startswith('select v.key'):
            self.reads += 1
            return [(key, json.dumps(value), version) for key, (value, version) in self.rows_.items()]
        if sql.startswith('select id::text from work.tenant'):
            return [('t-1',)] if params['digest'] == port.sha256(TOKEN) else []
        if sql.startswith('with old as'):
            key, value = params['key'], json.loads(params['value'])
            old, version = self.rows_.get(key, (None, 0))
            self.put(key, value, version + 1)
            self.events.append({'name': key, 'old': old, 'new': value, 'version': version + 1, 'reason': params['reason']})
            return [(version + 1,)]
        if sql.startswith('select value::text, version'):
            if params['key'] not in self.rows_:
                return []
            value, version = self.rows_[params['key']]
            return [(json.dumps(value), version, 'torre', 'why', '2026-11-09 01:00:00+00')]
        raise AssertionError(sql)


def call(table, method, path, body=None, token=TOKEN):
    answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                               'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                              table, '')
    return answer['statusCode'], json.loads(answer['body'])


class Defaults(unittest.TestCase):
    def test_the_compiled_defaults_mirror_the_registry(self):
        for name, (kind, default) in config_data.SPEC.items():
            area = name.split('.')[0]
            item = json.loads((ROOT / 'config' / 'registry' / area / f'{name}.json').read_text())
            self.assertEqual(item['default'], default, name)
            self.assertEqual({'boolean': bool, 'string': str, 'integer': int, 'number': float}[item['type']], kind, name)
            self.assertIn('infra/service/tower_infra/code_bundle.py' if name == 'deploy.live_code' else  # SLOW-PATH-NO-ROLLOUT-WAIT
                          'infra/service/tower_infra/live_image.py' if name in config_data.EMPTY_OK + ('deploy.live_stale_s',) else
                          # DEPLOY-CANARY, CANARY-OWN-SLOT: the canary's own keys are read by the canary
                          'infra/service/tower_infra/canary.py' if name in ('deploy.canary_limit_s', 'deploy.canary_slot') else
                          'infra/service/tower_infra/live_image.py' if name in config_data.ZERO_OK else
                          'infra/service/tower_infra/port.py' if name == 'deploy.standby_fresh_s' else  # IMAGE-SWAP-TIGHTEN
                          'infra/service/tower_infra/autodeploy.py' if area == 'deploy' else
                          'infra/service/tower_infra/config_data.py' if area == 'service' else 'infra/service/tower_infra/ingress.py',
                          item['x-readers'], name) if area != 'medir' else None
        for name, value in autodeploy.DEFAULTS.items():
            self.assertEqual(config_data.SPEC[f'deploy.{name}'][1], value)

    def test_the_defaults_are_the_engine_as_it_runs_and_never_spot_standbys_with_successors(self):
        # DEFAULTS-AS-LIVE (revisão da arquitetura, achado 36): the Torre's rows of 11/11 (0, 1, 1) were the opposite of the
        # defaults (1, 0, 0); a lost row brought back Spot standbys and successors together, which the db.t4g.micro's
        # connections do not hold (achado 34a: the port answered 500 on 11/11 22:17 to 22:21 UTC)
        defaults = {name: config_data.SPEC[name][1] for name in config_data.ZERO_OK}
        self.assertEqual(defaults, {'deploy.intask_standbys': 1, 'deploy.canary_slot': 1})  # GATE-LOOKS-GONE: no Spot standbys

    def test_validate_follows_the_registry_types(self):
        self.assertEqual(config_data.validate('deploy.monthly_usd', 5), 5.0)
        self.assertIs(config_data.validate('deploy.auto', False), False)
        self.assertEqual(config_data.validate('deploy.intask_standbys', 0), 0)  # 0 holds no successor
        for name, bad in (('deploy.auto', 'no'), ('deploy.debounce_s', 1.5), ('deploy.debounce_s', 0), ('deploy.debounce_s', True),
                          ('deploy.base_branch', ' '), ('service.dispatch_s', -1), ('nope.x', 1),
                          ('deploy.intask_standbys', -1), ('deploy.intask_standbys', 1.5)):
            with self.assertRaises(ValueError, msg=(name, bad)):
                config_data.validate(name, bad)

    def test_the_channel_and_the_migration(self):
        sql = (ROOT / 'infra/db/migrations/0010_config_values.sql').read_text()
        self.assertIn("pg_notify('tower_config'", sql)
        self.assertIn("pg_notify('tower_deploy'", sql)
        self.assertEqual(wake.CONFIG, 'tower_config')
        wake.Wake(lambda: None, wake.CONFIG)


class Refresh(unittest.TestCase):
    def test_no_row_reads_the_default_and_a_row_wins_on_the_event(self):
        table = Table()
        config = config_data.Config(table.scope)
        self.assertEqual(config.refresh(), [])
        self.assertEqual(config.get('service.dispatch_s'), 1.0)
        table.put('service.dispatch_s', 0.25)
        self.assertEqual(config.refresh(), ['service.dispatch_s'])
        self.assertEqual(config.get('service.dispatch_s'), 0.25)
        self.assertEqual(config.refresh(), [])
        table.rows_.clear()
        self.assertEqual(config.refresh(), ['service.dispatch_s'])  # a row gone is the default again
        self.assertEqual(config.get('service.dispatch_s'), 1.0)

    def test_an_invalid_value_or_a_dead_database_keeps_the_last_good_one(self):
        table = Table()
        config = config_data.Config(table.scope)
        table.put('deploy.debounce_s', 7)
        config.refresh()
        table.put('deploy.debounce_s', 'seven', 2)
        table.put('deploy.auto', 'maybe')
        with self.assertLogs('tower_infra.config_data', 'WARNING'):
            config.refresh()
        self.assertEqual((config.get('deploy.debounce_s'), config.get('deploy.auto')), (7, True))
        table.broken = True
        with self.assertLogs('tower_infra.config_data', 'ERROR'):
            self.assertEqual(config.refresh(), [])
        self.assertEqual(config.get('deploy.debounce_s'), 7)

    def test_a_row_of_a_key_the_registry_no_longer_has_is_not_read_and_said_once(self):
        # KEY-GONE: removed keys keep their rows (the port has no delete): live 15/11 the prewarm's cap had one, and every
        # refresh warned config.invalid about it
        table = Table()
        config = config_data.Config(table.scope)
        gone = '.'.join(('deploy', 'gone_key'))
        table.rows_[gone] = (3, 5)
        table.put('service.dispatch_s', 0.25)
        with self.assertLogs('tower_infra.config_data', 'INFO') as logs:
            self.assertEqual(config.refresh(), ['service.dispatch_s'])
        self.assertEqual([line for line in logs.output if 'WARNING' in line], [])
        self.assertIn(f'the row of {gone} is of a key the registry no longer has', '\n'.join(logs.output))
        self.assertNotIn(gone, config.values)
        table.put('service.dispatch_s', 0.5, 2)
        with self.assertLogs('tower_infra.config_data', 'INFO') as logs:
            self.assertEqual(config.refresh(), ['service.dispatch_s'])
        self.assertNotIn('no longer has', '\n'.join(logs.output))  # said once

    def test_the_listener_refreshes_on_the_notification_and_not_on_a_clock(self):
        table = Table()
        config = config_data.Config(table.scope)
        stop, notified, done = threading.Event(), threading.Semaphore(0), threading.Event()
        timeouts = []

        def wait(timeout_s):  # the NOTIFY: blocks until the test notifies
            timeouts.append(timeout_s)
            notified.acquire()
            done.set()
        thread = config_data.listen(config, stop, wait, safety_s=300)
        self.assertEqual(table.reads, 0)  # nothing was read without an event
        table.put('service.dispatch_s', 2.0)
        notified.release()
        done.wait(2)
        for _ in range(200):
            if config.get('service.dispatch_s') == 2.0:
                break
            threading.Event().wait(0.01)
        self.assertEqual((config.get('service.dispatch_s'), table.reads), (2.0, 1))
        stop.set()
        notified.release()
        thread.join(2)
        self.assertEqual(timeouts[0], 300)  # only the safety timeout of a lost notification


class Routes(unittest.TestCase):
    def test_put_validates_records_and_get_answers_the_value_or_the_default(self):
        table = Table()
        self.assertEqual(call(table, 'GET', '/v1/config/deploy.auto')[1], {'key': 'deploy.auto', 'value': True, 'source': 'default'})
        status, body = call(table, 'PUT', '/v1/config/deploy.auto', {'value': False, 'reason': 'freeze'})
        self.assertEqual((status, body), (200, {'key': 'deploy.auto', 'value': False, 'version': 1}))
        status, body = call(table, 'PUT', '/v1/config/deploy.auto', {'value': True, 'reason': 'thaw'})
        self.assertEqual(body['version'], 2)
        self.assertEqual(table.events[-1], {'name': 'deploy.auto', 'old': False, 'new': True, 'version': 2, 'reason': 'thaw'})
        got = call(table, 'GET', '/v1/config/deploy.auto')[1]
        self.assertEqual((got['value'], got['source'], got['version'], got['actor']), (True, 'table', 2, 'torre'))

    def test_refusals(self):
        table = Table()
        self.assertEqual(call(table, 'PUT', '/v1/config/deploy.auto', {'value': 'x', 'reason': 'r'})[0], 400)
        self.assertEqual(call(table, 'PUT', '/v1/config/deploy.auto', {'value': True})[0], 400)  # no reason
        self.assertEqual(call(table, 'PUT', '/v1/config/deploy.nothing', {'value': 1, 'reason': 'r'})[0], 404)
        self.assertEqual(call(table, 'GET', '/v1/config/deploy.nothing')[0], 404)
        self.assertEqual(call(table, 'PUT', '/v1/config/deploy.auto', {'value': True, 'reason': 'r'}, token='other')[0], 401)
        self.assertEqual(table.events, [])
        self.assertEqual(call(table, 'GET', '/v1/config/deploy.auto', token='')[0], 401)


class Autodeploy(unittest.TestCase):
    def test_a_config_row_changes_the_next_look_without_a_deploy(self):
        rig = auto.Rig()
        table = Table()
        rig.watcher.config = config_data.Config(table.scope)
        rig.db.push(auto.T0 - 500, auto.HEAD)
        table.put('deploy.auto', False)
        self.assertIn('off', rig.look()[1])
        self.assertEqual(rig.rings, [])
        table.put('deploy.auto', True, 2)
        self.assertEqual(rig.look(1), ('ring', 'started'))

    def test_the_row_wins_over_the_git_override_and_no_row_leaves_it(self):
        rig = auto.Rig()
        table = Table()
        rig.watcher.config = config_data.Config(table.scope)
        rig.watcher.overrides['debounce_s'] = ('1', 99)
        rig.watcher.config.refresh()
        self.assertEqual(rig.watcher.settings()['debounce_s'], 99)
        table.put('deploy.debounce_s', 5)
        rig.watcher.config.refresh()
        self.assertEqual(rig.watcher.settings()['debounce_s'], 5)
        self.assertEqual(rig.watcher.settings()['alarm_usd'], autodeploy.DEFAULTS['alarm_usd'])


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from infra_db.psql import migrated
        import test_db
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.db.rows("insert into work.tenant (name, token_sha256) values ('torre', %(d)s)", {'d': port.sha256(TOKEN)})

    def test_put_writes_the_row_the_event_and_the_trigger_notifies(self):
        first = call(self.db, 'PUT', '/v1/config/deploy.debounce_s', {'value': 9, 'reason': 'test'})
        self.assertEqual(first[0], 200, first)
        self.assertEqual(first[1]['version'], 1)
        self.assertEqual(call(self.db, 'PUT', '/v1/config/deploy.debounce_s', {'value': 11, 'reason': 'again'})[1]['version'], 2)
        config = config_data.Config(lambda: _Scope(self.db))
        config.refresh()
        self.assertEqual(config.get('deploy.debounce_s'), 11)
        event = self.db.rows("select payload from log.event where type = 'platform.config.changed' order by occurred_at desc limit 1")
        payload = json.loads(event[0][0]) if isinstance(event[0][0], str) else event[0][0]
        self.assertEqual((payload['old'], payload['new'], int(payload['version'])), (9, 11, 2))
        self.assertIn('wake_config', self.db.rows("select tgname from pg_trigger where tgname = 'wake_config'")[0][0])


class _Scope:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        return False


if __name__ == '__main__':
    unittest.main()
