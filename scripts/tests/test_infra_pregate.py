"""PRE-GATE (docs/operations/aws.md 22.9): at each push of a unit branch the live service asks the runner for the gate's
plan with the check jobs' bodies and makes them, memoized by content, so the delivery's gate is answered by the cache.
Hermetic: the look's statements are answered by a fake database."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import branches, pregate  # noqa: E402
import gate_infra  # noqa: E402

REPO = pregate.REPO
HEAD, BASE = 'a' * 40, 'b' * 40


def pushed(ref, after, repo=REPO):
    owner, name = repo.split('/')
    return json.dumps({'repository': {'name': name, 'owner': {'slug': owner}},
                       'refUpdates': [{'ref': ref, 'after': after, 'deleted': False}]})


class Db:
    def __init__(self, events, jobs=(), pr_events=(), recent=(), premerged=()):
        self.events, self.jobs, self.said, self.pr_events = list(events), list(jobs), [], list(pr_events)
        self.recent, self.premerged, self.asked = list(recent), list(premerged), []

    def rows(self, sql, params=None):
        if sql == pregate.RECENT:
            return [(body,) for body in self.recent]
        if sql == pregate.PREMERGED:
            found, self.premerged = self.premerged, []
            return found
        if sql == branches.SAY:
            self.asked.append(json.loads(params['payload']))
            return [('platform.forge.branch_merge',)]
        if sql == pregate.EVENTS:
            found, self.events = self.events, []
            return found
        if sql == pregate.PR_EVENTS:
            found, self.pr_events = self.pr_events, []
            return found
        if sql == pregate.BASE:
            return [(json.dumps([{'ref': 'refs/heads/mod/roadmap-integration', 'after': BASE}]),)]
        if sql == pregate.TENANT_ID:
            return [('t-1',)]
        if sql == pregate.JOBS:
            return self.jobs
        if sql == pregate.SAID:
            self.said.append(json.loads(params['payload']))
            return []
        raise AssertionError(sql)


class ThePregate(unittest.TestCase):
    def setUp(self):
        self.made = []

        def create(db, who, body):
            self.made.append((who, body))
            return {'id': f'job-{len(self.made)}', 'created': True}
        self.pregate = pregate.Pregate(tenant='the-tenant', clock=lambda: 1000.0, create=create)

    def test_a_unit_push_asks_the_runner_for_the_plan_with_the_jobs_the_delivery_will_make(self):
        db = Db([('e1', 990.0, pushed('refs/heads/units/x', HEAD)), ('e2', 991.0, pushed('refs/heads/mod/roadmap-integration', BASE)),
                 ('e3', 992.0, pushed('refs/heads/units/y', HEAD, repo='o/r'))])
        self.assertEqual(self.pregate.follow(db), 1)
        (who, body), = self.made
        self.assertEqual(who, ('tenant', 't-1'))
        self.assertEqual(body['input_digest'], gate_infra.digest('gate-plan', HEAD, BASE))  # the delivery's plan job's
        # GATE-OUTRANKS-PREGATE: the delivery's plan job's body, ranked under every delivery's job
        self.assertEqual((body['memoize'], body['rank']),
                         (True, gate_infra.RANK_PER_CHECK * gate_infra.RANK_CAP - pregate.PREGATE_DROP))
        self.assertLessEqual(body['rank'], 0)
        command = json.loads(__import__('base64').b64decode(body['input_uri'].split(',', 1)[1]))['command']
        self.assertEqual(command, ['scripts/gate-check', 'plan', 'jobs', '--base', BASE])
        self.assertEqual(self.pregate.follow(Db([('e1', 990.0, pushed('refs/heads/units/x', HEAD))])), 0)  # seen

    def test_the_answered_jobs_are_made_and_a_plan_without_them_is_said_skipped(self):
        self.pregate.planning = {'job-1': ('units/x', HEAD, BASE), 'job-2': ('units/z', 'c' * 40, BASE)}
        answer = {'answer': {'plan': {}, 'jobs': [{'name': 'test:a', 'body': {'memoize': True, 'input_digest': 'sha256:a',
                                                                                'rank': 998012}},
                                                  {'name': 'artifact:lambda', 'body': {'memoize': False, 'input_digest': 'x'}}]}}
        db = Db([], jobs=[('job-1', 'succeeded', json.dumps(answer)), ('job-2', 'failed', json.dumps({}))])
        self.assertEqual(self.pregate.settle(db), 1)
        self.assertEqual([body['input_digest'] for _, body in self.made], ['sha256:a'])  # a side effect is not pre-run
        self.assertEqual(self.made[0][1]['rank'], 998012 - pregate.PREGATE_DROP)  # GATE-OUTRANKS-PREGATE: under the gate's
        self.assertEqual({said['state'] for said in db.said}, {'made', 'skipped'})
        self.assertEqual(self.pregate.planning, {})

    def test_a_look_that_starts_reads_only_the_last_two_minutes(self):
        # PREGATE-WINDOW: an hour's pushes, read at the service's start after #650's deploy, planned delivered heads
        db = Db([])
        asked = []
        db.rows = (lambda rows: lambda sql, params=None: asked.append(params) or ([] if sql == pregate.EVENTS else rows(sql, params)))(db.rows)
        self.pregate.follow(db)
        self.assertEqual(asked[0], {'since': 1000.0 - pregate.WINDOW_S})
        self.assertLessEqual(pregate.WINDOW_S, 120.0)

    def test_a_pr_opened_or_pushed_is_pre_observed_by_its_number_and_head(self):
        # OBSERVE-ON-PUSH: `pr metadata` at the delivery finds the observation done
        asked = []
        self.pregate.observe = lambda db, who, body: asked.append(body)
        pr = lambda number, head, state='open', merged=False: json.dumps({
            'repository': {'name': 'open-university', 'owner': {'slug': 'openuniversity-si'}},
            'pullRequest': {'number': number, 'head': {'ref': 'units/x', 'sha': head}, 'state': state, 'merged': merged}})
        db = Db([], pr_events=[('p1', 990.0, pr('7', HEAD)), ('p2', 991.0, pr('8', 'c' * 40, state='closed')),
                               ('p3', 992.0, pr('9', 'd' * 40, merged=True))])
        self.assertEqual(self.pregate.preobserve(db), 1)
        self.assertEqual(asked, [{'pr': 7, 'head': HEAD}])  # closed and merged are not pre-observed
        self.assertEqual(self.pregate.preobserve(Db([], pr_events=[('p1', 990.0, pr('7', HEAD))])), 0)  # seen

    def test_the_base_moving_asks_a_premerge_of_the_newest_unit_heads_it_does_not_hold(self):
        # PREMERGE (the Torre, 13/11): #678 was behind the base and its delivery merged (85.5 s) and judged the combination
        # (47 s); the combination is now merged and pre-gated when the base moves, on a ref of its own
        moved = 'c' * 40
        recent = [pushed(f'refs/heads/units/u{n}', str(n) * 40) for n in range(6)] + [
            pushed('refs/heads/units/u0', 'f' * 40), pushed('refs/heads/units/y', 'e' * 40, repo='o/r'),
            pushed('refs/heads/mod/roadmap-integration', moved)]
        db = Db([('e1', 995.0, pushed('refs/heads/units/u5', '9' * 40)), ('e2', 996.0, pushed('refs/heads/mod/roadmap-integration', moved))],
                recent=recent)
        self.pregate.follow(db)
        asked = [(each['branch'], each['head']) for each in db.asked]
        # the newest four of the window (u0 pushed again, last); u5 was pushed in this very look: planned on the base already
        self.assertEqual(asked, [('units/u3', '3' * 40), ('units/u4', '4' * 40), ('units/u0', 'f' * 40)])
        self.assertEqual({(each['state'], each['premerge'], each['onto'], each['base']) for each in db.asked},
                         {('asked', True, moved, 'mod/roadmap-integration')})

    def test_a_premerge_pushed_is_planned_like_a_push_of_its_ref(self):
        merged, onto = 'd' * 40, 'c' * 40
        said = json.dumps({'state': 'premerged', 'sha': merged, 'onto': onto, 'ref': f'premerge/units/x/{onto[:12]}',
                           'branch': 'units/x', 'head': HEAD})
        db = Db([], premerged=[('m1', 995.0, said), ('m2', 996.0, json.dumps({'state': 'premerged', 'sha': 'zz'}))])
        self.assertEqual(self.pregate.premerged(db), 1)
        (_, body), = self.made
        spec = json.loads(__import__('base64').b64decode(body['input_uri'].split(',', 1)[1]))
        self.assertEqual((spec['commit'], spec['ref'], spec['base']), (merged, f'refs/heads/premerge/units/x/{onto[:12]}', onto))
        self.assertEqual(body['input_digest'], gate_infra.digest('gate-plan', merged, onto))  # the delivery's, same commit
        self.assertEqual(self.pregate.premerged(Db([], premerged=[('m1', 995.0, said)])), 0)  # seen

    def test_its_digest_is_the_gates(self):
        self.assertEqual(pregate.digest('gate-plan', HEAD, BASE), gate_infra.digest('gate-plan', HEAD, BASE))


URL = __import__('os').environ.get('TEST_DATABASE_URL', '')


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """PREGATE-WAKE: the real trigger: a PR opened or its head pushed wakes the pre-gate's look (tower_deploy) at once."""

    def setUp(self):
        from infra_db import psql
        import test_db
        name, self.db = psql.migrated(URL)
        self.addCleanup(test_db.destroy, URL, name)

    def heard(self, kind):
        insert = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                  f"('{kind}:1', null, '{kind}', clock_timestamp(), 'ingress', 'forge/pr', '{{}}'::jsonb)")
        return self.db.call(['-A', '-t', '-f', '-'], script=f'listen tower_deploy;\n{insert};\nselect 1;\n')

    def test_a_pr_opened_or_pushed_wakes_the_look_and_another_forge_event_does_not(self):
        # #656 and #657 (13/11): delivered 20 to 35 s after their PRs opened, before any look pre-observed them
        for kind in ('forge.pull_request.created', 'forge.pull_request.head_ref.pushed', 'forge.repository.pushed'):
            self.assertIn(f'Asynchronous notification "tower_deploy" with payload "{kind}"', self.heard(kind))
        self.assertNotIn('Asynchronous notification', self.heard('forge.repository.check_run.created'))


if __name__ == '__main__':
    unittest.main()
