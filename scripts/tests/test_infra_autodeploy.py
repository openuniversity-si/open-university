"""The deploy that rings itself (AUTO1): the service decides, from the log and two Parameter Store values, when to
invoke the doorbell. Fakes for the database, Parameter Store and the Lambda (no AWS, no network); the doorbell's own code
runs under node with a stub of the CodeBuild client; the IAM of the task role is read from the stack.
"""
from datetime import datetime, timezone
import calendar
import json
import time
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import autodeploy  # noqa: E402
from test_infra_aws import decide, load  # noqa: E402

BASE = 'mod/roadmap-integration'
HEAD, NEXT = 'a' * 40, 'b' * 40
T0 = 1_794_200_000.0  # 2026-11-08 ~ 05:33 UTC
BUILD = 'tower-infra-deploy:1111'


def at(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


class FakeDb:
    """Answers the module's statements from lists; records the inserts."""

    def __init__(self):
        self.pushes, self.ledger, self.inserted, self.locked, self.free = [], [], [], 0, True
        self.landed = []  # (when, payload) of platform.deploy.landed, FAST-ON-LANDED
        self.observed = []  # (event id, payload) of platform.deploy.observed, de-duplicated by id like the SQL's not exists
        self.artifacts = {}  # DIGEST-FROM-GATE-JOB: head -> the digests its gate artifact job said (its log's last JSON line)

    def push(self, when, head, ref=f'refs/heads/{BASE}', **more):
        self.pushes.append((at(when), [{'ref': ref, 'after': head, 'deleted': False, **more}]))

    def config(self, when, name, new):
        message = json.dumps({'events': [{'type': 'config.changed', 'occurred_at': f'{when:020.3f}',
                                          'payload': {'name': name, 'new': new}}]})
        self.pushes.append((at(when), [{'ref': autodeploy.EVENTS_REF, 'headCommit': {'message': message}}]))

    def rows(self, sql, params=None):
        if sql.startswith('select pg_try_advisory_lock'):
            self.locked += 1
            return [(self.free,)]
        if sql.startswith('select pg_advisory_unlock'):
            self.locked -= 1
            return [(True,)]
        if sql == autodeploy.GATE_DIGESTS:  # DIGEST-FROM-GATE-JOB
            head = params['key'].split(':')[2]
            return ([(json.dumps({'tail': 'built\n' + json.dumps({'digests': self.artifacts[head]}) + '\n'}),)]
                    if head in self.artifacts else [])
        if sql == autodeploy.TAKEOVER:  # RING-AT-TAKEOVER: no swap of the head (test_infra_reload_nostandby says one)
            return []
        if sql == autodeploy.STARTED:  # FAST-PATH-RELOAD: the newest build CodeBuild said started (none unless said)
            return list(getattr(self, 'started', []))
        if "type = 'platform.deploy.fast'" in sql and sql.startswith('select'):  # FAST-DURABLE: the swaps of the log
            found = [(json.dumps(payload), int(when.timestamp())) for kind, when, payload in self.ledger
                     if kind == 'platform.deploy.fast']
            return list(reversed(found))[:params['limit']]
        if sql in (autodeploy.NEWEST_SWAP, autodeploy.LIVE_CODE_WRITE):  # IMAGE-PREWARM-C: no image swap in these tests
            return []  # (test_infra_image_swap has them; SLOW-PATH-NO-ROLLOUT-WAIT: so no live code to write either)
        if 'platform.deploy.landed' in sql and sql.startswith('select'):
            return [(at(when), payload) for when, payload in self.landed]
        if 'platform.deploy.rung' in sql and sql.startswith('select'):
            return [(kind, when, payload) for kind, when, payload in self.ledger]
        if sql.startswith('select occurred_at'):
            ref = json.loads(params['ref'])[0]['ref']
            return [(when, updates) for when, updates in self.pushes if any(u.get('ref') == ref for u in updates)]
        if sql.startswith('insert') and 'platform.deploy.observed' in sql:
            if params['id'] not in [each[0] for each in self.observed]:
                self.observed.append((params['id'], json.loads(params['payload'])))
            return []
        if sql.startswith('insert'):
            payload = json.loads(params['payload'])
            self.inserted.append((params['type'], payload))
            self.ledger.append((params['type'], at(self.now), payload))
            return []
        raise AssertionError(sql)


class Rig:
    def __init__(self, **kwargs):
        self.db, self.now, self.rings = FakeDb(), T0, []
        self.params, self.answers = {}, [{'statusCode': 202, 'body': json.dumps({'build': BUILD})}]
        self.watcher = autodeploy.AutoDeploy(self.scope, self.ssm, self.invoke, clock=lambda: self.now,
                                             check_every_s=0, **kwargs)

    def scope(self):
        rig = self

        class Scope:
            def __enter__(self):
                rig.db.now = rig.now
                return rig.db

            def __exit__(self, *_):
                return False
        return Scope()

    def ssm(self, name):
        return self.params.get(name)

    def invoke(self, payload):
        self.rings.append(payload)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def look(self, later=0):
        self.now += later
        return self.watcher.step()

    def build(self, status, head, started, ended, build_id=BUILD):
        self.params[autodeploy.LAST_BUILD] = json.dumps({'status': status, 'base_head': head, 'started': started,
                                                         'ended': ended, 'build_id': build_id})


class ObservationTests(unittest.TestCase):
    """DEP3: the deploy state is published to the log once per change, for the port to serve."""

    def test_one_event_per_change_not_one_per_poll(self):
        rig = Rig()
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('succeeded', HEAD, T0 - 90, T0 - 60)
        rig.db.push(T0 - 500, HEAD)
        for later in (0, 30, 30, 30):
            rig.look(later)
        self.assertEqual(len(rig.db.observed), 1)  # at start, then the same state four looks long
        ident, payload = rig.db.observed[0]
        # ...head, pending, beat, spent, cycles, fast log, and FAST-SEEN-ACROSS-TASKS's count of swaps still without a result
        self.assertEqual(ident, f'platform.deploy.observed:{HEAD}:{BUILD}:succeeded:skip:deployed:{HEAD}:0:0:0:0:0:0')
        self.assertEqual((payload['last_sha'], payload['last_build']['status'], payload['ring']['reason']),
                         (HEAD, 'succeeded', 'deployed'))
        self.assertEqual(payload['observed_at'], int(T0))
        rig.params[autodeploy.LAST_SHA] = NEXT  # the state changed: a second event
        rig.look(30)
        self.assertEqual([each[1]['last_sha'] for each in rig.db.observed], [HEAD, NEXT])

    def test_a_ring_is_observed_and_renewed_while_it_is_in_flight(self):
        rig = Rig()
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 500, HEAD)
        rig.look()
        self.assertEqual(rig.db.observed[-1][1]['ring'], {'action': 'ring', 'reason': 'started', 'at': int(T0)})
        rig.look(30)  # skip: running (the ring has no ended build); a different decision is a new event
        rig.look(30)
        self.assertEqual(len(rig.db.observed), 2)
        rig.look(300)  # the beat renews it, so a reader sees a live service
        self.assertEqual(len(rig.db.observed), 3)
        self.assertGreater(rig.db.observed[-1][1]['observed_at'], rig.db.observed[1][1]['observed_at'])

    def test_a_failing_write_never_changes_the_decision(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        original = rig.db.rows

        def broken(sql, params=None):
            if 'platform.deploy.observed' in sql and sql.startswith('insert'):
                raise RuntimeError('db down')
            return original(sql, params)
        rig.db.rows = broken
        self.assertEqual(rig.look(), ('ring', 'started'))

    def test_the_insert_is_idempotent_and_the_event_has_no_tenant(self):
        self.assertIn('where not exists (select 1 from log.event where event_id = %(id)s', autodeploy.OBSERVE)
        self.assertIn('select %(id)s, null,', autodeploy.OBSERVE)


class WatchdogTests(unittest.TestCase):
    """DEP-WATCHDOG: a safety timeout for FAILURE. A ring whose build never reported its end is lost after deploy.lost_after_s
    (or when its in_progress record went silent for more than the deployer budget) and the current head is rung at once."""

    def rung(self):
        rig = Rig()
        rig.answers = [{'statusCode': 202, 'body': json.dumps({'build': BUILD})}, {'statusCode': 202, 'body': json.dumps({'build': 'tower-infra-deploy:2222'})}]
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 500, HEAD)
        self.assertEqual(rig.look(), ('ring', 'started'))
        return rig

    def test_a_ring_with_no_ended_build_is_lost_after_the_limit_and_the_head_is_rung_again(self):
        rig = self.rung()
        self.assertEqual(rig.look(2000), ('skip', 'running: the last ring has no ended build yet'))
        self.assertEqual(len(rig.rings), 1)
        self.assertEqual(rig.look(1100), ('ring', 'started'))  # 3100 s after the ring
        self.assertEqual(len(rig.rings), 2)
        lost = [payload for kind, payload in rig.db.inserted if kind == autodeploy.LOST]
        self.assertEqual(len(lost), 1)
        self.assertEqual((lost[0]['build'], lost[0]['line']), (BUILD, 'lost: no ended build after 3100 s'))
        self.assertEqual(rig.db.observed[-1][1]['lost']['line'], 'lost: no ended build after 3100 s')

    def test_the_limit_is_the_registry_key(self):
        self.assertEqual(autodeploy.DEFAULTS['lost_after_s'], 3000)
        rig = self.rung()
        rig.watcher.overrides['lost_after_s'] = ('1', 600)
        self.assertEqual(rig.look(700)[0], 'ring')

    def test_an_in_progress_build_that_stopped_updating_is_lost_before_the_limit(self):
        rig = self.rung()
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'in_progress', 'build_id': BUILD, 'base_head': HEAD, 'started': T0 + 5,
                                                        'ended': 0, 'updated': T0 + 100, 'step': 'lambda-package'})
        self.assertEqual(rig.look(2000), ('skip', 'running: the last ring has no ended build yet'))  # silent 1900 s of 2400
        seen = rig.db.observed[-1][1]['in_progress']
        self.assertEqual((seen['step'], seen['elapsed_s'], seen['idle_s']), ('lambda-package', 1995, 1900))
        self.assertEqual(rig.look(600), ('ring', 'started'))  # silent 2500 s > the 2400 s budget, 2600 s after the ring
        lost = [payload for kind, payload in rig.db.inserted if kind == autodeploy.LOST]
        self.assertIn('no stack or step event for 2500 s (step lambda-package)', lost[0]['line'])

    def test_a_build_that_keeps_updating_is_not_lost(self):
        rig = self.rung()
        for later in (900, 900, 900):
            rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'in_progress', 'build_id': BUILD, 'base_head': HEAD, 'started': T0 + 5,
                                                            'ended': 0, 'updated': rig.now + later - 10, 'step': 'stack:port'})
            self.assertEqual(rig.look(later)[0], 'skip')
        self.assertEqual(len(rig.rings), 1)

    def test_a_409_after_lost_does_not_repeat_the_event(self):
        rig = self.rung()
        rig.answers = [{'statusCode': 409, 'body': '{}'}]
        self.assertEqual(rig.look(3100)[0], 'skip')
        rig.look(100)
        rig.look(100)
        self.assertEqual(len([kind for kind, _ in rig.db.inserted if kind == autodeploy.LOST]), 1)

    def test_a_minimal_record_with_an_end_settles_the_ring(self):
        rig = self.rung()
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'build_id': BUILD, 'base_head': HEAD, 'started': T0 + 5,
                                                        'ended': T0 + 300, 'error': 'record too large'})
        self.assertEqual(rig.look(400)[0], 'skip')  # backoff
        self.assertTrue(any(kind == autodeploy.SETTLED for kind, _ in rig.db.inserted))


class SkipVisibleTests(unittest.TestCase):
    """DEP4: the status shows the CURRENT decision (min interval, budget) and the heads waiting."""

    def capped(self, **kwargs):
        rig = Rig(**kwargs)
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('succeeded', HEAD, T0 - 5000, T0 - 4500)
        rig.db.push(T0 - 90000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 7200), {'build': 'b0', 'source': 'autodeploy'}))
        rig.db.ledger.append((autodeploy.SETTLED, at(T0 - 7000), {'build': 'b0', 'seconds': 2400}))  # US$0.20
        return rig

    def test_the_stop_replaces_a_stale_deployed_and_counts_the_pending_heads(self):
        rig = self.capped()
        rig.watcher.overrides['monthly_usd'] = ('1', 0.2)
        self.assertEqual(rig.look()[1], 'deployed')
        rig.db.push(T0 + 10, NEXT)
        rig.db.push(T0 + 20, 'c' * 40)
        self.assertEqual(rig.look(300), ('skip', 'budget: US$0.20 estimated this month of US$0.20'))
        seen = rig.db.observed[-1][1]
        self.assertEqual(seen['ring']['reason'], 'budget: US$0.20 estimated this month of US$0.20')
        self.assertEqual((seen['head'], seen['pending'], seen['last_sha']), ('c' * 40, 2, HEAD))
        self.assertEqual(len(rig.db.observed), 2)
        rig.look(30)
        self.assertEqual(len(rig.db.observed), 2)  # the same cap is not a new event ...
        rig.look(900)
        self.assertEqual(len(rig.db.observed), 3)  # ... but it is renewed, so 'at' is never an hour old

    def test_min_interval_and_budget_are_published_too(self):
        rig = self.capped(); rig.db.ledger.clear()
        rig.watcher.overrides.update(debounce_s=('0', 120))
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 100), {'build': 'x', 'source': 'autodeploy'}))
        rig.db.ledger.append((autodeploy.SETTLED, at(T0 - 50), {'build': 'x', 'seconds': 30}))
        rig.db.push(T0 + 100, NEXT)
        rig.look(200)
        self.assertEqual(rig.db.observed[-1][1]['ring']['reason'].split(':')[0], 'debounce')
        rig.look(60)
        self.assertEqual(rig.db.observed[-1][1]['pending'], 1)
        rig.watcher.overrides['monthly_usd'] = (0, 0.001)
        rig.db.ledger[0] = (autodeploy.RUNG, at(T0 - 5000), {'build': 'x', 'source': 'autodeploy'})
        rig.look(900)
        self.assertEqual(rig.db.observed[-1][1]['ring']['reason'].split(':')[0], 'budget')

    def test_only_the_autodeploys_own_rings_count(self):
        rig = self.capped()
        rig.db.ledger[:] = [(autodeploy.RUNG, at(T0 - 7200 - index * 600), {'build': f'm{index}', 'source': 'manual'})
                            for index in range(6)]
        rig.db.push(T0 - 500, NEXT)
        self.assertEqual(rig.look(), ('ring', 'started'))
        self.assertEqual(rig.db.inserted[-1][1]['source'], 'autodeploy')
        self.assertEqual(len(rig.watcher.ledger(rig.db, rig.now)[0]), 1)  # the six manual ones are not in the ledger
        rig.db.ledger[:] = [(kind, when, {k: v for k, v in payload.items() if k != 'source'})
                            for kind, when, payload in rig.db.ledger]  # legacy rows have no source: they are ours
        self.assertEqual(len(rig.watcher.ledger(rig.db, rig.now)[0]), 7)


class DecisionTests(unittest.TestCase):
    def test_a_look_skipped_for_the_debounce_comes_back_when_it_ends_not_at_the_idle_safety(self):
        # DEBOUNCE-WAKE: nothing notifies the debounce's end; the loop's wait after that skip is what is left of it
        rig = Rig()
        rig.watcher.overrides['debounce_s'] = ('0', 120)
        rig.db.push(T0 - 30, 'h1')
        self.assertEqual(rig.look()[1][:8], 'debounce')
        self.assertAlmostEqual(rig.watcher.safety_s(), 90.5, places=3)
        self.assertEqual(rig.look(91), ('ring', 'started'))
        self.assertEqual(rig.watcher.safety_s(), rig.watcher.check_every_s)  # a ring in flight: the short safety, as before
        rig.params[autodeploy.LAST_SHA] = 'h1'
        rig.watcher.in_flight = False
        self.assertEqual(rig.look(1)[1], 'deployed')
        self.assertEqual(rig.watcher.safety_s(), rig.watcher.idle_safety_s)  # nothing on the clock: the idle safety

    def test_a_look_reads_what_is_new_of_the_log_not_its_seven_days_again(self):
        # LOOK-READS-WHAT-IS-NEW: live 12/11 10:38 UTC the look of the service that had just taken a swap over read the
        # 7 days of pushes inside the swap's second: 188 ms active on the database (a jsonb path and a containment over
        # every push's payload), and every look read them again
        asked = []

        class Log:
            """The log as the two 7-day reads see it: rows newer than `since`, as the database answers."""
            def __init__(self):
                self.pushes, self.landed = [], []

            def rows(self, sql, params=None):
                if sql in (autodeploy.PUSHES, autodeploy.LANDINGS):
                    since = calendar.timegm(time.strptime(params['since'], '%Y-%m-%dT%H:%M:%SZ'))
                    asked.append(('pushes' if sql == autodeploy.PUSHES else 'landings', since))
                    return [row for row in (self.pushes if sql == autodeploy.PUSHES else self.landed)
                            if row[0].timestamp() > since]
                raise AssertionError(sql)
        log, watcher = Log(), Rig().watcher
        push = lambda when, head: (at(when), [{'ref': f'refs/heads/{BASE}', 'after': head, 'deleted': False}])  # noqa: E731
        log.pushes += [push(T0 - 8 * 86400, 'old'), push(T0 - 3 * 86400, 'h1'), push(T0 - 100, 'h2')]
        self.assertEqual([head for head, _ in watcher.pushes(log, BASE, T0)], ['h1', 'h2'])
        self.assertEqual(asked, [('pushes', T0 - 7 * 86400), ('landings', T0 - 7 * 86400)])  # the first read: all 7 days
        del asked[:]
        log.pushes.append(push(T0 + 50, 'h3'))
        log.landed.append((at(T0 + 51), {'merge_sha': 'h3', 'pr_head': 'p3', 'paths': ['docs/a.md']}))
        self.assertEqual([head for head, _ in watcher.pushes(log, BASE, T0 + 60)], ['h1', 'h2', 'h3'])
        # the next ones: from a minute before the newest row each read has; with no landing read yet, its 7 days still
        self.assertEqual(asked, [('pushes', T0 - 100 - autodeploy.OVERLAP_S), ('landings', T0 + 60 - 7 * 86400)])
        self.assertEqual((watcher.landed_at['h3'], watcher.touched['h3']), (T0 + 51, ['docs/a.md']))
        del asked[:]
        log.pushes.insert(2, push(T0 + 20, 'late'))  # committed after a newer row was read: inside the overlap
        self.assertEqual([head for head, _ in watcher.pushes(log, BASE, T0 + 70)], ['h1', 'h2', 'late', 'h3'])
        self.assertEqual(asked, [('pushes', T0 + 50 - autodeploy.OVERLAP_S), ('landings', T0 + 51 - autodeploy.OVERLAP_S)])
        # what leaves the 7 days leaves the look too
        self.assertEqual([head for head, _ in watcher.pushes(log, BASE, T0 + 5 * 86400)], ['h2', 'late', 'h3'])

    def test_a_service_standing_by_reads_ahead_and_decides_nothing(self):
        # LOOK-READS-WHAT-IS-NEW: the first look of a service that took a swap over read the 7 days at that instant; the
        # standby reads them when it warms, and its first look reads what is new
        rig = Rig()
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 500, HEAD)
        autodeploy.WATCHERS[:] = [rig.watcher]
        self.addCleanup(autodeploy.WATCHERS.clear)
        self.assertEqual(autodeploy.read_ahead(rig.scope), 1)  # one push to the base read
        self.assertEqual((rig.rings, rig.db.inserted, rig.db.observed), ([], [], []))  # no ring, nothing written
        self.assertEqual(len(rig.watcher.rows_read[f'pushes:{BASE}']), 1)
        self.assertEqual(rig.look(), ('ring', 'started'))  # the look itself, as before
        autodeploy.WATCHERS.clear()
        self.assertIsNone(autodeploy.read_ahead(rig.scope))  # a process with no look: nothing to read

    def test_a_head_whose_landing_is_known_is_rung_without_the_debounce(self):
        # RING-AT-LANDING: the audit of the clocks (aws.md 19.2) left the debounce with a plan: ring at once. Every slow
        # deploy of a delivery started 20 s after its landing for it, and what a build must wait for is said by events
        rig = Rig()
        rig.watcher.overrides['debounce_s'] = ('0', 120)
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 5, HEAD)
        self.assertEqual(rig.look()[1][:8], 'debounce')  # a push alone: its landing is not known (yet, or ever)
        rig.db.landed.append((T0 - 4, {'merge_sha': HEAD, 'pr_head': 'p' * 40, 'paths': ['infra/aws/stacks/50-runner.json']}))
        self.assertEqual(rig.look(1), ('ring', 'started'))  # the landing's event woke the look: 6 s after the push, not 120
        self.assertEqual(rig.db.inserted[-1][1]['head'], HEAD)

    def test_a_burst_of_merges_is_one_ring_after_the_debounce(self):
        rig = Rig()
        rig.watcher.overrides['debounce_s'] = ('0', 120)
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 50, HEAD)
        self.assertEqual(rig.look()[0], 'skip')  # 50 s old of 120
        rig.db.push(T0 + 40, NEXT)  # a second merge restarts the wait
        self.assertEqual(rig.look(60)[1][:8], 'debounce')
        self.assertEqual(rig.look(100), ('ring', 'started'))  # 120 s after the newest push
        self.assertEqual(rig.rings, [{'source': 'autodeploy'}])
        self.assertEqual(rig.db.inserted, [(autodeploy.RUNG, {'build': BUILD, 'head': NEXT, 'pushed_at': T0 + 40,
                                                    'source': 'autodeploy'})])
        self.assertEqual(rig.db.locked, 0)

    def test_nothing_rings_when_the_head_is_deployed_or_no_push_is_seen_or_the_branch_is_another(self):
        rig = Rig()
        self.assertIn('no push', rig.look()[1])
        rig.db.push(T0 - 500, HEAD, ref='refs/heads/units/x')
        self.assertIn('no push', rig.look(1)[1])
        rig.db.push(T0 - 500, HEAD)
        rig.params[autodeploy.LAST_SHA] = HEAD
        self.assertEqual(rig.look(1), ('skip', 'deployed'))
        rig.params.pop(autodeploy.LAST_SHA)
        rig.build('nothing_new', HEAD, T0 - 90, T0 - 60)
        self.assertEqual(rig.look(1), ('skip', 'deployed'))
        self.assertEqual(rig.rings, [])

    def test_a_build_that_started_after_the_push_covers_it(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.build('succeeded', 'c' * 40, T0 - 400, T0 - 100)
        self.assertIn('covered', rig.look()[1])

    def test_a_409_is_running_not_an_error_and_rings_again_after_the_wait(self):
        rig = Rig(running_retry_s=60)
        rig.db.push(T0 - 500, HEAD)
        rig.answers = [{'statusCode': 409, 'body': '{"error":"ResourceAlreadyExistsException"}'},
                       {'statusCode': 202, 'body': json.dumps({'build': BUILD})}]
        self.assertIn('running', rig.look()[1])
        self.assertIn('running', rig.look(30)[1])
        self.assertEqual(len(rig.rings), 1)  # not rung again while it waits
        self.assertEqual(rig.look(31), ('ring', 'started'))
        self.assertEqual(rig.db.inserted[0][0], autodeploy.RUNG)

    def test_no_second_ring_while_the_rung_build_has_not_ended(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        self.assertEqual(rig.look(), ('ring', 'started'))
        rig.db.push(T0 + 10, NEXT)
        self.assertIn('running', rig.look(500)[1])  # the build is 500 s old and last-build is still the old one
        self.assertEqual(len(rig.rings), 1)

    def test_a_failed_head_waits_for_an_event_never_for_the_clock(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.build('failed', HEAD, T0 - 1900, T0 - 1000)
        for later in (0, 700, 200, 86400):  # no amount of time rings the same failed head again
            self.assertIn('never for time', rig.look(later)[1])
        self.assertEqual(rig.rings, [])
        rig.db.push(rig.now - 100, NEXT)  # the event: a new push (a fix) on the base
        self.assertEqual(rig.look(30), ('ring', 'started'))
        self.assertEqual(len(rig.rings), 1)

    def test_there_is_no_time_gate_left_in_the_settings(self):
        self.assertNotIn('retry_backoff_s', autodeploy.DEFAULTS)
        self.assertNotIn('min_interval_s', autodeploy.DEFAULTS)

    def test_last_sha_at_the_head_is_not_deployed_while_the_last_build_failed(self):
        # live 09/11: last-sha moved to the fix while last-build stayed the failed build of another head
        rig = Rig()
        rig.db.push(T0 - 3000, NEXT)
        rig.db.push(T0 - 2000, HEAD)
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('failed', NEXT, T0 - 1900, T0 - 1000)
        self.assertEqual(rig.look(), ('ring', 'started'))
        rig = Rig()
        rig.db.push(T0 - 2000, HEAD)
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'succeeded', 'base_head': HEAD, 'started': T0 - 1900,
                                                        'ended': T0 - 1000, 'build_id': BUILD, 'dirty': ['tower-app-ack-canary']})
        self.assertEqual(rig.look(), ('ring', 'started'))  # a dirty stack rings even when the diff is fast only
        rig = Rig()
        rig.db.push(T0 - 2000, HEAD)
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('succeeded', HEAD, T0 - 1900, T0 - 1000)
        self.assertEqual(rig.look()[1], 'deployed')

    def test_the_build_end_is_an_event_and_lifts_the_409_hold_at_once(self):
        rig = Rig()
        rig.db.push(T0 - 100, HEAD)
        rig.answers[:] = [{'statusCode': 409, 'body': '{}'}]
        self.assertIn('409', rig.look()[1])
        self.assertIn('running', rig.look(1)[1])  # held while the build runs
        rig.db.push(T0 - 30, NEXT)
        rig.build('succeeded', HEAD, T0 - 50, T0 + 6)  # the build ends: no 60 s wait
        rig.answers[:] = [{'statusCode': 202, 'body': json.dumps({'build': BUILD})}]
        self.assertEqual(rig.look(20), ('ring', 'started'))

    def test_the_loop_waits_on_the_event_and_the_safety_is_not_a_gate(self):
        import threading
        rig = Rig()
        rig.db.push(T0 - 100, HEAD)
        stop, waits = threading.Event(), []

        def wait(timeout):
            waits.append(timeout)
            if len(waits) == 2:
                stop.set()
            return len(waits) == 1  # the first wait is woken by an event, the second times out
        with mock.patch.object(autodeploy, 'from_boto3', lambda scope: rig.watcher):
            thread = autodeploy.start(rig.scope, stop, wait=wait)
        thread.join(5)
        self.assertEqual(len(rig.rings), 1)  # the event looked at once, with no tick in between
        self.assertEqual(waits[0], rig.watcher.idle_safety_s)  # idle: the long safety; in flight it is check_every_s

    def test_a_pass_that_raises_is_said_and_the_look_goes_on_and_three_in_a_row_are_published(self):
        """AUTODEPLOY-LIVES: the wait raising (a lost database connection under LISTEN) ended the thread for good while
        the task stayed healthy; now each failure is logged, the look pauses and goes on, and the third in a row pages."""
        import threading
        stop, calls, published = threading.Event(), [], []
        watcher = mock.Mock(check_every_s=1, safety_s=lambda: 1)

        def wait(_):
            calls.append(1)
            if len(calls) <= 3:
                raise OSError('the connection under LISTEN was lost')
            if len(calls) == 5:
                stop.set()
        with mock.patch.object(autodeploy, 'from_boto3', return_value=watcher), \
                mock.patch.object(autodeploy, 'LOOK_BACKOFF_MAX_S', 0.0), self.assertLogs('tower_infra.autodeploy', 'ERROR'):
            thread = autodeploy.start(None, stop, wait=wait, config=None, alert=lambda said, subject: published.append(
                (subject, said['key'], said['ok'])))
            thread.join(5)
        self.assertFalse(thread.is_alive())  # it ended only because it was asked to
        self.assertEqual(len(calls), 5)  # three failures, then the look went on
        self.assertEqual(watcher.step.call_count, 1)  # the pass after the failures stepped (the fifth stopped)
        self.assertEqual(published, [('tower autodeploy failing', 'autodeploy', False)])  # once, at the third

    def test_a_newer_head_is_not_held_by_the_backoff_of_an_older_failed_one(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.build('failed', HEAD, T0 - 1900, T0 - 1000)  # HEAD failed 1000 s ago, inside the backoff
        rig.db.push(T0 - 100, NEXT)  # a later commit
        self.assertEqual(rig.look(), ('ring', 'started'))  # past its own debounce: no backoff for another head
        self.assertEqual(len(rig.rings), 1)

    def test_the_monthly_budget_stops_the_ring_and_there_is_no_daily_cap(self):
        self.assertNotIn('max_per_day', autodeploy.DEFAULTS)
        rig = Rig()  # 40 rings of the last day, all ended: nothing caps them (default min_interval_s 0)
        rig.db.push(T0 - 500, HEAD)
        for index in range(40):
            rig.db.ledger.append((autodeploy.RUNG, at(T0 - 7200 - index * 600), {'build': f'b{index}'}))
            rig.db.ledger.append((autodeploy.SETTLED, at(T0 - 7000 - index * 600), {'build': f'b{index}', 'seconds': 30}))
        self.assertEqual(rig.look(), ('ring', 'started'))
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 7200), {'build': 'big'}))
        rig.db.ledger.append((autodeploy.SETTLED, at(T0 - 7000), {'build': 'big', 'seconds': 2400}))  # 40 min = US$0.20
        rig.watcher.overrides['monthly_usd'] = ('1', 0.2)
        self.assertIn('budget', rig.look()[1])
        rig.watcher.overrides['monthly_usd'] = ('2', 0.21)
        self.assertEqual(rig.look(1), ('ring', 'started'))

    def test_the_kill_switch_comes_from_a_config_change_and_an_unset_restores_the_default(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.db.config(T0 - 400, 'deploy.auto', False)
        self.assertIn('off', rig.look()[1])
        self.assertEqual(rig.rings, [])
        rig.db.config(T0 - 100, 'deploy.auto', None)
        self.assertEqual(rig.look(1), ('ring', 'started'))

    def test_a_bad_override_is_ignored_and_other_names_do_not_apply(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.db.config(T0 - 400, 'deploy.monthly_usd', 'many')
        rig.db.config(T0 - 399, 'delivery.judge', 'box')
        self.assertEqual(rig.look(), ('ring', 'started'))
        self.assertEqual(rig.watcher.settings(), autodeploy.DEFAULTS)

    def test_another_task_holding_the_lock_means_no_ring(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.db.free = False
        self.assertIn('another service task', rig.look()[1])
        self.assertEqual(rig.rings, [])

    def test_a_settled_build_is_recorded_with_its_seconds(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.build('succeeded', 'c' * 40, T0 - 1900, T0 - 1000)
        rig.look()
        self.assertIn((autodeploy.SETTLED, {'build': BUILD, 'seconds': 900, 'status': 'succeeded'}), rig.db.inserted)

    def test_a_failed_look_never_raises_and_the_rate_limit_holds(self):
        rig = Rig()
        rig.ssm = lambda name: 1 / 0
        rig.watcher.ssm = rig.ssm
        rig.db.push(T0 - 500, HEAD)
        self.assertIsNone(rig.look())
        rig.watcher.check_every_s = 30
        rig.watcher.next_look = rig.now + 30
        self.assertIsNone(rig.look(10))


class SpendTests(unittest.TestCase):
    def test_the_estimate_is_minutes_times_the_price_and_unsettled_rings_are_bounded(self):
        rings = [{'at': T0 - 7200, 'build': 'a'}, {'at': T0 - 3600, 'build': 'b'}, {'at': T0 - 100, 'build': 'c'}]
        spent = autodeploy.AutoDeploy.spent(rings, {'a': 600}, 0.005, T0)
        # a: 10 min; b: unsettled, the 3500 s until the next ring capped at the 2700 s timeout; c: 100 s until now
        self.assertAlmostEqual(spent, (600 + 2700 + 100) / 60 * 0.005)

    def test_one_unsettled_ring_costs_at_most_the_projects_timeout(self):
        spent = autodeploy.AutoDeploy.spent([{'at': T0 - 86400 * 2, 'build': 'x'}], {}, 0.005, T0 - 86400 * 2 + 10 ** 6)
        self.assertAlmostEqual(spent, 2700 / 60 * 0.005)  # US$0.225

    def test_the_hard_stop_is_above_the_alarm_and_under_the_account_cap(self):
        d = autodeploy.DEFAULTS
        self.assertEqual(d['alarm_usd'], 20.0)
        self.assertLess(d['alarm_usd'], d['monthly_usd'])
        self.assertLess(d['monthly_usd'] + autodeploy.BUILD_MAX_S / 60 * d['usd_per_min'], 60)


class SlowPathTests(unittest.TestCase):
    """DEP7: selective ring, coalescing, cycle measures, cost alarm, bisection not held back."""

    def classify(self, paths):
        sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
        import deploy_classify
        return deploy_classify.classify(paths)

    def test_the_service_filter_agrees_with_the_classifier_on_every_real_file(self):
        out = subprocess.run(['git', 'ls-files'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
        out = [path for path in out if path.startswith(('infra/', 'services/', 'config/', 'docs/', 'scripts/'))]
        for path in out + ['infra/aws/stacks/99-new.json', 'infra/service/tower_infra/new.py', 'infra/ingress/x.py']:
            self.assertEqual(autodeploy.slow_path(path), bool(self.classify([path])['slow']), path)

    def test_every_stack_file_is_slow_in_both_filters_hyphenated_names_included(self):
        tracked = subprocess.run(['git', 'ls-files', 'infra/aws/stacks'], cwd=ROOT, check=True, capture_output=True,
                                 text=True).stdout.split()
        for path in tracked + ['infra/aws/stacks/45-ack-canary.json', 'infra/aws/stacks/60-a-b-c-d.json',
                               'infra/aws/stacks/5-x.json', 'infra/aws/stacks/x.json', 'infra/aws/stacks/sub/y.json']:
            self.assertTrue(autodeploy.slow_path(path), path)
            self.assertTrue(self.classify([path])['slow'], path)

    def test_the_deploy_wake_is_a_log_trigger_not_a_timer(self):
        sql = (ROOT / 'infra/db/migrations/0009_wake_deploy.sql').read_text()
        for kind in ('forge.repository.pushed', 'platform.deploy.ended'):
            self.assertIn(f"'{kind}'", sql)
        self.assertIn("pg_notify('tower_deploy'", sql)
        sys.path.insert(0, str(ROOT / 'infra' / 'service'))
        from tower_infra import wake
        self.assertEqual(wake.DEPLOY, 'tower_deploy')
        wake.Wake(lambda: None, wake.DEPLOY)

    def rig_with(self, *pushes):
        rig = Rig()
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('succeeded', HEAD, T0 - 5000, T0 - 4500, build_id='old')
        rig.db.push(T0 - 90000, HEAD)
        for index, (head, paths) in enumerate(pushes):
            rig.db.push(T0 - 3000 + index, head, headCommit={'modified': paths} if paths is not None else {})
        return rig

    def test_a_merge_with_only_fast_targets_does_not_ring_and_stays_pending(self):
        rig = self.rig_with((NEXT, ['services/runner/github/tower-gate.yml', 'docs/x.md']))
        self.assertEqual(rig.look()[0], 'skip')
        self.assertEqual(rig.rings, [])
        self.assertEqual([kind for kind, _ in rig.db.inserted], [autodeploy.PENDING])
        self.assertIn('fast only', rig.look(1)[1])

    def test_a_slow_path_or_an_unlisted_push_rings_and_the_build_takes_the_current_head(self):
        for push in ((NEXT, ['infra/aws/stacks/40-port.json']), (NEXT, None)):
            rig = self.rig_with(push)
            self.assertEqual(rig.look(), ('ring', 'started'))
        rig = self.rig_with((NEXT, ['docs/a.md']), ('c' * 40, ['infra/service/Dockerfile']), ('d' * 40, ['docs/b.md']))
        self.assertEqual(rig.look(), ('ring', 'started'))  # one slow commit in the batch rings for the whole range
        self.assertEqual(len(rig.rings), 1)

    def test_no_second_ring_while_one_is_in_flight_and_the_next_takes_the_head_when_it_ends(self):
        rig = self.rig_with((NEXT, ['infra/aws/deploy.sh']))
        self.assertEqual(rig.look(), ('ring', 'started'))
        rig.db.push(T0 + 5, 'c' * 40, headCommit={'modified': ['infra/service/Dockerfile']})
        self.assertIn('running', rig.look(100)[1])
        rig.params[autodeploy.LAST_SHA] = NEXT
        rig.build('succeeded', NEXT, T0 + 1, T0 + 120)
        self.assertEqual(rig.look(200), ('ring', 'started'))  # no min interval, no daily cap
        self.assertEqual(rig.db.inserted[-1][1]['head'], 'c' * 40)

    def test_an_ended_build_is_a_cycle_event_with_seconds_usd_and_targets(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'succeeded', 'base_head': 'c' * 40, 'started': T0 - 1900,
                                                        'ended': T0 - 1720, 'build_id': BUILD, 'targets': ['port']})
        rig.look()
        cycle = dict(rig.db.inserted)[autodeploy.CYCLE]
        self.assertEqual((cycle['seconds'], cycle['targets'], cycle['status']), (180, ['port'], 'succeeded'))
        self.assertAlmostEqual(cycle['usd'], 180 / 60 * 0.005)
        status = rig.db.observed[-1][1]
        self.assertEqual(status['cost']['alarm'], False)

    def test_the_smoke_evidence_travels_in_the_cycle_event_and_the_status(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        smoke = {'ok': False, 'http_status': 500, 'ms': 30, 'body': 'b', 'drop': 'missing', 'reason': 'r', 'fail_tail': 'tail'}
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'base_head': 'c' * 40, 'started': T0 - 1900,
                                                        'ended': T0 - 1720, 'build_id': BUILD, 'ack_smoke': smoke})
        rig.look()
        cycle = dict(rig.db.inserted)[autodeploy.CYCLE]
        self.assertEqual(cycle['ack_smoke'], smoke)

    def test_a_build_that_moved_the_ack_off_sqs_or_rolled_back_is_an_event_and_an_alert_once(self):
        # MODE-CHANGE-ALERT (revisão da arquitetura, achado 6): on 10/11 a guard put the ACK back on the Lambda path and
        # production ran ~24 h so, unseen; a guard or rollback that changes how production runs is said where people look
        def ended(build, **record):
            rig = Rig()
            rig.db.push(T0 - 3000, HEAD)
            rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': build}))
            rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'base_head': HEAD, 'started': T0 - 1900,
                                                            'ended': T0 - 1720, 'build_id': build, **record})
            published = []
            rig.watcher.publish = lambda said, subject: published.append((subject, said))
            rig.look()
            rig.look(30)  # the build is settled once: no second event, no second alert
            return [payload for kind, payload in rig.db.inserted if kind == autodeploy.MODE], published
        said, published = ended('b1', ack={'path': 'lambda', 'source': 'file'}, ack_failed={'sha': HEAD},
                                rolled_back=['tower-app-port'])
        self.assertEqual(said, [{'build': 'b1', 'sha': HEAD, 'changes': [
            'the ACK smoke was red: the ACK is on the lambda path, not sqs', 'a red smoke rolled back tower-app-port']}])
        self.assertEqual([subject for subject, _ in published],
                         [('tower deploy: the ACK smoke was red: the ACK is on the lambda path, not sqs; '
                           'a red smoke rolled back tower-app-port')[:100]])  # SNS takes a subject of 100 characters
        # an older build's ACK failure that this build only carries is no new change; a green build with nothing undone says nothing
        self.assertEqual(ended('b2', ack={'path': 'lambda'}, ack_failed={'sha': NEXT}), ([], []))
        self.assertEqual(ended('b3'), ([], []))

    def test_a_found_culprit_is_an_event(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'base_head': HEAD, 'started': T0 - 1900,
                                                        'ended': T0 - 1000, 'build_id': BUILD, 'tail': 'why',
                                                        'bisect': {'culprit': NEXT, 'good': HEAD, 'bad': NEXT}})
        rig.look()
        self.assertEqual(dict(rig.db.inserted)['platform.deploy.culprit']['sha'], NEXT)

    def test_the_month_reaching_the_alarm_publishes_it_once_and_the_status_carries_the_line(self):
        rig = Rig()
        rig.db.push(T0 - 500, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 7200), {'build': 'big'}))
        rig.db.ledger.append((autodeploy.SETTLED, at(T0 - 7000), {'build': 'big', 'seconds': 2400}))  # US$0.20
        rig.watcher.overrides['alarm_usd'] = ('1', 0.2)
        self.assertEqual(rig.look(), ('ring', 'started'))  # the alarm speaks, the hard stop (US$30) does not stop it
        rig.db.push(T0 + 10, NEXT)
        rig.build('succeeded', HEAD, T0, T0 + 5, build_id=BUILD)
        rig.look(900)
        self.assertEqual([kind for kind, _ in rig.db.inserted].count(autodeploy.ALARM), 1)
        line = rig.db.observed[-1][1]['cost']
        self.assertTrue(line['alarm'] and 'COST ALARM' in line['line'])

    def test_a_bisection_in_progress_is_not_held_by_the_backoff_or_the_covered_rule(self):
        rig = Rig()
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'base_head': HEAD, 'started': T0 - 1900,
                                                        'ended': T0 - 1800, 'build_id': BUILD,
                                                        'bisect': {'good': 'z' * 40, 'bad': HEAD},
                                                        'bisect_epoch': autodeploy.BISECT_EPOCH})
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        self.assertEqual(rig.look(), ('ring', 'started'))
        rig = Rig()  # a culprit is final: the backoff applies again
        rig.db.push(T0 - 3000, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
        rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'failed', 'base_head': HEAD, 'started': T0 - 1900,
                                                        'ended': T0 - 1000, 'build_id': BUILD,
                                                        'bisect': {'culprit': HEAD, 'bad': HEAD}})
        self.assertIn('never for time', rig.look()[1])

    def test_a_leftover_bisection_does_not_hold_the_covered_rule_and_the_status_says_why(self):
        for bisect, epoch, why in (({'good': 'z' * 40, 'bad': HEAD}, 1, 'epoch'), ({'good': 'z' * 40, 'bad': HEAD, 'builds': 8},
                                   autodeploy.BISECT_EPOCH, '8 builds'), ({'culprit': 'c' * 40, 'good': 'z' * 40, 'bad': 'c' * 40},
                                   autodeploy.BISECT_EPOCH, 'does not block')):
            rig = Rig()
            rig.db.push(T0 - 3000, HEAD)
            rig.db.ledger.append((autodeploy.RUNG, at(T0 - 2000), {'build': BUILD}))
            last = {'status': 'succeeded', 'base_head': 'y' * 40, 'started': T0 - 1900, 'ended': T0 - 1800, 'build_id': BUILD,
                    'bisect': bisect, 'bisect_epoch': epoch}
            rig.params[autodeploy.LAST_BUILD] = json.dumps(last)
            rig.params[autodeploy.LAST_SHA] = 'z' * 40
            self.assertEqual(rig.look(), ('ring', 'started'), why)  # a build that started after the push would be 'covered'
            view = autodeploy.AutoDeploy.bisect_view(last)
            self.assertEqual(view['bisect']['state'], 'leftover')
            self.assertIn(why, view['bisect']['reason'])
        live = autodeploy.AutoDeploy.bisect_view({'bisect': {'good': 'z' * 40, 'bad': HEAD, 'reason': 'r'}, 'bisect_epoch': autodeploy.BISECT_EPOCH})
        self.assertEqual((live['bisect']['state'], live['bisect']['reason'], live['culprit']), ('bisecting', 'r', None))
        named = autodeploy.AutoDeploy.bisect_view({'bisect': {'culprit': 'c' * 40, 'reason': 'q'}, 'bisect_epoch': autodeploy.BISECT_EPOCH})
        self.assertEqual(named['culprit'], {'sha': 'c' * 40, 'reason': 'q', 'blocks': False})

    def test_nothing_may_be_zero(self):
        with self.assertRaises(ValueError):
            autodeploy.coerce('debounce_s', 0)


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = load(ROOT / 'infra/aws/bootstrap.json')
        self.stack = load(ROOT / 'infra/aws/stacks/30-service.json')

    def test_the_defaults_mirror_the_registry_and_every_key_names_the_module_as_its_reader(self):
        directory = ROOT / 'config/registry/deploy'
        found = {}
        for path in directory.glob('deploy.*.json'):
            entry = load(path)
            if path.stem.startswith('deploy.live_image_'):  # IMAGE-PREWARM-A: the pointers are live_image's, not a knob of the look
                self.assertEqual(entry['x-readers'], ['infra/service/tower_infra/live_image.py'])
                continue
            if path.stem == 'deploy.live_code':  # SLOW-PATH-NO-ROLLOUT-WAIT: a datum the look writes and the boot reads
                self.assertEqual(entry['x-readers'], ['infra/service/tower_infra/autodeploy.py', 'infra/service/tower_infra/code_bundle.py'])
                continue
            if path.stem == 'deploy.intask_standbys':  # IN-TASK-STANDBY: the successors a task holds (GATE-LOOKS-GONE: no prewarm)
                self.assertEqual(entry['x-readers'], ['infra/service/tower_infra/live_image.py'])
                continue
            # IMAGE-SWAP-TIGHTEN: the landing's freshness is the port's; IMAGE-SWAP-FAILOVER: the stale window is the gate's
            other = {'deploy.standby_fresh_s': 'port.py', 'deploy.live_stale_s': 'live_image.py',
                     'deploy.canary_limit_s': 'canary.py',  # DEPLOY-CANARY: the canary's limit is its own
                     'deploy.canary_slot': 'canary.py'}.get(path.stem)  # CANARY-OWN-SLOT: and its slot
            if other:
                self.assertEqual(entry['x-readers'], [f'infra/service/tower_infra/{other}'])
                continue
            found[path.stem[len('deploy.'):]] = entry['default']
            self.assertIn('infra/service/tower_infra/autodeploy.py', entry['x-readers'])
        self.assertEqual(found, autodeploy.DEFAULTS)

    def test_the_build_timeout_the_guard_assumes_is_the_projects(self):
        minutes = self.bootstrap['Resources']['DeployProject']['Properties']['TimeoutInMinutes']
        self.assertEqual(autodeploy.BUILD_MAX_S, minutes * 60)

    def test_the_task_role_can_invoke_only_the_doorbell_and_read_only_the_two_deploy_parameters(self):  # and put bundles
        policies = {each['PolicyName']: each['PolicyDocument']['Statement']
                    for each in self.stack['Resources']['TaskRole']['Properties']['Policies']}
        invoke, read, fast, artifacts, put = policies['autodeploy']
        # QUEUE-RELOAD: and put the code bundles it prepares, under artifacts/lambda/tower-code/ only
        self.assertEqual((put['Effect'], put['Action']), ('Allow', 's3:PutObject'))
        self.assertEqual(put['Resource']['Fn::Sub'],
                         'arn:${AWS::Partition}:s3:::tower-outputs-${AWS::AccountId}-${AWS::Region}/artifacts/lambda/tower-code/*')
        self.assertEqual((invoke['Action'], read['Action']), ('lambda:InvokeFunction', 'ssm:GetParameter'))
        # DEP8: the pointer swap acts on exactly the port's function (and its versions), nothing broader; TASKROLE-LEAST:
        # the ack ingress and the webhook consumer left the port stack, so the role names neither
        self.assertEqual(sorted(fast['Action']), sorted(['lambda:UpdateFunctionCode', 'lambda:PublishVersion', 'lambda:UpdateAlias',
                                                         'lambda:GetAlias', 'lambda:GetFunctionConfiguration', 'lambda:InvokeFunction']))
        prefix = 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:'
        self.assertEqual(sorted(each['Fn::Sub'] for each in fast['Resource']),
                         sorted(prefix + name + suffix for name in ('tower-port-api',)
                                for suffix in ('', ':*')))
        self.assertEqual(artifacts['Action'], 's3:GetObject')
        self.assertEqual(artifacts['Resource']['Fn::Sub'], 'arn:${AWS::Partition}:s3:::tower-outputs-${AWS::AccountId}-${AWS::Region}/artifacts/lambda/*')
        for each in (invoke, read, fast, artifacts):
            self.assertEqual(each['Effect'], 'Allow')
        arn = 'arn:aws-partition:lambda:REGION:ACCOUNT:function:tower-deploy-doorbell'
        self.assertEqual(invoke['Resource']['Fn::Sub'], 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-deploy-doorbell')
        self.assertEqual(sorted(each['Fn::Sub'].rsplit(':parameter', 1)[1] for each in read['Resource']),
                         ['/tower/deploy/last-build', '/tower/deploy/last-sha'])
        self.assertEqual(self.bootstrap['Resources']['DoorbellFunction']['Properties']['FunctionName'], 'tower-deploy-doorbell')
        boundary = self.bootstrap['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        self.assertEqual(decide(boundary, 'lambda:InvokeFunction', arn), 'allow')
        # LAMBDA-PRUNE (#689): its own policy lists and deletes the port's old versions (test_infra_service holds that the
        # delete is by the qualified ARN alone); every other policy holds no codebuild or lambda action but the swap's
        prune = {action for item in policies.pop('prune') for action in
                 ([item['Action']] if isinstance(item['Action'], str) else item['Action']) if action.startswith('lambda:')}
        self.assertEqual(prune, {'lambda:ListVersionsByFunction', 'lambda:ListAliases', 'lambda:DeleteFunction'})
        every = {action for each in policies.values() for item in each for action in
                 ([item['Action']] if isinstance(item['Action'], str) else item['Action'])}
        self.assertFalse({action for action in every if action.startswith(('codebuild:', 'lambda:'))} - set(fast['Action']))
        self.assertEqual(read['Action'], 'ssm:GetParameter')  # the autodeploy policy reads parameters, writes none
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn('autodeploy.start(', main)
        env = {each['Name']: each['Value'] for container in self.stack['Resources']['TaskDefinition']['Properties']
               ['ContainerDefinitions'] if container['Name'] == 'service' for each in container['Environment']}
        self.assertEqual(env['TOWER_DOORBELL_FUNCTION'], 'tower-deploy-doorbell')

    def test_the_ingress_hot_path_is_untouched(self):
        source = (ROOT / 'infra/service/tower_infra/ingress.py').read_text(encoding='utf-8')
        self.assertNotIn('autodeploy', source)

    def test_without_a_doorbell_name_the_service_does_not_start_it(self):
        self.assertIsNone(autodeploy.from_boto3(lambda: None, {}))


HARNESS = r'''
const Module = require('module');
const real = Module.prototype.require;
Module.prototype.require = function (name) {
  if (name === '@aws-sdk/client-codebuild') {
    return { CodeBuildClient: class { async send() {
      if (process.env.RUNNING) { const e = new Error('limit'); e.name = process.env.RUNNING_AS || 'AccountLimitExceededException'; throw e; }
      if (process.env.BUILT) { require('fs').writeFileSync(process.env.BUILT, 'a build'); }
      return { build: { id: 'tower-infra-deploy:abc' } }; } }, StartBuildCommand: class { constructor(x) { this.x = x; } } };
  }
  if (name === '@aws-sdk/client-ssm') {  // RING-QUEUE: /tower/deploy/ring-pending is the file PENDING
    const fs = require('fs');
    const command = (kind) => class { constructor(x) { this.kind = kind; this.x = x; } };
    return { SSMClient: class { async send(c) {
      if (c.x.Name === '/tower/deploy/github-webhook-secret' && c.kind === 'get' && c.x.WithDecryption) {  // GITHUB-HOOK
        fs.appendFileSync(process.env.HOOK_READS, 'read\n'); return { Parameter: { Value: process.env.HOOK_SECRET } }; }
      if (c.x.Name !== '/tower/deploy/ring-pending') { throw new Error('another parameter: ' + c.x.Name); }
      if (c.kind === 'put') { fs.writeFileSync(process.env.PENDING, c.x.Value); return {}; }
      if (!fs.existsSync(process.env.PENDING)) { const e = new Error('none'); e.name = 'ParameterNotFound'; throw e; }
      if (c.kind === 'delete') { fs.unlinkSync(process.env.PENDING); return {}; }
      return { Parameter: { Value: fs.readFileSync(process.env.PENDING, 'utf8') } }; } },
      GetParameterCommand: command('get'), PutParameterCommand: command('put'), DeleteParameterCommand: command('delete') };
  }
  if (name === '@aws-sdk/client-lambda') {  // QUEUE-RELOAD: the port's invocation, written to INVOKED
    return { LambdaClient: class { async send(command) {
      if (process.env.STARTED) { require('fs').writeFileSync(process.env.STARTED, 'a build'); }
      require('fs').writeFileSync(process.env.INVOKED, JSON.stringify({ name: command.x.FunctionName,
        payload: JSON.parse(Buffer.from(command.x.Payload).toString('utf8')) }));
      return process.env.PORT_FAILS ? { FunctionError: 'Unhandled' } : { StatusCode: 200 }; } },
      InvokeCommand: class { constructor(x) { this.x = x; } } };
  }
  return real.apply(this, arguments);
};
const source = require('fs').readFileSync(process.argv[2], 'utf8');
const mod = { exports: {} };
new Function('require', 'exports', 'module', source)(require, mod.exports, mod);
const once = () => mod.exports.handler(JSON.parse(process.argv[3]));  // TWICE: two calls in one container
(process.env.TWICE ? once().then(first => once().then(second => [first, second])) : once()).then(
  r => console.log(JSON.stringify(r)), e => console.log(JSON.stringify({ thrown: e.message })));
'''


class DoorbellTests(unittest.TestCase):
    """The doorbell's inline code under node, with a stub of the CodeBuild client."""

    @classmethod
    def setUpClass(cls):
        code = load(ROOT / 'infra/aws/bootstrap.json')['Resources']['DoorbellFunction']['Properties']['Code']['ZipFile']
        cls.directory = tempfile.TemporaryDirectory()
        cls.code, cls.harness = Path(cls.directory.name, 'index.js'), Path(cls.directory.name, 'run.js')
        cls.code.write_text(code, encoding='utf-8')
        cls.harness.write_text(HARNESS, encoding='utf-8')
        toolchain = ROOT / '.toolchain' / 'bin' / 'node'
        cls.node = str(toolchain) if toolchain.exists() else 'node'

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.pending = Path(self.directory.name, 'ring-pending')  # RING-QUEUE: the SSM parameter, as a file
        self.built = Path(self.directory.name, 'built')
        self.pending.unlink(missing_ok=True)
        self.built.unlink(missing_ok=True)

    def call(self, event, running=False, **more):
        env = {**os.environ, 'PROJECT': 'tower-infra-deploy', 'TOKEN_SHA256': '0' * 63 + '1', 'PENDING': str(self.pending),
               'BUILT': str(self.built), **more}
        if running:
            env['RUNNING'] = '1'
        done = subprocess.run([self.node, str(self.harness), str(self.code), json.dumps(event)], capture_output=True,
                              text=True, env=env, timeout=30, check=True)
        return json.loads(done.stdout)

    def test_a_direct_invocation_needs_no_token_and_starts_the_build(self):
        answer = self.call({'source': 'autodeploy'})
        self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (202, {'build': 'tower-infra-deploy:abc'}))

    def test_a_direct_invocation_is_refused_with_409_while_a_build_runs(self):
        self.assertEqual(self.call({'source': 'autodeploy'}, running=True)['statusCode'], 409)

    def ended(self, status='SUCCEEDED'):
        return {'source': 'aws.codebuild', 'detail-type': 'CodeBuild Build State Change',
                'detail': {'project-name': 'tower-infra-deploy', 'build-status': status}}

    def test_a_409_while_a_build_runs_is_queued_and_that_builds_end_starts_it(self):
        # RING-QUEUE (POLL-scripts-lib-deploy-py-ring-until-free): the refused ring stays pending in SSM, the push job
        # stops ringing, and DeployStateRule's event of the running build's end starts the next build
        for busy in ('AccountLimitExceededException', 'ResourceAlreadyExistsException'):
            self.pending.unlink(missing_ok=True)
            answer = self.call({'source': 'autodeploy'}, running=True, RUNNING_AS=busy)
            self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (409, {'error': busy, 'queued': True}))
            self.assertTrue(self.pending.exists())
        self.assertEqual(self.call(self.ended('IN_PROGRESS')), {'statusCode': 204})  # a start is no end
        self.assertTrue(self.pending.exists())
        self.assertFalse(self.built.exists())
        answer = self.call(self.ended('FAILED'))
        self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (202, {'build': 'tower-infra-deploy:abc'}))
        self.assertFalse(self.pending.exists())
        self.assertTrue(self.built.exists())

    def test_a_builds_end_with_nothing_pending_starts_nothing(self):
        for status in ('SUCCEEDED', 'FAILED', 'FAULT', 'STOPPED', 'TIMED_OUT'):
            self.assertEqual(self.call(self.ended(status)), {'statusCode': 204}, status)
        self.assertFalse(self.built.exists())

    def test_a_pending_start_refused_at_a_builds_end_stays_pending_and_throws_for_lambdas_retry(self):
        self.pending.write_text('2026-11-19T00:00:00Z')
        answer = self.call(self.ended(), running=True)
        self.assertIn('queued', answer['thrown'])
        self.assertTrue(self.pending.exists())

    def test_another_refusal_is_a_409_that_queues_nothing(self):
        answer = self.call({'source': 'autodeploy'}, running=True, RUNNING_AS='AccessDeniedException')
        self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (409, {'error': 'AccessDeniedException'}))
        self.assertFalse(self.pending.exists())

    def test_a_url_call_dressed_as_a_builds_end_still_needs_the_token(self):
        self.pending.write_text('2026-11-19T00:00:00Z')
        self.assertEqual(self.call({**self.ended(), 'requestContext': {}, 'headers': {}})['statusCode'], 401)
        self.assertFalse(self.built.exists())

    def test_the_function_url_without_or_with_a_wrong_token_is_still_401(self):
        url = {'requestContext': {'http': {'method': 'POST'}}, 'headers': {}}
        self.assertEqual(self.call(url)['statusCode'], 401)
        self.assertEqual(self.call({**url, 'headers': {'authorization': 'Bearer nope'}})['statusCode'], 401)
        self.assertEqual(self.call({'headers': {'authorization': 'Bearer nope'}})['statusCode'], 401)
        self.assertEqual(self.call({'requestContext': {}, 'body': '{"source":"autodeploy"}'})['statusCode'], 401)

    def test_the_function_url_with_the_right_token_starts_the_build_and_409s_when_running(self):
        import hashlib
        token = 'secret-of-the-test'
        env = {**os.environ, 'PROJECT': 'p', 'TOKEN_SHA256': hashlib.sha256(token.encode()).hexdigest(),
               'PENDING': str(self.pending)}
        event = {'requestContext': {}, 'headers': {'authorization': f'Bearer {token}'}}
        for running, want in ((False, 202), (True, 409)):
            run = dict(env, **({'RUNNING': '1'} if running else {}))
            done = subprocess.run([self.node, str(self.harness), str(self.code), json.dumps(event)], capture_output=True,
                                  text=True, env=run, timeout=30, check=True)
            self.assertEqual(json.loads(done.stdout)['statusCode'], want)

    def queue_call(self, body, fails=False, encoded=False):
        """QUEUE-RELOAD: a Function URL call with the right token and this body: (answer, the port's invocation or None)."""
        import base64
        import hashlib
        token = 'secret-of-the-test'
        invoked = Path(self.directory.name, 'invoked.json')
        invoked.unlink(missing_ok=True)
        env = {**os.environ, 'PROJECT': 'p', 'TOKEN_SHA256': hashlib.sha256(token.encode()).hexdigest(),
               'PORT': 'tower-port-api:live', 'INVOKED': str(invoked), **({'PORT_FAILS': '1'} if fails else {})}
        raw = json.dumps(body)
        event = {'requestContext': {}, 'headers': {'authorization': f'Bearer {token}'},
                 'body': base64.b64encode(raw.encode()).decode() if encoded else raw, 'isBase64Encoded': encoded}
        done = subprocess.run([self.node, str(self.harness), str(self.code), json.dumps(event)], capture_output=True,
                              text=True, env=env, timeout=30, check=True)
        return json.loads(done.stdout), (json.loads(invoked.read_text()) if invoked.exists() else None)

    def test_a_queue_word_goes_to_the_port_alias_and_starts_no_build(self):
        sha = 'a' * 40
        for encoded in (False, True):
            answer, invoked = self.queue_call({'event': 'landed', 'sha': sha}, encoded=encoded)
            self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (202, {'queue': 'landed', 'sha': sha}))
            self.assertEqual(invoked, {'name': 'tower-port-api:live', 'payload': {
                'source': 'tower.doorbell', 'detail-type': 'Merge Queue', 'detail': {'event': 'landed', 'sha': sha}}})
        self.assertEqual(self.queue_call({'event': 'prepare', 'sha': sha}, fails=True)[0]['statusCode'], 502)

    def test_a_queue_word_that_is_not_one_is_refused_and_invokes_nothing(self):
        for body in ({'event': 'deploy', 'sha': 'a' * 40}, {'event': 'landed', 'sha': 'main'}, {'event': 'landed'}):
            answer, invoked = self.queue_call(body)
            self.assertEqual((answer['statusCode'], invoked), (400, None), body)

    def hook_call(self, body, event='push', signed_with='hook-secret-of-the-test', encoded=False, twice=False, signature=None):
        """GITHUB-HOOK (POLL-scripts-lib-deploy-py-queue): GitHub's delivery to the Function URL, signed with signed_with
        (X-Hub-Signature-256, the raw body's HMAC-SHA256), no bearer: (answer, the port's invocation or None, secret reads)."""
        import base64
        import hmac
        invoked, reads = Path(self.directory.name, 'invoked.json'), Path(self.directory.name, 'hook-reads')
        invoked.unlink(missing_ok=True)
        reads.unlink(missing_ok=True)
        raw = json.dumps(body).encode()
        mac = 'sha256=' + hmac.new(signed_with.encode(), raw, 'sha256').hexdigest()
        env = {**os.environ, 'PROJECT': 'p', 'TOKEN_SHA256': '0' * 63 + '1', 'PORT': 'tower-port-api:live',
               'INVOKED': str(invoked), 'HOOK_READS': str(reads), 'HOOK_SECRET': 'hook-secret-of-the-test',
               'BUILT': str(self.built), 'PENDING': str(self.pending), **({'TWICE': '1'} if twice else {})}
        request = {'requestContext': {'http': {'method': 'POST'}},
                   'headers': {'x-github-event': event, 'x-hub-signature-256': mac if signature is None else signature,
                               'content-type': 'application/json'},
                   'body': base64.b64encode(raw).decode() if encoded else raw.decode(), 'isBase64Encoded': encoded}
        done = subprocess.run([self.node, str(self.harness), str(self.code), json.dumps(request)], capture_output=True,
                              text=True, env=env, timeout=30, check=True)
        return (json.loads(done.stdout), json.loads(invoked.read_text()) if invoked.exists() else None,
                len(reads.read_text().splitlines()) if reads.exists() else 0)

    def test_a_signed_push_to_main_is_the_queues_landed_with_no_token_and_no_build(self):
        sha = 'b' * 40
        for encoded in (False, True):
            answer, invoked, reads = self.hook_call({'ref': 'refs/heads/main', 'after': sha, 'deleted': False}, encoded=encoded)
            self.assertEqual((answer['statusCode'], json.loads(answer['body'])), (202, {'queue': 'landed', 'sha': sha}))
            self.assertEqual(invoked, {'name': 'tower-port-api:live', 'payload': {
                'source': 'tower.doorbell', 'detail-type': 'Merge Queue', 'detail': {'event': 'landed', 'sha': sha}}})
            self.assertEqual(reads, 1)
        self.assertFalse(self.built.exists())

    def test_the_hook_secret_is_read_once_per_container(self):
        answers, _, reads = self.hook_call({'ref': 'refs/heads/main', 'after': 'b' * 40, 'deleted': False}, twice=True)
        self.assertEqual([each['statusCode'] for each in answers], [202, 202])
        self.assertEqual(reads, 1)

    def test_a_wrong_or_malformed_signature_is_401_and_invokes_nothing(self):
        body = {'ref': 'refs/heads/main', 'after': 'b' * 40, 'deleted': False}
        for kind in ({'signed_with': 'another-secret'}, {'signature': ''}, {'signature': 'sha256=' + 'b' * 64},
                     {'signature': 'sha1=nope'}):
            answer, invoked, _ = self.hook_call(body, **kind)
            self.assertEqual((answer['statusCode'], invoked), (401, None), kind)
        self.assertFalse(self.built.exists())

    def test_anything_else_signed_is_a_204_that_invokes_nothing(self):
        sha = 'b' * 40
        for body, event in (({'zen': 'hi', 'hook_id': 713861741}, 'ping'),
                            ({'ref': 'refs/heads/gh-readonly-queue/main/pr-1-x', 'after': sha, 'deleted': False}, 'push'),
                            ({'ref': 'refs/heads/main', 'after': '0' * 40, 'deleted': True}, 'push'),
                            ({'ref': 'refs/heads/main', 'after': sha, 'deleted': False}, 'pull_request')):
            answer, invoked, _ = self.hook_call(body, event=event)
            self.assertEqual((answer, invoked), ({'statusCode': 204}, None), (body, event))
        self.assertFalse(self.built.exists())


if __name__ == '__main__':
    unittest.main()
