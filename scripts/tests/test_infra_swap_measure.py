"""SWAP-MEASURE (docs/operations/aws.md 22.9): a round of the image swap measured by command, through the landing's own
path. POST /v1/deploy/measure {drill} is one event; the live service's prewarm builds the published head's bundle with the
round's mark (scripts/gate-check artifact code --salt: the same code, another digest), wants its successor in each ECS
task, drills both roles when asked (SWAP-DRILL) and asks the delivery's readiness question once both are warm, swaps both
pointers by the autodeploy's statement once both rehearsed on it (armed, drilled), and ends the round once both roles
turned live and their ECS tasks took the bundle over. The autodeploy gives a round's pointers back as a landing's: after
the takeover, not on its next look (the published head was built before). scripts/medir: the official series from the
landing of #617 (every cut), by role and whole, the rounds apart; the landings before it labelled as before the cuts.

Hermetic but for OnPostgres (TEST_DATABASE_URL, skipped without), which runs the round on the real statements.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, canary, http_port, live_image, port, prewarm  # noqa: E402
import lambda_package  # noqa: E402
import medir  # noqa: E402
from test_infra_prewarm import Ecs, NETWORK, said, push  # noqa: E402
import test_infra_image_swap as image_swap  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE = 'b' * 40
S1, S2 = 'a' * 64, 'c' * 64


class Config:
    def __init__(self, intask=1):
        self.values = {'deploy.prewarm_max_tasks': 0, 'deploy.base_branch': 'mod/roadmap-integration',
                       'deploy.intask_standbys': intask, 'deploy.standby_fresh_s': 10}

    def get(self, name):
        return self.values[name]


class TheMarkedBundle(unittest.TestCase):
    def test_a_rounds_mark_is_the_same_code_under_another_digest_and_only_of_the_published_head(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'infra' / 'service' / 'tower_infra').mkdir(parents=True)
            (root / 'infra' / 'service' / 'tower_infra' / '__init__.py').write_text('')
            (root / 'infra' / 'db' / 'migrations').mkdir(parents=True)
            (root / 'infra' / 'db' / 'migrations' / '0001_x.sql').write_text('select 1;\n')
            (root / 'infra' / 'service' / 'requirements.txt').write_text('psycopg\n')
            plain, marked, again = (lambda_package.build_code(root, salt) for salt in (None, 'measure-1', 'measure-1'))
            other = lambda_package.build_code(root, 'measure-2')
            self.assertNotEqual(plain[1], marked[1])
            self.assertEqual(marked[1], again[1])  # the same round, the same bundle: its job may run again
            self.assertNotEqual(marked[1], other[1])
            import io
            import zipfile
            names = lambda data: set(zipfile.ZipFile(io.BytesIO(data)).namelist())  # noqa: E731
            self.assertEqual(names(marked[0]) - names(plain[0]), {f'{lambda_package.PACKAGE}/{lambda_package.SALT}'})
            refused = lambda_package.gate_code(root, BASE, '1' * 40, salt='measure-1')
            self.assertEqual(refused['code_only'], False)
            made = lambda_package.gate_code(root, BASE, BASE, salt='measure-1')
            self.assertEqual((made['code_only'], made['sha256'], made['published']), (True, marked[1], False))

    def test_the_gate_passes_the_mark_to_the_bundle(self):
        text = (ROOT / 'scripts' / 'gate-check').read_text()
        self.assertIn('--salt) salt=', text)
        self.assertIn('--salt "$salt"', text)


class TheRoute(unittest.TestCase):
    def test_the_route_is_the_canarys_measure(self):
        source = (ROOT / 'infra' / 'service' / 'tower_infra' / 'http_port.py').read_text()
        self.assertIn("('POST', r'/v1/deploy/measure', lambda db, who, body: canary.measure(db, who, body))", source)
        self.assertEqual(canary.MEASURE_EVENT, prewarm.MEASURE)
        self.assertLess(prewarm.MEASURE_LIMIT_S, canary.MEASURE_BUSY_S)  # the round fails before another may be asked


class Gate:
    def __init__(self, intask=True, strict=True, armed=False):
        self.role, self.digest, self.task, self.intask, self.strict, self.armed = 'service', S1, 't-1', intask, strict, armed
        self.sent_rows = []

    def sent(self, sql, params, db=None):
        self.sent_rows.append((sql, params))
        return []


class Db:
    def rows(self, sql, params=None):
        return []


class TheSuccessorSaysItsRehearsal(unittest.TestCase):
    def test_once_a_reading_with_whether_it_is_armed_and_only_a_successor_in_its_task(self):
        gate = Gate(armed=True)
        warm = live_image.Warm(gate, [])
        warm.say_rehearsed(3, Db())
        warm.say_rehearsed(3, Db())
        gate.armed = False
        warm.say_rehearsed(4, Db())
        said_ = [json.loads(params['payload']) for sql, params in gate.sent_rows]
        self.assertEqual([(each['state'], each['armed'], each['reads']) for each in said_],
                         [('rehearsed', True, 3), ('rehearsed', False, 4)])
        self.assertTrue(all(sql == live_image.UP for sql, _ in gate.sent_rows))
        for other in (Gate(intask=False), Gate(strict=False)):
            live_image.Warm(other, []).say_rehearsed(1, Db())
            self.assertEqual(other.sent_rows, [])


class TheCoverKeepsTheRoleOnly(unittest.TestCase):
    def test_the_looks_woken_with_the_swap_wait_while_the_process_covers_a_lost_successor(self):
        # COVER-NO-HOUSEKEEPING: the autodeploy's and the prewarm's looks (after_work) of the process that covers
        gate = live_image.Gate(lambda: None, 'service', S1, tenant='torre', task='t-1')
        gate.worked.set()
        checked = gate.after_work(lambda: True)
        self.assertIs(checked(), True)
        gate.covering = S1
        self.assertIs(checked(), False)
        gate.covering = None
        self.assertIs(checked(), True)


class TakeoverDb(image_swap.Db):
    took = ''

    def rows(self, sql, params=None):
        if sql == autodeploy.TAKEOVER:
            return [(S1, self.took, False)]
        return super().rows(sql, params)


class ThePointersGoBackAfterTheTakeover(image_swap.World):
    def test_a_rounds_swap_of_a_head_built_before_it_is_reconciled_only_once_both_tasks_took_it_over(self):
        self.db = TakeoverDb()
        self.watcher.scope = self.db.scope
        self.db.pointer = {key: image_swap.S for key in image_swap.KEYS}
        self.db.events.append((autodeploy.SWAP, {'digest': image_swap.S, 'head': image_swap.MERGE, 'by': 'measure',
                                                 'swapped': True, 'versions': {}}))
        self.db.live = {'runner', 'service'}
        self.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'succeeded', 'base_head': image_swap.MERGE,
                                                         'ended': 900, 'build_id': 'b:1'})
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: image_swap.S for key in image_swap.KEYS})  # still turning live
        self.db.took = 'runner'
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: image_swap.S for key in image_swap.KEYS})
        self.db.took = 'runner service'
        self.watcher.settle_image(self.db, self.heads)
        self.assertEqual(self.db.pointer, {key: '' for key in image_swap.KEYS})
        [retired] = [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']
        self.assertEqual(retired['by'], 'reconciled')


def status_of(*swaps, live=()):
    return {'image_swap': list(swaps), 'image_live': list(live)}


class TheSeries(unittest.TestCase):
    def test_by_role_and_whole_from_the_cuts_on_the_rounds_apart_and_the_landings_before_labelled(self):
        cut = medir.CUTS_AT
        versions = {'deploy.live_image_runner': 2, 'deploy.live_image_service': 2}
        swaps = [
            {'at': cut - 600, 'digest': 'd0', 'head': 'h0', 'swapped': True, 'landed_s': 0.1, 'versions': versions},
            {'at': cut + 4, 'digest': 'd1', 'head': 'h1', 'swapped': True, 'landed_s': 0.005, 'versions': versions,
             'by': 'landing', 'decide_s': 0.01},
            {'at': cut + 60, 'digest': 'd2', 'head': 'h1', 'swapped': True, 'landed_s': 0.004, 'versions': versions,
             'by': 'measure', 'drill': True},
            {'at': cut + 90, 'digest': 'd3', 'head': 'h1', 'swapped': True, 'landed_s': 0.006, 'versions': versions,
             'by': 'measure', 'drill': False}]
        live = [{'role': role, 'digest': digest, 'version': 2, 'swap_s': seconds} for digest, role, seconds in (
            ('d0', 'runner', 2.0), ('d0', 'service', 4.0), ('d1', 'runner', 0.07), ('d1', 'service', 0.43),
            ('d2', 'runner', 0.08), ('d2', 'service', 0.5), ('d3', 'runner', 0.02), ('d3', 'service', 0.2))]
        found = medir.from_deploy_status(status_of(*swaps, live=live))
        self.assertEqual(found['image_code_landing_before_cuts_s'], [4.1])
        self.assertEqual(sorted(found['image_code_landing_official_s']), [0.206, 0.445, 0.504])
        self.assertEqual(found['image_swap_runner_s'], [0.07, 0.08, 0.02])
        self.assertEqual(found['image_swap_service_s'], [0.43, 0.5, 0.2])
        self.assertEqual((found['image_measure_s'], found['image_measure_runner_s'], found['image_measure_service_s']),
                         ([0.504, 0.206], [0.08, 0.02], [0.5, 0.2]))
        self.assertEqual((found['image_measure_drilled_s'], found['image_measure_plain_s']), ([0.504], [0.206]))
        later = medir.from_deploy_status(status_of(*swaps, live=live), since=cut + 30)
        self.assertNotIn('image_code_landing_before_cuts_s', later)
        self.assertEqual(sorted(later['image_code_landing_official_s']), [0.206, 0.504])


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """A round on the real statements: the route, the job through port.create_job, the want, the drill, the readiness
    question, the swap of both pointers and the round's events, read back by a look that took the role over."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db
        self.tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        self.world.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'fifo'})
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                     "values ('push:base', %(tenant)s::uuid, 'forge.repository.pushed', clock_timestamp(), 'forge/origin', "
                     "'app/origin', %(payload)s::jsonb)", {'tenant': self.tenant, 'payload': json.dumps(
                         {'delivery': {'event': {'payload': push('mod/roadmap-integration', BASE)[1]}}})})

    def watcher(self, **config):
        return prewarm.Prewarm(live_image.kept(self.db), Ecs(), 'tower', NETWORK, config=Config(**config))

    def states(self):
        return [state for (state,) in self.db.rows(
            "select payload->>'state' from log.event where type = 'platform.deploy.measure' order by occurred_at")]

    def successor(self, role, sha, state, **more):
        self.db.rows(live_image.UP, {'id': f'{live_image.SUCCESSOR}:{role}:{sha}:t:{state}:{json.dumps(more)}',
                                     'producer': f'tower-{role}', 'role': role, 'payload': json.dumps(
                                         {'role': role, 'digest': sha, 'task': 't', 'state': state, **more})})

    def beat(self, sha):
        for role in ('runner', 'service'):
            self.db.rows("insert into work.standby_beat (role, digest, task) values (%(role)s, %(digest)s, 't') "
                         "on conflict (role, digest, task) do update set beat_at = clock_timestamp()",
                         {'role': role, 'digest': sha})

    def built(self, watcher, sha):
        watcher.step()
        [(job, command, key)] = self.db.rows(
            "select id::text, input_uri, idempotency_key from work.job where idempotency_key like 'prewarm:code:%%+measure-%%' "
            "and state = 'queued'")
        self.db.rows("update work.job set state = 'succeeded', result = %(result)s::jsonb where id = %(id)s::uuid",
                     {'id': job, 'result': said(sha)})
        watcher.step()  # built
        watcher.step()  # wanted
        return command, key

    def turned(self, sha):
        for role in ('runner', 'service'):
            for kind, state in (('platform.deploy.image_live', None), ('platform.deploy.image_reload', 'reloaded')):
                self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                             "values (%(id)s, null, %(type)s, clock_timestamp(), 'tower-x', 'deploy/image', %(payload)s::jsonb)",
                             {'id': f'{kind}:{role}:{sha}', 'type': kind, 'payload': json.dumps(
                                 {'role': role, 'digest': sha, **({'state': state} if state else {})})})

    def pointers(self):
        return {key: json.loads(self.db.rows(live_image.READ, {'tenant': 'torre', 'key': key})[0][0])
                for key in live_image.KEYS.values()}

    def test_a_drilled_round_swaps_both_pointers_once_both_successors_rehearsed_armed_and_ends_where_a_landing_does(self):
        asked = self.world.port('POST', '/v1/deploy/measure', 'installation', {'drill': True})
        self.assertEqual((asked['state'], asked['drill']), ('asked', True))
        with self.assertRaises(port.PortError) as busy:  # one round at a time
            canary.measure(self.db, ('installation', None), {})
        self.assertEqual(busy.exception.status, 409)
        watcher = self.watcher()
        command, key = self.built(watcher, S1)
        from tower_infra import forge
        salt = f"measure-{asked['round']}"
        self.assertEqual(forge.decode(command)['command'],
                         ['scripts/gate-check', 'artifact', 'code', '--base', BASE, '--salt', salt])
        self.assertEqual((forge.decode(command)['commit'], key), (BASE, f'prewarm:code:{BASE}+{salt}'))
        self.assertEqual(self.states(), ['asked', 'building', 'built', 'wanted'])
        [want] = self.db.rows(f"select payload->>'branch' from log.event where type = '{live_image.SUCCESSOR}' "
                              "and payload->>'state' = 'wanted' and payload->>'digest' = %(d)s", {'d': S1})
        self.assertEqual(want, (f"measure/{asked['round']}",))
        watcher.step()  # neither successor warm yet: nothing
        self.assertEqual(self.states()[-1], 'wanted')
        for role in ('runner', 'service'):
            self.successor(role, S1, 'warm')
        self.beat(S1)
        again = self.watcher()  # the look of another process (the swap gives the role to a new one): the log is the round
        self.successor('runner', S1, 'reserve', reserve='held')
        again.step()  # SWAP-RESERVE-WAIT: the service's reserve has not said how it stands: no drill, no question yet
        self.assertEqual(self.states()[-1], 'wanted')
        self.assertEqual(self.db.rows(f"select 1 from log.event where type = '{live_image.DRILL_EVENT}'"), [])
        self.successor('service', S1, 'reserve', reserve='held')
        again.step()
        self.assertEqual(self.states()[-1], 'ready')
        [(reserves,)] = self.db.rows("select payload->'reserves' from log.event where type = 'platform.deploy.measure' "
                                     "and payload->>'state' = 'ready'")
        self.assertEqual(json.loads(reserves) if isinstance(reserves, str) else reserves, ['runner', 'service'])
        drills = self.db.rows(f"select payload->>'role', payload->>'digest' from log.event where type = '{live_image.DRILL_EVENT}' "
                              "order by payload->>'role'")
        self.assertEqual(drills, [('runner', S1), ('service', S1)])
        self.successor('runner', S1, 'rehearsed', armed=True, reads=1)
        self.successor('service', S1, 'rehearsed', armed=False, reads=1)  # not armed yet: the round waits for it
        again.step()
        self.assertEqual(self.states()[-1], 'ready')
        self.successor('service', S1, 'rehearsed', armed=True, reads=2)
        again.step()
        self.assertEqual(self.states()[-1], 'swapped')
        self.assertEqual(self.pointers(), {key: S1 for key in live_image.KEYS.values()})
        [(swap,)] = self.db.rows("select payload::text from log.event where type = 'platform.deploy.image_swap'")
        swap = json.loads(swap)
        self.assertEqual((swap['by'], swap['head'], swap['digest'], swap['drill'], swap['swapped']),
                         ('measure', BASE, S1, True, True))
        again.step()
        self.assertEqual(self.states()[-1], 'swapped')
        self.turned(S1)
        again.step()
        self.assertEqual(self.states(), ['asked', 'building', 'built', 'wanted', 'ready', 'swapped', 'done'])
        self.assertNotIn(f"measure/{asked['round']}", again.holds)
        self.assertEqual(self.pointers(), {key: S1 for key in live_image.KEYS.values()})  # the pointers' own way back
        self.world.port('POST', '/v1/deploy/measure', 'installation', {'drill': False})  # the next round may be asked
        said = self.world.port('GET', '/v1/deploy/status', 'torre')['measure']  # where each round is, newest first
        self.assertEqual([each['state'] for each in said][:2], ['asked', 'done'])

    def test_a_round_without_the_drill_asks_none_and_a_round_never_takes_a_deliverys_slot(self):
        asked = self.world.port('POST', '/v1/deploy/measure', 'torre', {'drill': False})
        watcher = self.watcher()
        self.built(watcher, S2)
        for role in ('runner', 'service'):
            self.successor(role, S2, 'warm')
        self.beat(S2)
        watcher.step()
        self.assertEqual(self.states()[-1], 'wanted')  # no reserve said yet
        import time
        watcher.clock = lambda: time.time() + prewarm.RESERVE_WAIT_S + 1  # SWAP-RESERVE-WAIT: its bound (a landing too)
        self.beat(S2)
        watcher.step()
        self.assertEqual(self.states()[-1], 'ready')
        watcher.clock = time.time
        self.assertEqual(self.db.rows(f"select 1 from log.event where type = '{live_image.DRILL_EVENT}'"), [])
        for role in ('runner', 'service'):
            self.successor(role, S2, 'rehearsed', armed=False, reads=1)
        watcher.step()
        self.assertEqual(self.states()[-1], 'swapped')
        self.turned(S2)
        watcher.step()
        self.assertEqual(self.states()[-1], 'done')
        # a delivery's bundle holds the slot: the next round says so and ends
        watcher.standbys[S1] = {'at': 0, 'branches': {'units/a'}, 'tasks': {}, 'key': 'k', 'tries': {}, 'tried': {}, 'why': {}}
        watcher.holds['units/a'] = S1
        self.world.port('POST', '/v1/deploy/measure', 'torre', {'drill': True})
        self.built(watcher, '9' * 64)
        [(why,)] = self.db.rows("select payload->>'why' from log.event where type = 'platform.deploy.measure' "
                                "and payload->>'state' = 'failed'")
        self.assertIn('the successor slot holds aaaaaaaaaaaa of units/a', why)
        self.assertNotEqual(asked['round'], None)

    def test_the_swaps_commit_does_not_wait_for_the_disk_as_the_landings(self):
        """SWAP-ASYNC-COMMIT: the statement a round (and the autodeploy's promotion) swaps by turns synchronous_commit off
        in its own transaction, as the landing's does (LANDING-ASYNC-COMMIT), and in no other."""
        from infra_db.psql import PLACEHOLDER, literal
        self.assertIn("set_config('synchronous_commit', 'off', true)", autodeploy.SWAP_WRITE)
        params = {'tenant': 'torre', 'digest': S1, 'keys': ','.join(live_image.KEYS.values()), 'reason': 't',
                  'id': 'platform.deploy.image_swap:measure:t', 'landed_at': 0, 'payload': '{}'}
        swap = PLACEHOLDER.sub(lambda found: literal(params[found.group(1)]), autodeploy.SWAP_WRITE)
        server = self.db.rows("select current_setting('synchronous_commit')")
        said = self.db.call(['-A', '-t', '-c', "begin; set local synchronous_commit = on; "
                             f"{swap}; select 'commit: ' || current_setting('synchronous_commit'); commit"])
        self.assertIn('commit: off', said)
        self.assertEqual(self.db.rows("select current_setting('synchronous_commit')"), server)
        self.assertEqual(self.pointers(), {key: S1 for key in live_image.KEYS.values()})

    def test_a_round_with_no_successors_configured_fails_and_says_why(self):
        self.world.port('POST', '/v1/deploy/measure', 'installation', {})
        self.watcher(intask=0).step()
        self.assertEqual(self.states(), ['asked', 'failed'])
        with self.assertRaises(port.PortError) as refused:
            canary.measure(self.db, ('installation', None), {'drill': 'yes'})
        self.assertEqual(refused.exception.status, 400)


if __name__ == '__main__':
    unittest.main()
