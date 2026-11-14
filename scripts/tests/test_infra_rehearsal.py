"""FIRST-JOB-REHEARSED (tower_infra.rehearsal): a job of no one through a real job's whole path, in a transaction that is
rolled back, so the first job after a swap finds every statement of its path already run on its backend.

On a throwaway database of the toolchain's PostgreSQL migrated by the service's runner (TI1), with the world of the
mechanisms' test (two tenants, their executors, capacities and queues). The rehearsal runs on one psql session kept open
inside a transaction, the way the warm-up's cursor gives it one (live_image.Warm.step); a second connection plays the
live dispatcher and the live runner beside it, with a lock timeout: waiting for a lock of the rehearsal is a failure.
Local PostgreSQL only, no network.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db import psql  # noqa: E402
import test_db  # noqa: E402
from test_infra_mechanisms import LIVRE, TORRE, World  # noqa: E402
from tower_infra import canary, mechanisms, rehearsal, runner  # noqa: E402

END = '__the_statement_ended__'
EVENTS = ("select e.type, e.payload->>'rehearsal' from log.event e join work.tenant t on t.id = e.tenant_id "
          "where t.name like 'rehearsal-%' order by e.occurred_at, e.type")
LEFT = ("select (select count(*) from work.tenant where name like 'rehearsal-%'), "
        "(select count(*) from work.queue where name like 'rehearsal-%'), "
        "(select count(*) from work.executor where name like 'rehearsal-%'), "
        "(select count(*) from work.capacity where executor like 'rehearsal-%'), "
        "(select count(*) from work.job where queue like 'rehearsal-%'), "
        "(select count(*) from work.run where executor like 'rehearsal-%'), "
        "(select count(*) from log.event where payload ? 'rehearsal' or producer like 'rehearsal-%')")


class Session:
    """One psql process kept open: rows(sql, params) on one connection, so a transaction lasts from a call to the next
    (infra_db.psql.Psql is a process per statement). The shape rehearsal.Rows gives over a psycopg cursor."""

    def __init__(self, url):
        self.process = subprocess.Popen(
            [str(test_db.psql_binary()), url, '-X', '-q', '-A', '-t', '-F', psql.SEPARATOR, '-P', f'null={psql.NULL}',
             '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def rows(self, sql, params=None):
        sql = psql.PLACEHOLDER.sub(lambda found: psql.literal((params or {})[found.group(1)]), sql)
        self.process.stdin.write(f'{sql.rstrip().rstrip(";")};\n\\echo {END}\n')
        self.process.stdin.flush()
        lines = []
        while True:
            line = self.process.stdout.readline()
            if not line:  # psql stopped at the statement's error
                said = self.process.stderr.read()
                found = psql.SQLSTATE.search(said)
                raise psql.DatabaseError(said.strip(), found.group(1) if found else None)
            if line.rstrip('\n') == END:
                break
            lines.append(line.rstrip('\n'))
        return [tuple(None if cell == psql.NULL else cell for cell in line.split(psql.SEPARATOR)) for line in lines if line]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        for pipe in (self.process.stdout, self.process.stderr):
            pipe.close()


class Rehearsed(World):
    def setUp(self):
        super().setUp()
        self.session = Session(self.db.url)
        self.addCleanup(self.session.close)
        # the live dispatcher and the live runner beside the rehearsal: a lock of it that they wait for is a refusal
        self.live = psql.Psql(self.db.url + '?options=-c%20lock_timeout%3D3000')

    def test_the_job_goes_through_a_real_job_s_whole_path_and_nothing_of_it_is_left(self):
        before = self.db.rows('select count(*) from log.event')[0][0]
        self.session.rows('begin')
        parts = rehearsal.job(self.session, 'service', mark='one')
        self.assertEqual(sorted(parts), ['create_s', 'dispatch_s', 'end_s', 'take_s'])
        self.assertTrue(all(isinstance(each, float) and each >= 0 for each in parts.values()), parts)
        # inside its transaction: every transition of a real job, by the functions the roles themselves call
        self.assertEqual(self.session.rows(EVENTS), [('job.created', 'service'), ('run.started', None), ('run.running', None),
                                                     ('run.usage', None), ('run.ended', None)])
        self.assertEqual(self.session.rows(
            "select j.state, j.result->>'exit', r.state, r.outcome, c.in_use::text, e.adapter, t.name "
            "from work.job j join work.run r on r.job_id = j.id join work.capacity c on c.executor = r.executor "
            "join work.executor e on e.name = r.executor join work.tenant t on t.id = e.tenant_id "
            "where j.queue = 'rehearsal-one'"),
            [('succeeded', '0', 'ended', 'succeeded', '0', 'rehearsal-one', 'rehearsal-one')])
        self.assertEqual(self.db.rows(LEFT), [('0',) * 7])  # nobody else sees any of it while it runs
        self.session.rows('rollback')
        self.assertEqual(self.session.rows(LEFT), [('0',) * 7])  # and nothing of it is left: not a row, not an event
        self.assertEqual(self.db.rows('select count(*) from log.event')[0][0], before)

    def test_it_takes_no_real_job_and_no_real_run_that_wait_beside_it(self):
        ahead = self.job('a-check', selector={'adapter': 'container'})  # queued before the rehearsal, never dispatched by it
        handed = self.job('handed', selector={'adapter': 'container'}, queue='ranked', rank='9')
        tenants = dict(self.db.rows('select name, id::text from work.tenant'))
        claimed = mechanisms.dispatch_one(self.db, tenants['torre'], 'ranked', '5 minutes', '50')  # a run no runner took yet
        self.assertEqual(claimed['job'], handed)
        self.session.rows('begin')
        rehearsal.job(self.session, 'runner', mark='two')
        self.assertEqual(self.session.rows(
            "select j.idempotency_key, j.state, coalesce(r.state, '') from work.job j left join work.run r "
            "on r.job_id = j.id where j.idempotency_key in ('a-check', 'handed') order by 1"),
            [('a-check', 'queued', ''), ('handed', 'running', 'starting')])  # as they were: not claimed, not taken
        self.session.rows('rollback')
        self.assertEqual((self.state(ahead), self.state(handed)), ('queued', 'running'))

    def test_a_live_dispatcher_and_a_live_runner_work_beside_it_and_wait_for_no_lock_of_it(self):
        self.session.rows('begin')
        rehearsal.job(self.session, 'service', mark='three')  # open: its rows are written and locked, nothing is committed
        check = self.job('a-check', selector={'adapter': 'container'})
        made = mechanisms.dispatch(self.live)  # every queue with queued work: the rehearsal's is not one it sees
        self.assertEqual([(got['job'], got['executor']) for got in made], [(check, 'script-runner')])
        taken = runner.take(self.live, 'container', 'the-live-runner')  # the next handed-over run: the check's
        self.assertEqual((taken['job'], taken['run']), (check, made[0]['run']))
        self.assertTrue(mechanisms.relay(self.live, taken['run'], taken['fence'], 'run.usage', {'meter': 'cpu_s', 'quantity': 1}))
        self.assertEqual(mechanisms.end(self.live, taken['run'], taken['fence'], 'succeeded', result={'exit': 0}), 'succeeded')
        self.assertEqual(mechanisms.reap(self.live), [])  # and the reaper finds no lease of it to end
        self.session.rows('rollback')
        self.assertEqual((self.state(check), self.in_use('script-runner')), ('succeeded', '0'))

    def test_two_rehearsals_at_once_wait_for_nothing_of_each_other(self):
        # a runner's slots and the service rehearse at the same notification, each on its own connection
        other = Session(self.db.url + '?options=-c%20lock_timeout%3D3000')
        self.addCleanup(other.close)
        self.session.rows('begin')
        rehearsal.job(self.session, 'runner')
        other.rows('begin')
        rehearsal.job(other, 'runner')  # the first is still open
        other.rows('rollback')
        self.session.rows('rollback')
        self.assertEqual(self.db.rows(LEFT), [('0',) * 7])

    def test_the_service_also_makes_and_reads_a_canary_that_no_one_sees_and_that_is_never_dispatched(self):
        # FIRST-JOB-AT-ONCE: what the service that takes the role does after its first tick (canary.settle), rehearsed
        canaries = ("select j.state, j.selector->>'adapter', t.name from work.job j join work.tenant t on t.id = j.tenant_id "
                    f"where j.idempotency_key = '{canary.PREFIX}rehearsal-four'")
        self.port('PUT', '/v1/queues/checks', TORRE, {'policy': 'rank'})  # gate-infra.check_queue, where a canary runs
        with mock.patch.dict(os.environ, {'TOWER_CONFIG_TENANT': 'torre'}):
            self.session.rows('begin')
            parts = rehearsal.job(self.session, 'service', mark='four', canary_of='torre')
            self.assertNotIn('canary_s', parts)  # a log with no head of the base: no canary is made, as after a swap
            self.session.rows('rollback')
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "('push-1', null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                         {'payload': json.dumps({'delivery': {'event': {'payload': {'refUpdates': [
                             {'ref': 'refs/heads/mod/roadmap-integration', 'after': 'c' * 40}]}}}})})
            self.session.rows('begin')
            parts = rehearsal.job(self.session, 'service', mark='four', canary_of='torre')
            self.assertGreaterEqual(parts['canary_s'], 0)
            self.assertEqual(self.session.rows(canaries), [('queued', 'container', 'torre')])  # made and read, not dispatched
            self.assertEqual(self.db.rows(canaries), [])  # and seen by no one else: the live dispatcher has nothing of it
            self.assertEqual(mechanisms.dispatch(self.live), [])
            self.session.rows('rollback')
        self.assertEqual(self.db.rows(canaries), [])
        self.assertEqual(self.db.rows(LEFT), [('0',) * 7])
        self.assertEqual(self.db.rows("select count(*) from work.capacity where account = 'canary'"), [('0',)])  # nor its slot

    def test_another_tenants_queue_of_the_same_world_is_untouched(self):
        waiting = self.job('theirs', LIVRE, deadline='2100-01-01T00:00:00Z', executor='pessoa')
        self.session.rows('begin')
        rehearsal.job(self.session, 'service')
        self.session.rows('rollback')
        self.assertEqual((self.state(waiting), self.in_use('pessoa')), ('queued', '0'))


class AStepThatIsNotTheRealOne(unittest.TestCase):
    """A rehearsal that claimed nothing, took nothing or ended nothing says so: the warm-up logs it and goes on."""

    class Answers:
        def __init__(self):
            self.sent = []

        def rows(self, sql, params=None):
            self.sent.append(sql)
            return [('the-tenant', True)]

    def run_with(self, **patched):
        real = {'create_job': {'id': 'the-job', 'created': True},
                'dispatch_one': {'job': 'the-job', 'run': 'the-run', 'cached': False},
                'take': {'run': 'the-run', 'fence': 1}, 'relay': True, 'renew': 'running', 'end': 'succeeded'}
        real.update(patched)
        with mock.patch.object(rehearsal.port, 'create_job', return_value=real['create_job']), \
                mock.patch.object(mechanisms, 'dispatch_one', return_value=real['dispatch_one']), \
                mock.patch.object(runner, 'take', return_value=real['take']), \
                mock.patch.object(mechanisms, 'relay', return_value=real['relay']), \
                mock.patch.object(runner, 'renew', return_value=real['renew']), \
                mock.patch.object(mechanisms, 'end', return_value=real['end']):
            return rehearsal.job(self.Answers(), 'service', clock=iter(range(100)).__next__)

    def test_each_part_is_timed_from_the_end_of_the_one_before(self):
        self.assertEqual(self.run_with(), {'create_s': 1.0, 'dispatch_s': 1.0, 'take_s': 1.0, 'end_s': 1.0})

    def test_a_step_that_did_not_do_what_the_real_one_does_raises(self):
        for patched, step in (({'dispatch_one': None}, 'dispatch'),
                              ({'dispatch_one': {'job': 'another', 'run': 'the-run', 'cached': False}}, 'dispatch'),
                              ({'dispatch_one': {'job': 'the-job', 'cached': True}}, 'dispatch'),
                              ({'take': None}, 'take'), ({'take': {'run': 'another', 'fence': 1}}, 'take'),
                              ({'relay': False}, 'usage'), ({'renew': None}, 'renew'), ({'end': None}, 'end')):
            with self.assertRaises(rehearsal.Unrehearsed) as refused:
                self.run_with(**patched)
            self.assertTrue(str(refused.exception).startswith(step), (patched, str(refused.exception)))

    def test_its_names_are_a_tenant_s_and_drawn_for_each_call(self):
        first, second = self.Answers(), self.Answers()
        with mock.patch.object(rehearsal.port, 'create_job', side_effect=RuntimeError('far enough')) as made:
            for each in (first, second):
                with self.assertRaises(RuntimeError):
                    rehearsal.job(each, 'runner')
        names = [call.args[2]['queue'] for call in made.call_args_list]
        self.assertEqual(len(set(names)), 2)
        for name in names:
            self.assertRegex(name, r'^rehearsal-[0-9a-f]{16}$')
            self.assertRegex(name, r'^[a-z][a-z0-9-]{1,39}$')  # work.tenant's check


class TheCursorsRows(unittest.TestCase):
    def test_rows_over_a_cursor_never_commit_and_answer_nothing_for_a_statement_with_no_result(self):
        cursor = mock.Mock(description=None)
        self.assertEqual(rehearsal.Rows(cursor).rows('insert', {'a': 1}), [])
        cursor.execute.assert_called_once_with('insert', {'a': 1})
        cursor.fetchall.assert_not_called()
        cursor = mock.Mock(description=[('id',)], **{'fetchall.return_value': [('1',)]})
        self.assertEqual(rehearsal.Rows(cursor).rows('select'), [('1',)])
        self.assertEqual([name for name, _, _ in cursor.mock_calls], ['execute', 'fetchall'])  # no commit, no rollback


if __name__ == '__main__':
    if not os.environ.get('TEST_DATABASE_URL'):
        raise SystemExit('TEST_DATABASE_URL is not set (source scripts/cloud/env.sh)')
    unittest.main()
