"""The infrastructure's service (engine-infra-service; INFRA-SVC 1b, P3 F1).

Its migrations at start and its database init step run here on throwaway databases of the toolchain's PostgreSQL (TI1)
through psql, the same rows/run shape psycopg gives them in the image: a fresh database gets every migration once,
with the event that records it and the partitions of log.event for this month and the next; a second start applies
nothing; a migration that fails leaves nothing behind; the init step makes the IAM login idempotently. Migration 0006
wakes the dispatcher (tower_work) and the runner (tower_runs) only for the events that free work, and the wake waits
until a notification or the tick, drains a burst, and outlives a lost listener (INFRA-SVC 5). Local PostgreSQL only, no
network.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
import config  # noqa: E402
import test_db  # noqa: E402
from tower_infra import dbinit, migrations  # noqa: E402

MIGRATIONS = ROOT / 'infra/db/migrations'
URL = os.environ.get('TEST_DATABASE_URL', '')


class Psql:
    """rows/run through psql on one database: what the service does through psycopg."""

    def __init__(self, url):
        self.url = url

    def call(self, args, script=None):
        done = subprocess.run([str(test_db.psql_binary()), self.url, '-X', '-q', '-v', 'ON_ERROR_STOP=1', *args],
                              input=script, capture_output=True, text=True,
                              timeout=config.get('test-db.psql_timeout_s'), check=False)
        if done.returncode:
            raise RuntimeError(done.stderr.strip())
        return done.stdout

    def rows(self, sql):
        return [tuple(line.split('|')) for line in self.call(['-A', '-t', '-F', '|', '-c', sql]).splitlines() if line]

    def run(self, sql):
        self.call(['-1', '-f', '-'], script=sql)


class Throwaway(unittest.TestCase):
    """Each test gets a database of its own."""

    def setUp(self):
        self.name = test_db.create(URL)
        parts = urlsplit(URL)
        self.db = Psql(urlunsplit((parts.scheme, parts.netloc, '/' + self.name, '', '')))

    def tearDown(self):
        test_db.destroy(URL, self.name)

    def one(self, sql):
        return self.db.rows(sql)[0][0]


class MigrationTests(Throwaway):
    def test_a_fresh_database_gets_every_migration_once_with_the_event_that_records_it(self):
        self.assertEqual(migrations.migrate(self.db, MIGRATIONS, 'test'), [path.stem for path in
                                                                          migrations.migrations(MIGRATIONS)])
        self.assertEqual(self.one("select to_regclass('work.job') is not null and to_regclass('log.event') is not null"),
                         't')  # the schema itself is test_infra_db's
        recorded = self.db.rows("select payload->>'migration', payload->>'sha256' from log.event "
                                "where type = 'platform.migration.applied'")
        first = migrations.migrations(MIGRATIONS)[0]
        self.assertIn((first.stem, hashlib.sha256(first.read_bytes()).hexdigest()), recorded)

    def test_a_second_start_applies_nothing(self):
        migrations.migrate(self.db, MIGRATIONS, 'test')
        self.assertEqual(migrations.migrate(self.db, MIGRATIONS, 'test'), [])
        self.assertEqual(self.one("select count(*) = count(distinct event_id) from log.event "
                                  "where type = 'platform.migration.applied'"), 't')

    def test_the_partitions_of_this_month_and_the_next_exist(self):
        migrations.migrate(self.db, MIGRATIONS, 'test')
        self.assertEqual(self.one("select to_regclass('log.event_' || to_char(now(), 'YYYY_MM')) is not null and "
                                  "to_regclass('log.event_' || to_char(now() + interval '1 month', 'YYYY_MM')) "
                                  "is not null"), 't')

    def test_a_failing_migration_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in migrations.migrations(MIGRATIONS):
                shutil.copy(path, tmp)
            broken = Path(tmp) / '9999_broken.sql'
            broken.write_text('create table work.half_done (id int);\nselect 1 / 0;\n')
            with self.assertRaises(RuntimeError):
                migrations.migrate(self.db, tmp, 'test')
            self.assertEqual(self.one("select to_regclass('work.half_done') is null"), 't')
            self.assertNotIn(broken.stem, migrations.applied(self.db))
            broken.unlink()
            self.assertEqual(migrations.migrate(self.db, tmp, 'test'), [])

    def test_only_numbered_sql_files_are_migrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('0002_second.sql', '0001_first.sql', 'README.md', 'draft.sql', '01_short.sql'):
                (Path(tmp) / name).write_text('')
            self.assertEqual([path.name for path in migrations.migrations(tmp)], ['0001_first.sql', '0002_second.sql'])


NOTIFIED = re.compile(r'Asynchronous notification "(\w+)" with payload "([^"]+)"')


class WakeTests(Throwaway):
    """INFRA-SVC 5 (P6 F1, the 1 s path): migration 0006 wakes the dispatcher and the runner when work frees."""

    def test_the_database_wakes_the_dispatcher_and_the_runner_only_when_work_frees(self):
        migrations.migrate(self.db, MIGRATIONS, 'test')
        types = ('job.created', 'job.cancelled', 'run.started', 'run.ended', 'cache.hit', 'capacity.set',
                 'run.usage', 'run.running', 'forge.ping', 'platform.forge.keys')  # the last four free no work
        inserts = ''.join(f"insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                          f"values ('wake-{n}', null, '{kind}', clock_timestamp(), 'test', 'wake', '{{}}');\n"
                          for n, kind in enumerate(types))
        said = self.db.call(['-A', '-t', '-f', '-'], script=f'listen tower_work;\nlisten tower_runs;\n{inserts}select 1;\n')
        self.assertEqual(sorted(NOTIFIED.findall(said)),
                         sorted([('tower_work', kind) for kind in ('job.created', 'job.cancelled', 'run.ended',
                                                                    'cache.hit', 'capacity.set')]
                                + [('tower_runs', 'run.started'), ('tower_runs', 'job.cancelled')]))  # CANCEL-WAKES-RUNNER


class Listener:
    """A psycopg connection as the wake uses it: execute, autocommit, notifies(timeout, stop_after), close."""

    def __init__(self, pending=(), failure=None):
        self.pending, self.failure, self.autocommit, self.closed = list(pending), failure, False, False
        self.executed, self.timeouts = [], []

    def execute(self, sql):
        self.executed.append(sql)

    def notifies(self, timeout=None, stop_after=None):
        if self.failure:
            raise self.failure
        self.timeouts.append(timeout)
        while self.pending and (stop_after is None or stop_after > 0):
            yield self.pending.pop(0)
            stop_after = None if stop_after is None else stop_after - 1

    def close(self):
        self.closed = True


class ServeNames(unittest.TestCase):
    """The wake's listener never worked in production (08/11): `serve` built `Wake(lambda: connection(...))`, a closure that
    resolves the module's `connection()` when it runs, but the heartbeat's `with engine.connect() as connection` made
    `connection` a local of `serve`, so the call hit a SQLAlchemy Connection ('object is not callable') and every tick fell back
    to the 1 s wait. A local of `serve` must never share the name of a module-level function the closures call."""

    def test_no_local_of_serve_shadows_a_module_function(self):
        import ast
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8'))
        module_functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        serve = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'serve')
        local = {node.id for node in ast.walk(serve) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        self.assertEqual(sorted(local & module_functions), [])


class Wake(unittest.TestCase):
    def test_a_notification_wakes_the_wait_and_the_burst_with_it_is_one_pass(self):
        from tower_infra import wake
        listener = Listener(['run.ended', 'job.created', 'run.ended'])
        waits = wake.Wake(lambda: listener, wake.WORK, sleep=self.fail)
        self.assertTrue(waits.wait(float('0.5')))
        self.assertEqual((listener.executed, listener.autocommit, listener.pending), (['listen tower_work'], True, []))
        self.assertEqual(listener.timeouts, [float('0.5'), 0])  # waited, then drained without waiting
        self.assertFalse(waits.wait(float('0.5')))  # nothing came: the tick
        self.assertEqual(listener.executed, ['listen tower_work'])  # listened once

    def test_a_failed_listener_waits_the_tick_and_listens_again_next_time(self):
        from tower_infra import wake
        made, slept = [Listener(failure=OSError('the connection was lost')), Listener(['run.started'])], []
        listeners = list(made)
        waits = wake.Wake(lambda: listeners.pop(0), wake.RUNS, sleep=slept.append)
        with self.assertLogs('tower_infra.wake', 'WARNING'):
            self.assertFalse(waits.wait(float('0.5')))
        self.assertEqual((slept, made[0].closed), ([float('0.5')], True))
        self.assertTrue(waits.wait(float('0.5')))
        self.assertEqual(made[1].executed, ['listen tower_runs'])

    def test_only_the_channels_of_migration_0006_are_listened_to(self):
        from tower_infra import wake
        with self.assertRaises(ValueError):
            wake.Wake(lambda: Listener(), 'tower_work; drop table work.job')
        with self.assertRaises(ValueError):
            wake.Wake(lambda: Listener(), (wake.DEPLOY, 'tower_work; drop table work.job'))
        with self.assertRaises(ValueError):
            wake.Wake(lambda: Listener(), ())

    def test_one_listener_may_wake_on_several_channels(self):
        # IMAGE-PREWARM-B2: the prewarm wakes on a push (tower_deploy) and on its bundle job's end (tower_work)
        from tower_infra import wake
        listener = Listener(['run.ended'])
        self.assertTrue(wake.Wake(lambda: listener, (wake.DEPLOY, wake.WORK), sleep=self.fail).wait(float('0.5')))
        self.assertEqual(listener.executed, ['listen tower_deploy', 'listen tower_work'])


class InitTests(Throwaway):
    def setUp(self):
        super().setUp()
        self.role = self.name + '_login'  # unique as the throwaway database is
        self.db.run("do $$ begin if not exists (select 1 from pg_roles where rolname = 'rds_iam') then "
                    "create role rds_iam; end if; end $$;")

    def tearDown(self):
        try:
            self.db.run(f"do $$ begin if exists (select 1 from pg_roles where rolname = '{self.role}') then "
                        f"execute format('revoke all on database %I from %I', '{self.name}', '{self.role}'); "
                        f"execute format('drop role %I', '{self.role}'); end if; end $$;")
        finally:
            super().tearDown()

    def test_the_service_login_authenticates_by_iam_and_may_create_schemas(self):
        dbinit.init(self.db, self.name, self.role)
        dbinit.init(self.db, self.name, self.role)  # idempotent: a second start changes nothing
        self.assertEqual(self.db.rows(f"select rolcanlogin, pg_has_role('{self.role}', 'rds_iam', 'member'), "
                                      f"has_database_privilege('{self.role}', '{self.name}', 'create') "
                                      f"from pg_roles where rolname = '{self.role}'"), [('t', 't', 't')])

    def test_the_owner_s_step_creates_pg_proctab_where_the_database_offers_it_and_goes_on_where_it_does_not(self):
        """DB-HOST-VITALS: the host's memory, swap and load are read through pg_proctab's functions, and only the
        database's owner may create an extension: the init step does, when the engine offers it (RDS for PostgreSQL
        does; the toolchain's Postgres may not), and a database without it, or one that refuses, starts as before."""
        said = dbinit.statements('tower')
        self.assertIn("if exists (select 1 from pg_available_extensions where name = 'pg_proctab') then", said)
        self.assertIn('create extension if not exists pg_proctab;', said)
        self.assertIn('exception when others then', said)  # a refusal is a notice, never a task that cannot start
        dbinit.init(self.db, self.name, self.role)  # on this Postgres, whichever it is
        offered, created = self.db.rows("select exists (select 1 from pg_available_extensions where name = 'pg_proctab'), "
                                        "exists (select 1 from pg_extension where extname = 'pg_proctab')")[0]
        self.assertEqual(offered, created)

    def test_the_owner_s_step_lets_the_service_read_the_host_through_a_function_of_the_owner_s(self):
        """DB-HOST-VITALS, live 12/11 04:52 UTC: the owner's step created pg_proctab and the service's login got
        `permission denied for function pg_memusage`: RDS keeps the extension's functions from PUBLIC. The step now
        makes public.tower_host(), the owner's, security definer (the three functions' rows as one jsonb), for the
        service's role only; work.host_vitals() calls it (migration 0018). Stand-ins of the same names here, kept from
        PUBLIC as RDS keeps them."""
        if self.db.rows("select to_regproc('pg_memusage') is null")[0][0] != 't':
            self.skipTest('this Postgres has pg_proctab itself')
        dbinit.init(self.db, self.name, self.role)
        self.assertEqual(self.db.rows("select to_regprocedure('public.tower_host()') is null"), [('t',)])  # nothing to wrap
        self.db.run("""
            create function public.pg_memusage(out memused bigint, out memfree bigint, out swapused bigint)
              language sql as $$ select 900000::bigint, 31000::bigint, 412000::bigint $$;
            create function public.pg_loadavg(out load1 float4, out last_pid int) language sql as $$ select 3.25::float4, 7 $$;
            create function public.pg_cputime(out idle bigint, out iowait bigint) language sql as $$ select 900::bigint, 7::bigint $$;
            revoke all on function public.pg_memusage(), public.pg_loadavg(), public.pg_cputime() from public;
        """)
        dbinit.init(self.db, self.name, self.role)
        dbinit.init(self.db, self.name, self.role)  # idempotent
        try:
            self.the_owner_s_function()
        finally:
            self.db.run("drop function if exists public.tower_host()")  # the role's grant goes with it: the teardown drops the role

    def the_owner_s_function(self):
        self.assertEqual(self.db.rows(
            f"select has_function_privilege('{self.role}', 'public.pg_memusage()', 'execute'), "
            f"has_function_privilege('{self.role}', 'public.tower_host()', 'execute'), "
            "has_function_privilege('public', 'public.tower_host()', 'execute'), "
            "(select prosecdef from pg_proc where oid = 'public.tower_host()'::regprocedure)"), [('f', 't', 'f', 't')])
        said = self.db.call(['-A', '-t', '-c', f"set role {self.role}; select public.tower_host()::text"])
        first = json.loads(said.strip().splitlines()[-1])
        self.assertEqual({key: first[key] for key in ('mem', 'load', 'cpu')},
                         {'mem': {'memused': 900000, 'memfree': 31000, 'swapused': 412000},
                          'load': {'load1': 3.25, 'last_pid': 7}, 'cpu': {'idle': 900, 'iowait': 7}})
        # HOST-PROCS: with the process table too (pg_proctab()), who holds the memory, by what each connection is for
        # (the application name its backend has in pg_stat_activity; the process's own name for the rest), and the
        # settings that size the server's memory. A process table that cannot be read is said, and the rest stays
        self.assertEqual(json.loads(said.strip().splitlines()[-1]).get('procs_error'), 'function pg_proctab() does not exist')
        self.db.run("""
            create function public.pg_proctab(out pid int, out comm text, out rss bigint, out majflt bigint)
              returns setof record language sql as $$
                select pg_backend_pid(), 'postgres', 3000::bigint, 40::bigint
                union all select 1, 'rdsagent', 9000::bigint, 7::bigint union all select 2, 'rdsagent', 1000::bigint, 1::bigint $$;
            revoke all on function public.pg_proctab() from public;
        """)
        dbinit.init(self.db, self.name, self.role)
        said = json.loads(self.db.call(['-A', '-t', '-c', f"set role {self.role}; select public.tower_host()::text"])
                          .strip().splitlines()[-1])
        self.assertEqual(said['mem']['swapused'], 412000)
        self.assertEqual(said['procs'][0], {'who': 'rdsagent', 'n': 2, 'rss': 10000, 'rss_max': 9000, 'majflt': 8})
        self.assertEqual({key: said['procs'][1][key] for key in ('n', 'rss', 'majflt')}, {'n': 1, 'rss': 3000, 'majflt': 40})
        self.assertEqual(set(said['settings']), {'shared_buffers', 'jit', 'work_mem', 'max_connections', 'huge_pages'})

    def test_a_name_that_is_not_a_plain_identifier_is_refused(self):
        for database_name, role in (('tower; drop database tower', 'tower_service'), ('tower', 'Service"')):
            with self.assertRaises(ValueError):
                dbinit.statements(database_name, role)


SERVICE = ROOT / 'infra/service'
# What the service may import besides the standard library and itself (ARQUITETURA-ALVO §10.4: no module of the
# infrastructure imports one of management or an adapter): the orchestrator, the database driver, the AWS client and
# Claude's official SDK, which the provider's own guidance asks for (D-311; imported when a client is first made).
THIRD_PARTY = {'dbos', 'sqlalchemy', 'psycopg', 'boto3', 'botocore', 'anthropic'}


def imported(path):
    """The top-level modules a Python file imports; a relative import is the package itself."""
    import ast
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.add(node.module.split('.')[0])
    return names


class ImageTests(unittest.TestCase):
    def test_the_service_imports_no_module_of_management_or_of_an_adapter(self):
        for path in sorted((SERVICE / 'tower_infra').glob('*.py')):
            self.assertLessEqual(imported(path) - set(sys.stdlib_module_names), THIRD_PARTY, path.name)

    def test_its_database_steps_need_only_the_standard_library(self):
        # The gate imports them without the image's packages; the process and the engine take those packages lazily.
        for name in ('migrations.py', 'dbinit.py', 'port.py', 'http_port.py', 'mechanisms.py', 'forge.py',
                     'runner.py', 'subscriptions.py', 'sessions.py', 'cursor_agents.py', 'api_sessions.py',
                     'openai_chat.py', 'gemini_api.py', 'api_providers.py', 'ed25519.py', 'forge_webhooks.py',
                     'ingress.py', 'awsjson.py', 'webhook_consumer.py', '__init__.py'):
            self.assertLessEqual(imported(SERVICE / 'tower_infra' / name), set(sys.stdlib_module_names), name)

    def test_the_image_is_pinned_carries_the_migrations_and_runs_unprivileged(self):
        dockerfile = (SERVICE / 'Dockerfile').read_text(encoding='utf-8')
        self.assertRegex(dockerfile, r'(?m)^FROM public\.ecr\.aws/docker/library/python:[\d.]+-slim$')
        for needle in ('COPY infra/service/tower_infra /app/tower_infra', 'COPY infra/db/migrations /app/migrations',
                       'TOWER_MIGRATIONS=/app/migrations', 'USER nobody', 'ENTRYPOINT ["python", "-m", "tower_infra"]',
                       ' git xz-utils', 'chown nobody:nogroup /work'):  # the container executor's checkout and setup
            self.assertIn(needle, dockerfile)
        # INFRA-EXE 1f: the box's C compiler, which the gate's fork server builds its shim with (fork-server.test.sh)
        self.assertEqual(config.get('gate.fork_server_compiler'), 'cc')
        self.assertIn(' gcc libc6-dev ', dockerfile)
        wanted = [line for line in (SERVICE / 'requirements.txt').read_text(encoding='utf-8').splitlines()
                  if line.strip() and not line.startswith('#')]
        self.assertEqual({line.split('==')[0].split('[')[0] for line in wanted},
                         {'dbos', 'psycopg', 'boto3', 'awslambdaric', 'anthropic'})
        for line in wanted:
            self.assertRegex(line, r'^[a-z0-9-]+(\[[a-z]+\])?==\d+(\.\d+)+$')

    def test_one_workflow_per_run_registered_before_the_launch(self):
        # DBOS is not in the gate: these read the source. The run id is the workflow id, so a run reaches its executor
        # once across restarts (measured locally: a second start of the same id handed nothing over twice).
        workflows = (SERVICE / 'tower_infra' / 'workflows.py').read_text(encoding='utf-8')
        self.assertIn("with SetWorkflowID(run['run']):", workflows)
        self.assertIn('return None if adapter is None else adapter.start(run)', workflows)  # no adapter: no run
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        imported = re.search(r'from \. import [\w, ]*\bworkflows\b', main)
        self.assertLess(imported.start(), main.index('DBOS.launch()'))
        self.assertLess(main.index("workflows.register('forge'"), main.index('DBOS.launch()'))
        self.assertLess(main.index('DBOS.launch()'), main.index('workflows.tick(lease, '))

    def test_a_tick_comes_when_work_frees_and_an_idle_runner_wakes_when_a_run_starts(self):
        # INFRA-SVC 5: the loop's wait is the wake of tower_work (migration 0006), not a fixed tick; the runner's is
        # the wake of tower_runs. DB-LISTEN-ONE: both on the process's one listening connection (wake.Hub)
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        self.assertIn('woken = hub.wake(wake.WORK)', main)
        self.assertIn("        woken.wait(settings.get('service.dispatch_s'))", main)  # DEP9: the safety tick is a config value
        self.assertNotIn('stop.wait(tick)', main)
        self.assertIn('wait=hub.wake(wake.RUNS).wait', main)

    def test_the_session_adapter_registers_before_the_launch_and_every_tick_follows_its_runs(self):
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        loop = main[main.index('while not stop.is_set():'):main.index("LOG.info('serve: stopping')")]
        self.assertIn('followed.follow(db)', loop)
        self.assertLess(main.index("workflows.register('session', followed)"), main.index('DBOS.launch()'))
        self.assertIn("providers = {'cursor': cursor_agents.CursorAgents(parameter(", main)  # its key when used
        self.assertIn("api_providers.allowed(os.environ.get('TOWER_API_MODELS'))", main)  # D-311: only named models
        self.assertIn("providers.update(api_providers.providers(models, lambda name: parameter(f'/tower/sessions/{name}')",
                      main)

    def test_the_service_refreshes_the_forges_webhook_keys_and_a_failure_never_stops_the_tick(self):
        # P4 F2b: the port's Lambda has no route to Origin's JWKS (D-309); the service records the keys in the log.
        # GATE-SHUTDOWN: only under service.gate_looks (the ingress that verified with them is gone, PR #17)
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        loop = main[main.index('while not stop.is_set():'):main.index("LOG.info('serve: stopping')")]
        self.assertIn('refresh_keys(forge_webhooks, workflows)', loop)
        self.assertIn("if gate_looks and (last_keys is None or now - last_keys >= settings.get('service.forge_keys_every_s')):",
                      loop)
        helper = main[main.index('def refresh_keys('):main.index('def serve():')]
        self.assertIn('forge_webhooks.refresh(db', helper)
        self.assertIn('except Exception', helper)

    def test_every_tick_delivers_the_logs_subscriptions(self):
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        loop = main[main.index('while not stop.is_set():'):main.index("LOG.info('serve: stopping')")]
        self.assertIn('deliver(engine, sinks)', loop)
        self.assertLess(main.index('sinks = subscriptions.Sinks('), main.index('DBOS.launch()'))

    def test_the_runner_reads_its_keys_when_used_and_beats_for_its_health_check(self):
        main = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        start = main.index('def run_container():')
        body = main[start:main.index('\ndef ', start + 1)]
        for needle in ("parameter(os.environ.get('TOWER_FORGE_KEY_PARAMETER'))",  # ORIGIN-ACCESS-GONE: no default
                       "'/tower/runner/signing-key'", 'checkout_of=box.checkout_of',
                       'beat=lambda: health_file().touch()', 'runner.serve_all(workers, stop'):
            self.assertIn(needle, body)
        # INFRA-EXE 1e: TOWER_RUNNER_SLOTS slots, each with its own checkout, connection and wake
        slots = body[body.index("for slot in range(max(1, int(number('TOWER_RUNNER_SLOTS', 1))) + 1)"):]
        for needle in ('slot=slot', 'container.Reconnecting(kept, database.Database)', 'hub.wake(wake.RUNS)'):
            self.assertIn(needle, slots)
        self.assertIn("if command == 'run-container':", main)

    def health(self, path, fresh=None):
        environ = dict(os.environ, TOWER_HEALTH_FILE=str(path), PYTHONPATH=str(SERVICE))
        if fresh is not None:
            environ['TOWER_HEALTH_FRESH_S'] = fresh
        return subprocess.run([sys.executable, '-m', 'tower_infra', 'healthy'], env=environ, cwd=str(SERVICE),
                              capture_output=True, text=True, check=False).returncode

    def shell(self, path, fresh=None):
        """ROLLOUT-PARTS: the containers' own check (CMD-SHELL of 30-service.json and 50-runner.json), run by sh."""
        commands = set()
        for name in ('30-service.json', '50-runner.json'):
            template = json.loads((ROOT / 'infra' / 'aws' / 'stacks' / name).read_text())
            for resource in template['Resources'].values():
                for container in (resource.get('Properties') or {}).get('ContainerDefinitions') or []:
                    if container.get('HealthCheck'):
                        commands.add(tuple(container['HealthCheck']['Command']))
        self.assertEqual(len(commands), 1)  # one rule for every role
        [(kind, command)] = commands
        self.assertEqual(kind, 'CMD-SHELL')
        environ = dict(os.environ, TOWER_HEALTH_FILE=str(path))
        environ.pop('TOWER_HEALTH_FRESH_S', None)
        if fresh is not None:
            environ['TOWER_HEALTH_FRESH_S'] = fresh
        return 0 if subprocess.run(['sh', '-c', command], env=environ, check=False).returncode == 0 else 1

    def test_the_containers_check_in_the_shell_is_the_same_rule_as_the_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            beat = Path(tmp) / 'healthy'
            for check in (self.health, self.shell):
                self.assertEqual(check(beat), 1, check.__name__)  # no beat yet
            beat.touch()
            for check in (self.health, self.shell):
                self.assertEqual(check(beat), 0, check.__name__)
                self.assertEqual(check(beat, fresh='0'), 1, check.__name__)
            os.utime(beat, (beat.stat().st_atime - 200, beat.stat().st_mtime - 200))
            for check in (self.health, self.shell):
                self.assertEqual(check(beat), 1, check.__name__)  # older than the default 120 s

    def test_the_health_check_passes_only_while_the_last_beat_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            beat = Path(tmp) / 'healthy'
            self.assertEqual(self.health(beat), 1)  # no beat yet
            beat.touch()
            self.assertEqual(self.health(beat), 0)
            self.assertEqual(self.health(beat, fresh='0'), 1)  # every beat is too old for a window of nothing

    def test_where_the_database_is_comes_from_the_task_definition(self):
        from tower_infra import database
        where = database.settings({'TOWER_DB_HOST': 'tower-data.internal', 'TOWER_DB_PORT': '5432',
                                   'TOWER_DB_NAME': 'tower', 'AWS_REGION': 'region-of-the-stack'})
        self.assertEqual((where['host'], where['name'], where['region'], where['sslmode']),
                         ('tower-data.internal', 'tower', 'region-of-the-stack', 'require'))
        self.assertIsInstance(where['port'], int)

    def test_every_connection_says_who_opened_it_and_what_for(self):
        # DB-LISTEN-ONE: application_name is tower-<role>:<purpose>, which platform.db.vitals counts by (peak_by_app)
        from unittest import mock
        from tower_infra import __main__ as main, database, http_port
        environ = {'TOWER_DB_HOST': 'h', 'TOWER_DB_PORT': '5432', 'TOWER_DB_NAME': 'tower', 'AWS_REGION': 'r',
                   'AWS_ACCESS_KEY_ID': 'key', 'AWS_SECRET_ACCESS_KEY': 'secret'}
        asked = []
        psycopg = mock.Mock(connect=lambda **options: asked.append(options) or mock.Mock(closed=False))
        with mock.patch.dict(sys.modules, {'psycopg': psycopg}), mock.patch.dict(os.environ, environ):
            where = database.settings(role='runner')
            main.connection(database, where, 'tower_service', 'local', purpose='slot', autocommit=True)
            main.connection(database, where, 'tower_service', None, purpose='listen')  # by IAM token
            main.connection(database, database.settings(role='service'), 'tower_service', 'local')
            database.password_connection({name: where[name] for name in where if name != 'role'}, 'owner', 'local')
            with main.quick(database, database.settings(role='service'), 'tower_service', 'local')():
                pass
            lazy = http_port.lazy_database(role='consumer')
            lazy.connect()
            http_port.wake_of(http_port.lazy_database()).listening()  # a long poll's listener
        self.assertEqual([each['application_name'] for each in asked],
                         ['tower-runner:slot', 'tower-runner:listen', 'tower-service:other', 'tower-engine:other',
                          'tower-service:quick', 'tower-consumer:call', 'tower-port:wait'])
        self.assertNotIn('purpose', asked[0])  # libpq never sees it
        # PORT-LOGIN-PHASES: only the port's calls' connection says its login in parts; the others are the driver's own
        told = []
        with mock.patch.object(database, 'iam_connection', lambda where, user, **options: told.append(
                (where['role'], options['purpose'], options.get('phases') is not None))), mock.patch.dict(os.environ, environ):
            for role, purpose in (('port', 'call'), ('port', 'wait'), ('consumer', 'call')):
                http_port.lazy_database(role=role).connect(purpose=purpose)
        self.assertEqual(told, [('port', 'call', True), ('port', 'wait', False), ('consumer', 'call', False)])
        main_text = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
        for named in ("where = database.settings(role='service')", "where = database.settings(role='runner')",
                      "purpose='loop', autocommit=True)", "purpose='listen', **wake.KEEPALIVE)", "kept('gate')",
                      "def kept(purpose='slot'):", "purpose='warm')"):
            self.assertIn(named, main_text)
        engine = (SERVICE / 'tower_infra' / 'database.py').read_text(encoding='utf-8')
        self.assertIn("connect_args={'application_name': named(where, 'pool')}", engine)  # the pool's, and DBOS's

    def test_the_pool_hands_out_the_connection_that_came_back_last(self):
        # POOL-LIFO: in turns, every pooled statement went to the backend that had waited longest, and on a host that
        # pages that is the one paged out (live 12/11: the swap's record on a pooled connection, 365 ms)
        from unittest import mock
        from tower_infra import database
        made = {}

        class Engine:
            pass

        def create_engine(url, **options):
            made.update(url=url, **options)
            return Engine()
        sqlalchemy = mock.Mock(create_engine=create_engine)
        sqlalchemy.URL.create = lambda *args, **kwargs: ('url', args, kwargs)
        sqlalchemy.event.listens_for = lambda engine, name: (lambda function: made.update(listens=name) or function)
        with mock.patch.dict(sys.modules, {'sqlalchemy': sqlalchemy}):
            engine = database.iam_engine({'host': 'h', 'port': 5432, 'name': 'tower', 'sslmode': 'require', 'region': 'r',
                                          'role': 'service'}, 'tower_service', token=lambda: 'local')
        self.assertIsInstance(engine, Engine)
        self.assertIs(made['pool_use_lifo'], True)
        self.assertIs(made['pool_pre_ping'], True)  # as before: a connection that waited is checked before it is used
        self.assertEqual((made['connect_args'], made['listens']), ({'application_name': 'tower-service:pool'}, 'do_connect'))


STACKS = ROOT / 'infra/aws/stacks'
TARGET = ROOT / 'docs/arquitetura-referencia/ARQUITETURA-ALVO.md'


def load(path):
    import json
    return json.loads(path.read_text(encoding='utf-8'))


class StackTests(unittest.TestCase):
    """infra/aws/stacks/30-service.json: the task of P3 F1, the image the deployer built, and nothing more."""

    def setUp(self):
        self.template = load(STACKS / '30-service.json')
        self.resources = self.template['Resources']
        task = self.resources['TaskDefinition']['Properties']
        self.task = task
        self.containers = {container['Name']: container for container in task['ContainerDefinitions']}

    def default(self, name):
        return self.template['Parameters'][name]['Default']

    def statements(self, role):
        return [item for policy in self.resources[role]['Properties']['Policies']
                for item in policy['PolicyDocument']['Statement']]

    def test_the_task_is_the_a1_size_on_fargate_arm(self):
        # SERVICE-MEMORY (13/11): 1 GB, the 0.5 GB task killed out of memory (17:52 UTC); passed by parameters.json too
        # SERVICE-CPU (13/11, Daniel's 0.5 vCPU of 12/11 19:20 BRT): the landing's merge is the Origin CLI started on the
        # task's CPU (~0.3 CPU-s), forge_merge_s p99 7.15 s on 256 units; 512, the 1 GB kept
        self.assertIn('uma tarefa de 0,5 vCPU e 1 GB', TARGET.read_text(encoding='utf-8'))
        self.assertEqual((self.default('Cpu'), self.default('Memory')), ('512', '1024'))  # CPU units and MiB of ECS
        self.assertEqual(json.loads((ROOT / 'infra/aws/parameters.json').read_text())['service'], {'Cpu': '512', 'Memory': '1024'})
        self.assertEqual((self.task['Cpu'], self.task['Memory']), ({'Ref': 'Cpu'}, {'Ref': 'Memory'}))
        self.assertEqual(self.task['RuntimePlatform'], {'CpuArchitecture': 'ARM64', 'OperatingSystemFamily': 'LINUX'})
        self.assertEqual((self.task['RequiresCompatibilities'], self.task['NetworkMode']), (['FARGATE'], 'awsvpc'))

    def test_it_runs_in_the_public_subnets_with_the_tasks_group_and_no_inbound(self):
        network = self.resources['Service']['Properties']['NetworkConfiguration']['AwsvpcConfiguration']
        self.assertEqual(network['AssignPublicIp'], 'ENABLED')  # no NAT: the public IP reaches ECR and the logs
        self.assertEqual(network['Subnets'], {'Fn::Split': [',', {'Fn::ImportValue': 'tower-network-public-subnets'}]})
        self.assertEqual(network['SecurityGroups'], [{'Fn::ImportValue': 'tower-network-tasks-sg'}])
        exports = {output['Export']['Name'] for output in load(STACKS / '10-network.json')['Outputs'].values()}
        self.assertLessEqual({'tower-network-public-subnets', 'tower-network-tasks-sg'}, exports)

    def test_the_image_is_the_one_the_deployer_built_from_infra_service(self):
        image = self.template['Parameters']['Image']
        self.assertEqual((image['Type'], image['Default']),
                         ('AWS::SSM::Parameter::Value<String>', '/tower/deploy/image/service'))
        spec = load(ROOT / 'infra/aws/bootstrap.json')['Resources']['DeployProject']['Properties']['Source']['BuildSpec']
        self.assertIn('bash repo/infra/aws/deploy.sh', spec)  # DEP1: the images are built by the script it runs
        self.assertIn('/tower/deploy/image/$name', (ROOT / 'infra/aws/deploy.sh').read_text())
        self.assertTrue((SERVICE / 'Dockerfile').is_file())
        for container in self.containers.values():
            self.assertEqual(container['Image'], {'Ref': 'Image'}, container['Name'])

    def test_only_the_init_container_receives_the_owner_password(self):
        init, service = self.containers['init'], self.containers['service']
        self.assertEqual((init['Command'], init['Essential']), (['init'], False))
        self.assertEqual([secret['Name'] for secret in init['Secrets']], ['TOWER_DB_OWNER_PASSWORD'])
        self.assertIn('parameter/tower/db/master-password', str(init['Secrets'][0]['ValueFrom']))
        self.assertEqual((service['Command'], service['Essential']), (['serve'], True))
        # No secret at start: the forge's key is read when a landing runs, so a missing key never stops the task.
        self.assertNotIn('Secrets', service)
        self.assertFalse([item for item in service['Environment'] if 'PASSWORD' in item['Name']])
        self.assertEqual(service['DependsOn'], [{'ContainerName': 'init', 'Condition': 'SUCCESS'}])

    def test_the_init_container_logs_in_as_the_owner_the_data_stack_created(self):
        owner = next(item['Value'] for item in self.containers['init']['Environment'] if item['Name'] == 'TOWER_DB_OWNER')
        self.assertEqual(owner, load(STACKS / '20-data.json')['Resources']['Database']['Properties']['MasterUsername'])

    def test_the_service_container_finds_the_database_it_reads(self):
        from tower_infra import database
        source = (SERVICE / 'tower_infra' / 'database.py').read_text(encoding='utf-8')
        read = {name for name in ('TOWER_DB_HOST', 'TOWER_DB_PORT', 'TOWER_DB_NAME') if f"['{name}']" in source}
        self.assertTrue(read)
        given = {item['Name'] for item in self.containers['service']['Environment']}
        self.assertLessEqual(read, given)
        self.assertTrue(callable(database.settings))

    def test_every_container_names_its_region_for_the_iam_token(self):
        # The service and the init step ask boto3 for a token in the stack's region; the task says which, rather than
        # trusting the platform to set it.
        for container in self.containers.values():
            given = {item['Name']: item['Value'] for item in container['Environment']}
            self.assertEqual(given.get('AWS_REGION'), {'Ref': 'AWS::Region'}, container['Name'])

    def test_the_task_role_connects_as_the_service_login_reads_only_the_forge_key_and_publishes_to_tower_topics(self):
        statements = self.statements('TaskRole')
        self.assertEqual([item['Action'] for item in statements],
                         ['rds-db:connect', 'ssm:GetParameter', 'ssm:PutParameter', 'kms:Decrypt', 'sns:Publish',
                          'bedrock-mantle:CreateInference', 'bedrock:InvokeModel',
                          'lambda:InvokeFunction', 'ssm:GetParameter',
                          ['lambda:UpdateFunctionCode', 'lambda:PublishVersion', 'lambda:UpdateAlias', 'lambda:GetAlias',
                           'lambda:GetFunctionConfiguration', 'lambda:InvokeFunction'], 's3:GetObject',  # AUTO1: the doorbell; DEP8: the aliases
                          's3:PutObject',  # QUEUE-RELOAD: the code bundles it prepares
                          'ecs:RunTask', ['ecs:StopTask', 'ecs:DescribeTasks'], 'ecs:TagResource', 'iam:PassRole',  # IMAGE-PREWARM-B2
                          ['lambda:ListVersionsByFunction', 'lambda:ListAliases'], 'lambda:DeleteFunction', 's3:ListBucket',
                          's3:DeleteObject', 'ecs:DescribeServices', 'ecs:DescribeTaskDefinition'])  # LAMBDA-PRUNE
        # LAMBDA-PRUNE (the review's finding 26): a version is deleted by its qualified ARN only (never the function itself),
        # and only the packages under artifacts/lambda/ are listed and deleted
        listing, deleting, bucket, objects = statements[-6:-2]
        self.assertEqual([item['Fn::Sub'].rsplit(':function:', 1)[1] for item in listing['Resource']],
                         ['tower-port-api', 'tower-port-webhook-consumer', 'tower-port-ack-ingress'])
        self.assertEqual([item['Fn::Sub'].rsplit(':function:', 1)[1] for item in deleting['Resource']],
                         ['tower-port-api:*', 'tower-port-webhook-consumer:*', 'tower-port-ack-ingress:*'])
        self.assertEqual(bucket['Condition'], {'StringLike': {'s3:prefix': 'artifacts/lambda/*'}})
        self.assertTrue(objects['Resource']['Fn::Sub'].endswith('/artifacts/lambda/*'))
        # QUEUE-RELOAD: the service puts the code bundles it prepares, and nothing else of the bucket
        [put] = [item for item in statements if item['Action'] == 's3:PutObject']
        self.assertTrue(put['Resource']['Fn::Sub'].endswith('/artifacts/lambda/tower-code/*'))
        # GATE-SHUTDOWN: no statement publishes the forge's webhook keys (/tower/port/forge-keys): the ingress is gone
        database, key, write_back, decrypt, topics, claude, converse = statements[:7]
        self.assertEqual(claude['Resource'], '*')  # D-310: the model ARN of bedrock-mantle is not documented yet
        model, profile = converse['Resource']  # D-311: models and inference profiles only, never provisioned ones
        self.assertEqual((model['Fn::Sub'], profile['Fn::Sub']), ('arn:${AWS::Partition}:bedrock:*::foundation-model/*',
                                                       'arn:${AWS::Partition}:bedrock:*:${AWS::AccountId}:inference-profile/*'))
        self.assertEqual(topics['Resource'], {'Fn::Sub': 'arn:${AWS::Partition}:sns:${AWS::Region}:${AWS::AccountId}:tower-*'})
        # ORIGIN-ACCESS-GONE (15/11/2026): the Origin keys (/tower/origin/forge-key, factory-app-signing-key) are no
        # longer read: the sessions' keys alone, when used
        [session_keys] = key['Resource']
        self.assertEqual(key['Sid'], 'ReadTheSessionKeysWhenUsed')
        self.assertTrue(session_keys['Fn::Sub'].endswith(':parameter/tower/sessions/*'))
        self.assertNotIn('/tower/origin/', json.dumps(statements))
        # renewed OAuth credentials are written back: exactly the two CLI sessions, no wildcard (Daniel, through the Torre)
        self.assertEqual([item['Fn::Sub'].split(':parameter')[1] for item in write_back['Resource']],
                         ['/tower/sessions/claude-code', '/tower/sessions/codex'])
        self.assertNotIn('/tower/port/forge-keys', json.dumps(statements))
        self.assertIn('kms:ViaService', str(decrypt['Condition']))
        given = {item['Name']: item['Value'] for item in self.containers['service']['Environment']}
        self.assertNotIn('TOWER_FORGE_KEY_PARAMETER', given)  # ORIGIN-ACCESS-GONE
        self.assertNotIn('TOWER_ORIGIN_APP_KEY_PARAMETER', given)
        # D-310, D-311: the models an API provider may run; only the cheap ones of the test, on Bedrock. Haiku 5.5 waits on
        # AWS's release for the account (the Torre, 04/11 18:54 BRT); Haiku 4.5 answers through Converse meanwhile.
        self.assertEqual(json.loads(given['TOWER_API_MODELS']), {
            'bedrock': ['anthropic.claude-haiku-5-5', 'global.anthropic.claude-haiku-5-5', 'us.anthropic.claude-haiku-5-5'],
            'bedrock-converse': ['amazon.nova-micro-v1:0', 'us.amazon.nova-micro-v1:0',
                                 'us.anthropic.claude-haiku-4-5-20251001-v1:0']})
        arn, values = database['Resource']['Fn::Sub']
        self.assertTrue(arn.endswith(':dbuser:${Instance}/' + dbinit.SERVICE_ROLE))
        self.assertEqual(values, {'Instance': {'Fn::ImportValue': 'tower-data-resource-id'}})

    def test_the_execution_role_pulls_only_the_service_image_and_reads_only_the_owner_password(self):
        for item in self.statements('ExecutionRole'):
            actions = item['Action'] if isinstance(item['Action'], list) else [item['Action']]
            listed = item['Resource'] if isinstance(item['Resource'], list) else [item['Resource']]
            names = [value.get('Fn::Sub', str(value)) if isinstance(value, dict) else value for value in listed]
            if any(action.startswith('ecr:') and action != 'ecr:GetAuthorizationToken' for action in actions):
                self.assertEqual([name.rsplit(':', 1)[-1] for name in names], ['repository/tower-service'])
            if 'ssm:GetParameters' in actions:
                self.assertEqual([name.rsplit(':', 1)[-1] for name in names], ['parameter/tower/db/master-password'])
            if 'kms:Decrypt' in actions:
                self.assertIn('kms:ViaService', str(item['Condition']))

    def test_every_role_is_an_app_role_under_the_boundary(self):
        for name, resource in self.resources.items():
            if resource['Type'] == 'AWS::IAM::Role':
                self.assertTrue(resource['Properties']['RoleName'].startswith('tower-app-'), name)
                self.assertIn('policy/tower-boundary', str(resource['Properties']['PermissionsBoundary']), name)

    def test_a_task_that_stops_comes_back_and_a_failed_deploy_rolls_back(self):
        service = self.resources['Service']['Properties']
        self.assertEqual((service['DesiredCount'], self.default('DesiredCount')), ({'Ref': 'DesiredCount'}, 1))
        deployment = service['DeploymentConfiguration']
        # SERVICE-ROLLOUT-OVERLAP: the new task starts beside the old one and the old one stops once the new one is healthy:
        # the dispatcher never stops for a rollout (it did, MinimumHealthyPercent 0: the jobs made meanwhile waited 61 s at
        # p95). Two at once are safe: the migrations take an advisory lock, a claim is `for update skip locked`
        # (test_infra_two_dispatchers.py), and DBOS recovers only the workflows of its own version
        self.assertEqual((deployment['MinimumHealthyPercent'], str(deployment['MaximumPercent'])), (100, '200'))
        self.assertEqual(deployment['DeploymentCircuitBreaker'], {'Enable': True, 'Rollback': True})
        check = self.containers['service']['HealthCheck']
        # ROLLOUT-PARTS: the check is the health file's age in the shell (no interpreter started every pass on 0.25 vCPU),
        # every 10 s: a new task is HEALTHY about 20 s sooner, the old one stops then; the same 90 s of failed checks
        self.assertEqual(check['Command'][0], 'CMD-SHELL')
        self.assertEqual((check['Interval'], check['Interval'] * check['Retries'], check['StartPeriod']), (10, 90, 120))


if __name__ == '__main__':
    unittest.main()
