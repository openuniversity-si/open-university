"""IMAGE-SWAP-DB-LOAD (docs/operations/aws.md 22.9): no statement of the swap's moment scans the whole log or the work tables.

Live on 10/11 (#470) the runner's TAKE took 0.796 s and the service's first reap and dispatch 1.536 s, statements that take
milliseconds on an idle database: at that moment the landing's commit wakes the autodeploy and prewarm looks, the status
polls and the port's BASE_HEAD, and log.event had no index but its primary key (occurred_at, event_id), so each read by type
or by event_id read the whole month's partition on the db.t4g.micro. Migration 0015 indexes log.event by (type, occurred_at)
and by event_id, and work.run / work.job by their few open rows. Here, on Postgres with a log big enough for the planner
to choose (TEST_DATABASE_URL), every such statement's plan reaches the log and the work tables only through an index.
"""
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from infra_db.psql import PLACEHOLDER, literal, migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import autodeploy, canary, config_data, forge_webhooks, http_port, live_image, mechanisms, port, queue_deploy, runner  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
MIGRATION = ROOT / 'infra/db/migrations/0015_swap_indexes.sql'
DIGEST = 'd' * 40
REF = json.dumps([{'ref': 'refs/heads/mod/roadmap-integration'}])
EVENTS, JOBS = 40000, 5000
# the log's mix: runs dominate, the platform's own types the looks read are rare (as live)
COMMON = ('job.created', 'run.started', 'run.running', 'run.reported', 'run.ended', 'forge.pull_request.synchronize',
          'forge.check_run.completed')
RARE = ('forge.repository.pushed', 'platform.deploy.landed', 'platform.deploy.image_swap', 'platform.deploy.image_live',
        'platform.deploy.standby', 'platform.deploy.observed', 'platform.runner.warm', 'platform.config.observed',
        'platform.deploy.rung', 'platform.deploy.fast', 'forge.pull_request.closed')


def since(days):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - days * 86400))


# every statement on the swap's moment: (name, sql, params); the dispatcher's functions by the loops they run
SWAP_MOMENT = [
    ('port.BASE_HEAD', port.BASE_HEAD, {'refs': REF, 'ref': 'refs/heads/mod/roadmap-integration', 'merge': 'x' * 40}),
    ('port.DECIDE', port.DECIDE, {'tenant': 'torre', 'keys': ','.join(port.SWAP_KEYS), 'base': 'mod/roadmap-integration',
                                  'merge': 'x' * 40, 'key': 'prewarm:code:' + 'p' * 40}),  # LANDING-ONE-READ
    ('port.LANDED_SWAP', port.LANDED_SWAP, {
        'id': 'platform.deploy.landed:t', 'digest': DIGEST, 'fresh_s': 3, 'keys': ','.join(live_image.KEYS.values()),
        'reason': 't', 'config_tenant': 'torre', 'tenant': None, 'payload': '{}', 'why': '',
        'swap_id': 'platform.deploy.image_swap:t', 'swap': '{}'}),
    ('port.LANDED_ONLY', port.LANDED_ONLY, {'id': 'platform.deploy.landed:t', 'tenant': None, 'payload': '{}'}),
    ('status.observed', "select payload::text from log.event where type = 'platform.deploy.observed' and "
     "(tenant_id is null or tenant_id = %(tenant)s::uuid) and occurred_at > now() - interval '400 days' "
     "order by occurred_at desc limit 1", {'tenant': None}),
    ('status.standby', "select payload::text from log.event where type = 'platform.deploy.standby' and tenant_id is null "
     "and occurred_at > now() - interval '30 days' order by occurred_at desc limit 20", {}),
    ('status.image_retired', "select payload::text from log.event where type = 'platform.deploy.image_retired' and "
     "tenant_id is null and occurred_at > now() - interval '30 days' order by occurred_at desc limit 20", {}),
    ('autodeploy.FAST_SEED', autodeploy.FAST_SEED, {'limit': 20}),
    ('autodeploy.PUSHES', autodeploy.PUSHES, {'since': since(1), 'ref': REF}),
    ('autodeploy.LANDINGS', autodeploy.LANDINGS, {'since': since(7)}),
    ('autodeploy.LEDGER', autodeploy.LEDGER, {'since': since(30)}),
    ('autodeploy.OBSERVE', autodeploy.OBSERVE, {'id': 'platform.deploy.observed:t', 'payload': '{}'}),
    ('autodeploy.SWAP_OF', autodeploy.SWAP_OF, {'id': 'platform.deploy.image_swap:t'}),
    ('autodeploy.STANDBYS', autodeploy.STANDBYS, {'digest': DIGEST}),
    ('autodeploy.NEWEST_SWAP', autodeploy.NEWEST_SWAP, {}),
    ('autodeploy.LIVE_SEEN', autodeploy.LIVE_SEEN, {'digest': DIGEST, 'since': time.time() - 120}),
    ('live_image.LIVE', live_image.LIVE, {
        'id': 'platform.deploy.image_live:t', 'producer': 'runner', 'role': 'runner', 'digest': DIGEST, 'task': 't',
        'parts': '{}', 'tenant': 'torre', 'key': live_image.KEYS['runner'], 'version': 1}),
    # IMAGE-SWAP-RELOAD: the reload's trigger, claim and record come a second or more after the swap, by the same indexes
    ('live_image.RELOAD_OF', live_image.RELOAD_OF, {'role': 'runner', 'digest': DIGEST, 'tenant': 'torre',
                                                    'live': 'platform.deploy.image_live:t'}),
    # DEPLOY-CANARY: the standby pass's one statement (a second apart, with the swap's canary job by its unique key), and
    # the canary's own: its job by key, the swap's head, its reading and its verdict's record
    ('live_image.WATCH', live_image.WATCH, {'role': 'runner', 'digest': 'registry/tower:old', 'task': 't', 'tenant': 'torre',
                                            'key': live_image.KEYS['runner']}),
    ('canary.JOB', canary.JOB, {'tenant': 'torre', 'key': f'canary:swap:{DIGEST}:1'}),
    ('canary.HEAD', canary.HEAD, {'digest': DIGEST}),
    ('canary.READ', canary.READ, {'tenant': 'torre', 'id': '01a1be27-1c2d-7af4-b1e5-e2087696832c'}),
    ('canary.SETTLE', canary.SETTLE, {'id': 'platform.deploy.canary:t', 'producer': 'tower-service', 'payload': '{}'}),
    ('status.canary', "select payload::text from log.event where type = 'platform.deploy.canary' and tenant_id is null "
     "and occurred_at > now() - interval '30 days' order by occurred_at desc limit 20", {}),
    ('live_image.RELOAD_START', live_image.RELOAD_START, {
        'id': 'platform.deploy.image_reload:t', 'producer': 'runner', 'role': 'runner', 'payload': '{}', 'tenant': 'torre',
        'key': live_image.KEYS['runner'], 'digest': DIGEST, 'version': 1}),
    ('live_image.RELOAD_SAY', live_image.RELOAD_SAY, {
        'id': 'platform.deploy.image_reload:t', 'producer': 'runner', 'role': 'runner', 'payload': '{}', 'wrote_at': None,
        'started_at': None}),
    ('status.image_reload', "select payload::text from log.event where type = 'platform.deploy.image_reload' and "
     "tenant_id is null and occurred_at > now() - interval '30 days' order by occurred_at desc limit 20", {}),
    # RELOAD-WITHOUT-STANDBY: a landing with no standby pair: the look's order and its end, and the tasks' read (half a
    # second apart while an order is open, never on a pass with none), claim and word, by the same indexes
    ('autodeploy.ORDER', autodeploy.ORDER, {'id': 'platform.deploy.image_reload:order:t', 'digest': DIGEST, 'settle_s': 600,
                                            'landed_at': time.time(), 'payload': '{}'}),
    ('autodeploy.ORDER_DONE', autodeploy.ORDER_DONE, {
        'order': 'platform.deploy.image_reload:order:t', 'id': 'platform.deploy.image_reload:done:t', 'head': 't',
        'digest': DIGEST, 'tenant': 'torre', 'newest': True, 'roles': 2, 'payload': '{}'}),
    # FAST-PATH-RELOAD: the build's start the port records and the look's read of it
    ('autodeploy.STARTED', autodeploy.STARTED, {}),
    ('live_image.ORDER_OF', live_image.ORDER_OF, {'tenant': 'torre', 'head': ''}),
    ('live_image.ORDER_START', live_image.ORDER_START, {
        'id': 'platform.deploy.image_reload:t', 'producer': 'runner', 'role': 'runner', 'payload': '{}',
        'order': 'platform.deploy.image_reload:order:t', 'tenant': 'torre', 'key': live_image.KEYS['runner'], 'digest': DIGEST}),
    ('live_image.ORDER_SAY', live_image.ORDER_SAY, {'id': 'platform.deploy.image_reload:t', 'producer': 'runner',
                                                    'role': 'runner', 'payload': '{}'}),
    ('config_data.OBSERVE', config_data.OBSERVE, {'id': 'platform.config.observed:t', 'name': 'k', 'version': 1,
                                                  'tenant': 'torre', 'payload': '{}', 'value': '1'}),
    ('http_port.BUILD_ENDED', http_port.BUILD_ENDED, {'id': 'platform.deploy.ended:t', 'payload': '{}'}),
    ('http_port.BUILD_STARTED', http_port.BUILD_STARTED, {'id': 'platform.deploy.started:t', 'payload': '{}'}),
    ('forge_webhooks.LATEST_KEYS', forge_webhooks.LATEST_KEYS, {}),
    ('runner.TAKE', runner.TAKE, {'adapter': 'container', 'runner': 't'}),
    ('work.reap', "select * from work.job where lease_run_id is not null and lease_expires_at < clock_timestamp() "
     "order by lease_expires_at for update skip locked", {}),
    ('work.wake_held', "select * from work.job where state = 'waiting' and lease_run_id is null and wait_reason is not null "
     "order by id for update skip locked", {}),
    ('mechanisms.QUEUES', mechanisms.QUEUES, {}),
    # QUEUE-SWAP: the merge queue's want, the landing's swap and what the looks read of it after
    ('queue_deploy.WANT', queue_deploy.WANT, {'id': 'platform.deploy.successor:t', 'payload': '{}'}),
    ('queue_deploy.WANTED', queue_deploy.WANTED, {}),
    ('queue_deploy.SWAP', queue_deploy.SWAP, {'digest': DIGEST, 'tenant': 'torre', 'fresh_s': 3.0, 'reason': 'r',
                                              'id': 'platform.deploy.image_swap:t', 'payload': '{}'}),
    ('queue_deploy.SWAP_OF', queue_deploy.SWAP_OF, {'head': DIGEST, 'digest': DIGEST}),
    ('queue_deploy.ADOPTED', queue_deploy.ADOPTED, {}),
]
# the idempotency checks by event_id: the primary key leads with occurred_at, so reaching them by it reads the whole index
BY_ID = ('port.LANDED_SWAP', 'port.LANDED_ONLY', 'autodeploy.OBSERVE', 'autodeploy.SWAP_OF',
         'live_image.LIVE', 'config_data.OBSERVE', 'http_port.BUILD_ENDED', 'live_image.RELOAD_OF', 'live_image.RELOAD_SAY',
         'canary.READ', 'canary.SETTLE', 'autodeploy.ORDER', 'autodeploy.ORDER_DONE', 'live_image.ORDER_START',
         'live_image.ORDER_SAY', 'http_port.BUILD_STARTED', 'queue_deploy.WANT', 'queue_deploy.SWAP')
FILL = f"""
insert into work.tenant (name) values ('torre');
insert into work.executor (name, adapter) values ('runner', 'container');
insert into work.capacity (executor, account, slots) values ('runner', 'default', 4);
insert into work.queue (tenant_id, name) select id, 'checks' from work.tenant;
insert into work.job (tenant_id, queue, executor, input_uri, input_digest, state, attempts)
  select t.id, 'checks', 'runner', 'forge://x/' || g, md5(g::text), 'succeeded', 1 from work.tenant t,
  generate_series(1, {JOBS}) g;
insert into work.run (job_id, n, executor, account, state, outcome)
  select id, 1, 'runner', 'default', 'ended', 'succeeded' from work.job;
insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  select k.type || ':' || g, null, k.type, now() - (now() - date_trunc('month', now())) * g / {EVENTS + 1}, 'test', 'job/x',
         jsonb_build_object('n', g, 'filler', repeat('x', 200))
  from generate_series(1, {EVENTS}) g
  join (select row_number() over () - 1 as i, type from unnest(%(types)s::text[]) type) k
    on k.i = case when g % 100 = 0 then {len(COMMON)} + (g / 100) % {len(RARE)} else g % {len(COMMON)} end;
analyze;
"""


def render(sql, params):
    return PLACEHOLDER.sub(lambda found: literal(params[found.group(1)]), sql)


def scans(node):
    """(node type, relation, index) of every node of a JSON plan."""
    yield node['Node Type'], node.get('Relation Name'), node.get('Index Name') or ''
    for child in node.get('Plans', []):
        yield from scans(child)


@unittest.skipUnless(URL, 'TEST_DATABASE_URL is not set')
class OnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name, cls.db = migrated(URL)
        types = '{' + ','.join(COMMON + RARE) + '}'
        cls.db.run(render(FILL, {'types': types}))
        cls.month = cls.db.rows("select 'event_' || to_char(now(), 'YYYY_MM')")[0][0]

    @classmethod
    def tearDownClass(cls):
        test_db.destroy(URL, cls.name)

    def plan(self, sql):
        out = self.db.call(['-A', '-t', '-c', f'explain (format json) {sql}'])
        return list(scans(json.loads(out)[0]['Plan']))

    def test_no_statement_of_the_swap_scans_the_log_or_the_work_tables(self):
        big = {self.month, 'run', 'job'}  # the partition of now (the live log's whole month) and the work tables
        for name, sql, params in SWAP_MOMENT:
            with self.subTest(statement=name):
                plan = self.plan(render(sql, params))
                found = {relation for kind, relation, _ in plan if kind == 'Seq Scan'}
                self.assertFalse(big & found, f'{name} scans {sorted(big & found)}')
                if name in BY_ID:
                    keyed = [index for _, relation, index in plan if relation == self.month and index.endswith('_pkey')]
                    self.assertFalse(keyed, f'{name} looks its event_id up by {keyed}')

    def test_every_partition_of_the_log_has_both_indexes_and_a_new_one_gets_them(self):
        self.db.run("create table log.event_2099_01 partition of log.event for values from ('2099-01-01') to ('2099-02-01')")
        found = self.db.rows("select c.relname, string_agg(pg_get_indexdef(i.indexrelid), ' ; ') from pg_inherits h "
                             "join pg_class c on c.oid = h.inhrelid join pg_index i on i.indrelid = c.oid "
                             "where h.inhparent = 'log.event'::regclass group by c.relname")
        self.assertIn('event_2099_01', dict(found))
        for partition, definitions in found:
            with self.subTest(partition=partition):
                self.assertIn('(type, occurred_at)', definitions)
                self.assertIn('(event_id)', definitions)

    def test_the_migration_is_additive_and_names_the_unit(self):
        sql = MIGRATION.read_text(encoding='utf-8')
        self.assertIn('IMAGE-SWAP-DB-LOAD', sql)
        statements = [line for line in sql.splitlines() if line and not line.startswith('--')]
        self.assertTrue(all(line.startswith('create index if not exists ') for line in statements), statements)


if __name__ == '__main__':
    unittest.main()
