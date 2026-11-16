"""RUNNER-OWN-LOGIN (migration 0019; architecture review, finding 14): the runner's login owns nothing and may do only
what a runner does.

On a throwaway database of the toolchain's PostgreSQL migrated by the service's runner (TI1), with the world of the
mechanisms' test built by the owner (the service's login in production). A second connection is the runner's login,
tower_runner, as the owner's step creates it (tower_infra.dbinit) and the service grants it (work.grant_runner()):
every statement a runner's process sends passes on it, and what a pull request's check could do with the service's
login is refused (SQLSTATE 42501). Local PostgreSQL only, no network.
"""
import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db import psql  # noqa: E402
from test_infra_mechanisms import TORRE, World  # noqa: E402
from tower_infra import __main__ as main, code_bundle, dbinit, lifecycle, live_image, mechanisms, migrations, rehearsal, runner, vitals  # noqa: E402

DENIED = '42501'
S, OLD = 'd' * 64, 'e' * 64
BOTH = ','.join(sorted(live_image.KEYS.values()))
ROLE = ("do $$ begin create role tower_runner login; "
        "exception when duplicate_object or unique_violation then null; end $$")  # the cluster's, as dbinit makes it
POINT = ("insert into work.config_value (tenant_id, key, value, actor, reason) select t.id, k, to_jsonb(%(digest)s::text), "
         "'test', 'test' from work.tenant t, unnest(string_to_array(%(keys)s, ',')) k where t.name = 'torre' "
         "on conflict (tenant_id, key) do update set value = excluded.value, version = work.config_value.version + 1")


class TheRunnersLogin(World):
    def setUp(self):
        super().setUp()
        self.db.rows(ROLE)
        self.assertEqual(self.db.rows('select work.grant_runner()'), [('t',)])
        self.runner = psql.Psql(re.sub(r'//[^@/]*@', f'//{dbinit.RUNNER_ROLE}@', self.db.url))
        self.assertEqual(self.runner.rows('select current_user::text'), [(dbinit.RUNNER_ROLE,)])

    def refused(self, sql, params=None, state=DENIED):
        with self.assertRaises(psql.DatabaseError) as refused:
            self.runner.rows(sql, params)
        self.assertEqual(refused.exception.sqlstate, state, str(refused.exception)[:300])

    def events(self, kind):
        return [json.loads(row[0]) for row in self.db.rows(
            'select payload::text from log.event where type = %(type)s order by occurred_at', {'type': kind})]

    def pointers(self):
        return dict(self.db.rows("select key, value #>> '{}' from work.config_value where key like 'deploy.live_image_%'"))

    # --- what a runner does ------------------------------------------------------------------------------------------------
    def test_it_takes_relays_renews_and_ends_a_run_through_the_owners_functions(self):
        check = self.job('a-check', selector={'adapter': 'container'})
        [made] = mechanisms.dispatch(self.db)  # the service's claim
        self.assertIsNone(runner.take(self.runner, 'agent-session', 'the-runner'))  # no run of another adapter
        taken = runner.take(self.runner, 'container', 'the-runner')
        self.assertEqual((taken['job'], taken['run'], taken['fence'], taken['n']), (check, made['run'], made['fence'], 1))
        self.assertEqual(self.events('run.running')[0]['runner'], 'the-runner')
        self.assertIsNone(runner.take(self.runner, 'container', 'another-slot'))  # taken once
        self.assertTrue(mechanisms.relay(self.runner, taken['run'], taken['fence'], 'run.usage', {'meter': 'cpu_s', 'quantity': 2}))
        self.assertEqual(runner.renew(self.runner, taken, '5 minutes'), 'running')
        self.assertIsNone(mechanisms.end(self.runner, taken['run'], taken['fence'] + 1, 'succeeded'))  # fenced, as before
        self.assertEqual(mechanisms.end(self.runner, taken['run'], taken['fence'], 'succeeded', result={'exit': 0}), 'succeeded')
        self.assertEqual((self.state(check), self.in_use('script-runner')), ('succeeded', '0'))

    def test_it_says_what_a_runners_process_says_and_beats_as_a_runner(self):
        said = {'role': 'runner', 'digest': S, 'task': 'task-1', 'tenant': 'torre', 'producer': 'tower-runner'}
        self.db.rows(POINT, {'digest': S, 'keys': BOTH})
        self.runner.rows(live_image.LIVE, {**said, 'id': 'live-1', 'key': live_image.KEYS['runner'], 'version': 1, 'parts': '{"swap_s": 0.1}'})
        self.runner.rows(live_image.UP, {**said, 'id': 'up-1', 'payload': json.dumps({'role': 'runner', 'state': 'warm'})})
        self.runner.rows(live_image.HOLDS, {**said, 'id': 'holds-1', 'payload': json.dumps({'role': 'runner', 'state': 'holds'})})
        self.runner.rows(lifecycle.RECORD, {'id': 'started-1', 'type': lifecycle.STARTED, 'producer': 'tower-runner',
                                           'subject': 'process/runner', 'payload': '{"role": "runner"}', 'tenant': 'torre'})
        self.runner.rows(main.WARM_EVENT, {'id': 'warm-1', 'payload': '{"ok": true}'})
        self.runner.rows(main.UP_EVENT, {'id': 'task-up-1', 'producer': 'tower-runner', 'payload': '{"role": "runner"}'})
        for kind, count in (('platform.deploy.image_live', 1), (live_image.SUCCESSOR, 2), (lifecycle.STARTED, 1),
                            ('platform.runner.warm', 1), ('platform.deploy.task_up', 1)):
            self.assertEqual(len(self.events(kind)), count, kind)
        self.runner.rows(live_image.UPSERT, said)
        self.runner.rows(live_image.LIVE_BEAT, said)
        watched = self.runner.rows(live_image.WATCH, {**said, 'key': live_image.KEYS['runner']})  # a standby's pass
        self.assertEqual(watched[0][0], S)
        self.assertEqual(self.runner.rows(live_image.READ, {'tenant': 'torre', 'key': live_image.KEYS['runner']})[0][0], f'"{S}"')
        self.assertEqual(self.db.rows('select role, digest, task from work.standby_beat'), [('runner', S, 'task-1')])

    def test_every_statement_of_a_runners_process_passes_on_its_login(self):
        # each module's statements, as the process sends them (a fragment of one is not a statement); the service's own
        # (the sweep of every role's beats, the settings it observes) are not the runner's
        params = dict(role='runner', digest=S, task='task-1', tenant='torre', key=live_image.KEYS['runner'], keys=BOTH,
                      id='an-id', producer='tower-runner', payload='{}', parts='{}', version=1, actor='tower-runner',
                      reason='test', was=OLD, live='x', wrote_at=1.0, started_at=1.0, type=lifecycle.STOPPED,
                      subject='process/runner', adapter='container', runner='r', run='00000000-0000-0000-0000-000000000000',
                      fence=1, lease='5 minutes', name='rehearsal-0a1b', window=1.0, head='h' * 40, order='h' * 40,
                      window_s=1.0, since=1.0, heir='task-2', turn=1, state='started', born='1',
                      ref='refs/heads/mod/roadmap-integration', sha='a' * 40, repo='org/name',  # UID0-FROM-BASE: LANDED
                      runs='00000000-0000-0000-0000-000000000000',  # CANCEL-WAKES-RUNNER: ENDED_JOBS
                      pointer=live_image.KEYS['runner'])  # OWN-POINTER: WANTS reads the runner's own pointer
        self.db.rows(POINT, {'digest': S, 'keys': BOTH})
        sent = []
        for module, left_out in ((live_image, {'EMPTY_IF', 'EMPTY_THEN', 'WOKEN', 'SWEEP_OLD', 'SWAP_CANARY'}), (runner, set()),
                                 (lifecycle, set()), (code_bundle, set()), (rehearsal, {'TENANT', 'QUEUE', 'EXECUTOR', 'CAPACITY'})):
            for name, sql in sorted(vars(module).items()):
                if (name.isupper() and isinstance(sql, str) and name not in left_out
                        and re.match(r'\s*(select|insert|with|update|delete)\b', sql)):
                    names = set(re.findall(r'%\((\w+)\)s', sql))
                    self.assertLessEqual(names, set(params), (module.__name__, name))
                    self.runner.rows(sql, {each: params[each] for each in names})
                    sent.append(name)
        for owed in ('TAKE', 'RENEW', 'RUN', 'READ', 'DRILL', 'LIVE', 'REHEARSE', 'UPSERT', 'WATCH', 'LIVE_BEAT', 'EMPTY', 'LEAVE', 'ALONE',
                     'RELOAD_OF', 'RELOAD_START', 'RELOAD_SAY', 'ORDER_START', 'ORDER_SAY', 'WANTS', 'UP', 'HOLDS', 'RECORD',
                     'LANDED', 'ENDED_JOBS'):
            self.assertIn(owed, sent)

    def test_it_hands_a_pointer_back_and_sets_none(self):
        self.db.rows(POINT, {'digest': S, 'keys': BOTH})
        handed = self.runner.rows(live_image.EMPTY, {
            'tenant': 'torre', 'keys': BOTH, 'digest': S, 'actor': 'tower-runner', 'reason': 'handback', 'id': 'retired-1',
            'payload': json.dumps({'digest': S, 'by': 'handback'})})
        self.assertEqual(json.loads(handed[0][0]), sorted(live_image.KEYS.values()))
        self.assertEqual(set(self.pointers().values()), {''})
        self.assertEqual(self.events('platform.deploy.image_retired')[0]['by'], 'handback')
        for sql in ("update work.config_value set value = to_jsonb('f00d'::text), version = version + 1 where key = 'deploy.live_image_runner'",
                    "update work.config_value set value = '\"\"'::jsonb where key = 'deploy.live_image_runner'",  # not a new version
                    "update work.config_value set key = 'deploy.base_branch', value = '\"\"'::jsonb, version = version + 1 "
                    "where key = 'deploy.live_image_runner'"):
            self.refused(sql)
        self.db.rows("insert into work.config_value (tenant_id, key, value, actor, reason) select id, 'deploy.base_branch', "
                     "'\"main\"'::jsonb, 'test', 'test' from work.tenant where name = 'torre'")
        self.refused("update work.config_value set value = '\"\"'::jsonb, version = version + 1 where key = 'deploy.base_branch'")
        self.refused("insert into work.config_value (tenant_id, key, value, actor, reason) select id, 'deploy.live_code', "
                     "'\"x\"'::jsonb, 'r', 'r' from work.tenant where name = 'torre'")
        self.refused("delete from work.config_value where key = 'deploy.base_branch'")
        self.assertEqual(set(self.pointers().values()), {''})

    # --- and nothing else ---------------------------------------------------------------------------------------------------
    def test_what_a_check_could_do_with_the_services_login_is_refused(self):
        check = self.job('a-check', selector={'adapter': 'container'})
        self.db.rows(live_image.UPSERT, {'role': 'service', 'digest': S, 'task': 'the-service'})
        for sql in (
                "insert into work.tenant (name) values ('mine')",
                'select token_sha256 from work.tenant',
                "insert into work.job (tenant_id, input_uri, input_digest, executor) select id, 'in/x', 'sha256:x', 'script-runner' from work.tenant limit 1",
                "update work.job set state = 'succeeded'",
                'delete from work.job',
                'select * from work.run',
                'update work.capacity set slots = 100',
                'select * from work.capacity',
                "insert into work.executor (name, adapter) values ('mine', 'container')",
                'select work.reap()',  # the dispatcher's, with the caller's rights
                'select work.hold_job(%(job)s::uuid, null)',
                "update log.event set payload = '{}'::jsonb",
                'delete from log.event',
                'delete from work.standby_beat',  # the service's beat is not the runner's to withdraw
                "update work.standby_beat set role = 'runner'",
                "insert into work.standby_beat (role, digest, task) values ('service', 'f00d', 'mine')",
                "select log.rewind(null, null, null)", 'select * from log.subscription', 'select * from work.train'):
            self.refused(sql, {'job': check})
        for kind in ('platform.deploy.image_swap', 'platform.deploy.landed', 'platform.deploy.canary', 'platform.train.landed',
                     'job.created', 'run.started', 'run.ended', 'forge.repository.pushed', 'platform.config.observed'):
            self.refused("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                         "values ('forged', null, %(type)s, clock_timestamp(), 'tower-runner', 'forged', '{}'::jsonb)", {'type': kind})
        self.assertEqual((self.state(check), self.db.rows('select count(*) from work.standby_beat')), ('queued', [('1',)]))
        self.assertEqual(self.db.rows("select count(*) from log.event where event_id = 'forged'"), [('0',)])

    def test_the_service_the_owner_is_bound_by_none_of_it(self):
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                     "values ('swap-1', null, 'platform.deploy.image_swap', clock_timestamp(), 'tower-service', 'deploy/image', '{}'::jsonb)")
        self.db.rows(live_image.UPSERT, {'role': 'service', 'digest': S, 'task': 'the-service'})
        self.db.rows(POINT, {'digest': S, 'keys': BOTH})  # the landing's swap sets the pointers
        self.assertEqual(set(self.pointers().values()), {S})
        self.db.rows(live_image.SWEEP_OLD)

    def test_the_owners_functions_are_the_owners_and_the_runners(self):
        owned = ('take_run', 'rehearse_run', 'relay_run', 'renew_lease', 'end_run')
        found = self.db.rows(
            "select p.proname, p.prosecdef, has_function_privilege('tower_runner', p.oid, 'execute'), "
            "has_function_privilege('public', p.oid, 'execute'), array_to_string(p.proconfig, ',') from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'work' and p.proname = any(string_to_array(%(names)s, ',')) "
            "order by 1", {'names': ','.join(owned)})
        self.assertEqual(found, [(name, 't', 't', 'f', 'search_path=work, log, pg_catalog') for name in sorted(owned)])

    # --- the runner's rehearsal ----------------------------------------------------------------------------------------------
    def test_its_rehearsal_takes_and_ends_a_run_of_no_one_and_leaves_nothing_even_committed(self):
        before = self.db.rows('select (select count(*) from log.event), (select count(*) from work.tenant), '
                              '(select count(*) from work.job), (select count(*) from work.run), (select count(*) from work.capacity)')
        parts = rehearsal.run(self.runner, mark='0a1b2c')  # each statement of this connection commits by itself
        self.assertEqual(sorted(parts), ['run_s'])
        self.assertEqual(self.db.rows('select (select count(*) from log.event), (select count(*) from work.tenant), '
                                      '(select count(*) from work.job), (select count(*) from work.run), '
                                      '(select count(*) from work.capacity)'), before)
        self.refused("select work.rehearse_run('torre')", state='P0001')  # only under a rehearsal's name
        with self.assertRaises(rehearsal.Unrehearsed):
            rehearsal.run(type('Db', (), {'rows': lambda self, sql, params=None: [('f',)]})())

    def test_a_real_run_that_waits_is_not_the_rehearsals(self):
        check = self.job('a-check', selector={'adapter': 'container'})
        [made] = mechanisms.dispatch(self.db)
        rehearsal.run(self.runner)
        self.assertEqual(self.db.rows("select state from work.run where id = %(run)s::uuid", {'run': made['run']}), [('starting',)])
        self.assertEqual(self.state(check), 'running')

    # --- how the login comes to be ------------------------------------------------------------------------------------------
    def test_the_owners_step_makes_the_login_and_every_migration_pass_grants_it(self):
        said = dbinit.statements('tower')
        self.assertIn('create role tower_runner login;', said)
        self.assertIn('grant rds_iam to tower_runner;', said)
        self.assertIn('grant connect on database tower to tower_runner;', said)
        self.assertNotIn('grant create, connect on database tower to tower_runner', said)  # it creates nothing
        self.assertEqual(vitals.runner_login(self.db), {'runner_login': 'granted'})  # what the hour's vitals say of it
        self.db.rows('revoke insert on log.event from tower_runner')
        self.assertEqual(vitals.runner_login(self.db), {'runner_login': 'not granted'})
        self.db.rows('revoke select on work.config_value from tower_runner')
        self.refused('select 1 from work.config_value')
        self.assertEqual(migrations.migrate(self.db, ROOT / 'infra/db/migrations', 'test'), [])  # nothing to apply: the grants again
        self.assertEqual(self.runner.rows('select count(*) from work.config_value'), [('0',)])
        self.assertEqual(vitals.runner_login(self.db), {'runner_login': 'granted'})
        self.assertEqual(TORRE, 'torre-of-the-test')  # (the world's tenants are the mechanisms' test's)


if __name__ == '__main__':
    if not os.environ.get('TEST_DATABASE_URL'):
        raise SystemExit('TEST_DATABASE_URL is not set (source scripts/cloud/env.sh)')
    unittest.main()
