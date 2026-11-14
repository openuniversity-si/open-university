"""FULL-RUN (revisão da arquitetura, achado 29): at each push to the base the live service lists the landed sha's script
tests on the runner and runs each one with no cache, below the gates; a test a gate took back runs again; the sha is said
green or red, and a red one is published. Hermetic: the look's statements are answered by a fake database."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import fullrun, mechanisms, pregate  # noqa: E402

BASE = 'refs/heads/mod/roadmap-integration'
ONE, TWO = 'a' * 40, 'b' * 40


def pushed(ref, after, repo=pregate.REPO):
    owner, name = repo.split('/')
    return json.dumps({'repository': {'name': name, 'owner': {'slug': owner}},
                       'refUpdates': [{'ref': ref, 'after': after, 'deleted': False}]})


class Db:
    def __init__(self):
        self.pushes, self.states, self.said = [], {}, []

    def rows(self, sql, params=None):
        if sql == fullrun.PUSHES:
            found, self.pushes = self.pushes, []
            return found
        if sql == fullrun.TENANT_ID:
            return [('t-1',)]
        if sql == fullrun.JOBS:
            # FULL-RUN-KEEP: (state, result[, its run ended]): a job's run has ended unless the test says it has not
            return [(ident, *(tuple(self.states[ident]) + (True,))[:3]) for ident in params['ids'].split(',')
                    if ident in self.states]
        if sql == fullrun.SAID:
            self.said.append(json.loads(params['payload']))
            return []
        if sql == fullrun.STATES:  # FULL-RUN-RECOVER: what was said, newest first
            return [(json.dumps(each), float(at)) for at, each in reversed(list(enumerate(self.said)))]
        raise AssertionError(sql)


class TheFullRun(unittest.TestCase):
    def setUp(self):
        self.made, self.cancelled, self.published, self.now = [], [], [], [1000.0]

        def create(db, who, body):  # the port's: the same idempotency key answers the job it made first
            for index, each in enumerate(self.made):
                if each['idempotency_key'] == body['idempotency_key']:
                    return {'id': f'job-{index + 1}'}
            self.made.append(body)
            return {'id': f'job-{len(self.made)}'}
        self.full = fullrun.FullRun(clock=lambda: self.now[0], create=create,
                                    cancel=lambda db, who, ident: self.cancelled.append(ident),
                                    publish=lambda said, subject: self.published.append((subject, said)))
        self.db = Db()

    def body(self, key):
        return next(each for each in self.made if each['idempotency_key'] == key)

    def listed(self, sha, tests):
        self.db.states['job-1'] = ('succeeded', json.dumps({'answer': {'tests': tests}}))

    def test_a_landing_lists_its_tests_and_runs_each_with_no_cache_below_the_gates(self):
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE)), ('e2', 991.0, pushed('refs/heads/units/x', TWO))]
        self.full.step(self.db)
        listing = self.body(f'fullrun:{ONE}:list')
        spec = json.loads(__import__('base64').b64decode(listing['input_uri'].split(',', 1)[1]))
        self.assertEqual((spec['commit'], spec['command'][:2]), (ONE, ['python3', '-c']))  # the landed sha's own list
        # FULL-RUN-LIST-RANK: the list ranks as a one-check head's job and never yields (it waited 6 min behind the gates)
        self.assertEqual((listing['rank'], listing['selector']), (fullrun.LIST_RANK, {'adapter': 'container'}))
        self.listed(ONE, ['scripts/tests/a.test.sh', 'scripts/tests/b.test.sh', '../etc/x.sh'])
        self.full.step(self.db)
        tests = [each for each in self.made if each['idempotency_key'].endswith(':1')]
        self.assertEqual(len(tests), 2)  # what is no script test of the tree is not run
        for each in tests:
            self.assertEqual((each['memoize'], each['rank'], each['selector']), (False, 0, {'adapter': 'container', 'yield': True}))
            # FULL-RUN-NO-CACHE: and no store of the slot answers the test (infra-autodeploy at c8d1fa3f was a cached PASS)
            command = json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))['command']
            self.assertEqual(command[:4], ['env', 'GATE_TEST_CACHE_OFF=1', 'scripts/gate-check', 'test'])
        self.assertEqual(fullrun.SELECTOR['yield'], True)
        self.assertIn("selector ? 'yield'", mechanisms.YIELD_HELD)  # the dispatcher keys on the same word
        self.assertEqual([each['state'] for each in self.db.said], ['listing', 'running'])

    def test_the_uid_0_probe_asks_for_root_on_the_landed_sha_and_the_rest_for_the_check_user(self):
        # UID0-FROM-BASE: the full run's sha is the base's, landed; the runner gives root to it alone
        sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
        import config
        self.assertEqual(list(fullrun.ROOT_FROM_BASE), config.get('gate-infra.root_from_base_tests'))
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.listed(ONE, ['scripts/tests/uid0-probe.test.sh', 'scripts/tests/b.test.sh'])
        self.full.step(self.db)
        users = {json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))['command'][-1]:
                 json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))['user']
                 for each in self.made if each['idempotency_key'].endswith(':1')}
        self.assertEqual(users, {'scripts/tests/uid0-probe.test.sh': 'root', 'scripts/tests/b.test.sh': 'tower-check'})

    def test_a_test_a_gate_took_back_runs_again_and_the_sha_is_said_red_and_published(self):
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.listed(ONE, ['scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'])
        self.full.step(self.db)
        self.db.states.update({'job-2': ('cancelled', None), 'job-3': ('failed', None)})
        self.assertIsNone(self.full.step(self.db))  # a's run was taken back for a gate: made again
        again = self.body(f'fullrun:{ONE}:scripts/tests/a.test.sh:2')
        self.assertEqual(again['memoize'], False)
        self.db.states['job-4'] = ('succeeded', None)
        self.now[0] = 1300.0
        self.assertEqual(self.full.step(self.db), 'red')
        verdict = self.db.said[-1]
        self.assertEqual((verdict['sha'], verdict['state'], verdict['red'], verdict['retried'], verdict['n']),
                         (ONE, 'red', ['scripts/tests/b.test.sh'], ['scripts/tests/a.test.sh'], 2))
        self.assertEqual(self.published[0][0], f'tower base RED at {ONE[:12]}: scripts/tests/b.test.sh')

    def test_a_green_base_publishes_nothing_and_a_landing_while_it_runs_waits_for_it(self):
        # FULL-RUN-COALESCE: with no cache (#697) a run is longer than the time between two landings; a newer landing
        # cancelled the older run, and none ended (4c340fc4 and aaf65b73, 13/11 22:09 to 22:15 UTC, both dropped)
        three = 'c' * 40
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.listed(ONE, ['scripts/tests/a.test.sh'])
        self.full.step(self.db)
        self.db.pushes = [('e2', 995.0, pushed(BASE, TWO)), ('e3', 996.0, pushed(BASE, three))]
        self.full.step(self.db)  # TWO and three landed while ONE ran: nothing is cancelled, the newest waits
        self.assertEqual(self.cancelled, [])
        self.assertEqual([(each['state'], each['sha']) for each in self.db.said][-1:], [('waiting', three)])
        self.assertEqual(self.db.said[-1]['behind'], ONE)
        self.db.states['job-2'] = ('succeeded', None)
        self.assertEqual(self.full.step(self.db), 'green')  # ONE ends as it would; three starts
        self.assertEqual([(each['state'], each['sha']) for each in self.db.said][-2:], [('green', ONE), ('listing', three)])
        self.db.states['job-3'] = ('succeeded', json.dumps({'answer': {'tests': ['scripts/tests/a.test.sh']}}))
        self.full.step(self.db)
        self.db.states['job-4'] = ('succeeded', None)
        self.assertEqual(self.full.step(self.db), 'green')
        self.assertEqual((self.db.said[-1]['sha'], self.published), (three, []))
        self.assertNotIn(TWO, [each['sha'] for each in self.db.said])  # judged by three's run, whose tree holds it


    def test_a_restarted_service_takes_its_open_run_again_by_the_jobs_keys_and_the_waiting_sha_after_it(self):
        # FULL-RUN-RECOVER: a code landing reloads the service; the open run was its memory alone (f3d933ba at #698's
        # swap, 9b02bb50 at #699's, 13/11 22:30 and 22:34 UTC)
        three = 'c' * 40
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.listed(ONE, ['scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'])
        self.full.step(self.db)
        self.db.pushes = [('e2', 995.0, pushed(BASE, three))]
        self.full.step(self.db)  # three waits behind ONE
        made = len(self.made)
        again = fullrun.FullRun(clock=lambda: self.now[0], create=self.full.create, cancel=self.full.cancel,
                                publish=self.full.publish)  # the new process
        self.db.pushes = [('e2', 995.0, pushed(BASE, three))]  # its first look reads the last two minutes again
        again.step(self.db)
        self.assertEqual((again.sha, again.waiting), (ONE, three))
        self.assertEqual(len(self.made), made)  # no job made twice: the keys answered ONE's list and tests
        self.db.states['job-2'] = ('succeeded', None)
        self.db.states['job-3'] = ('failed', None)
        self.assertEqual(again.step(self.db), 'red')  # ONE's verdict, from the jobs the first process made
        self.assertEqual([(each['state'], each['sha']) for each in self.db.said][-2:], [('red', ONE), ('listing', three)])

    def test_a_restart_with_no_open_run_begins_the_waiting_sha_and_one_after_a_verdict_begins_nothing(self):
        self.db.said = [{'sha': ONE, 'state': 'listing'}, {'sha': ONE, 'state': 'running', 'n': 1},
                        {'sha': TWO, 'state': 'waiting', 'behind': ONE}, {'sha': ONE, 'state': 'green', 'n': 1}]
        fresh = fullrun.FullRun(clock=lambda: self.now[0], create=self.full.create, cancel=self.full.cancel)
        fresh.step(self.db)
        self.assertEqual(fresh.sha, TWO)  # ONE ended; TWO had waited and had not begun
        self.db.said.append({'sha': TWO, 'state': 'green', 'n': 1})
        done = fullrun.FullRun(clock=lambda: self.now[0], create=self.full.create, cancel=self.full.cancel)
        done.step(self.db)
        self.assertIsNone(done.sha)


    def test_a_sha_whose_gate_check_runs_batches_runs_its_tests_in_bins_and_reads_each_ones_verdict(self):
        # FULL-RUN-BATCH: 7935bd72's run, one job per test, took 1365.9 s for 1279 s of costs
        names = [f'scripts/tests/t{n}.test.sh' for n in range(30)] + ['scripts/tests/uid0-probe.test.sh']
        costs = {name: (110.0 if n < 3 else 4.0) for n, name in enumerate(names[:30])}
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.db.states['job-1'] = ('succeeded', json.dumps({'answer': {'tests': names, 'costs': costs, 'batch': True}}))
        self.full.step(self.db)
        made = {each['idempotency_key']: json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))
                for each in self.made[1:]}
        alone = made[f'fullrun:{ONE}:scripts/tests/uid0-probe.test.sh:1']
        self.assertEqual((alone['command'][2:4], alone['user']), (['scripts/gate-check', 'test'], 'root'))
        bins = [spec['command'][5].split(',') for key, spec in made.items() if ':batch-' in key]
        self.assertEqual(sorted(name for each in bins for name in each), sorted(names[:30]))
        self.assertTrue(all(len(each) <= fullrun.BATCH_MAX for each in bins))
        self.assertEqual(sorted(sum(1 for name in each if costs[name] > 100) for each in bins)[-1], 1)  # the long ones apart
        self.assertEqual({tuple(spec['command'][:5]) for key, spec in made.items() if ':batch-' in key},
                         {('env', 'GATE_TEST_CACHE_OFF=1', 'GATE_TEST_WORKERS=1', 'scripts/gate-check', 'tests')})
        ids = {key: f'job-{index + 2}' for index, key in enumerate(made)}
        first = next(key for key in made if ':batch-' in key)
        failed = made[first]['command'][5].split(',')[0]
        for key, ident in ids.items():
            if key == first:
                self.db.states[ident] = ('failed', json.dumps({'answer': {'tests': {name: 'FAIL' if name == failed else 'PASS'
                                                                                    for name in made[key]['command'][5].split(',')}}}))
            elif ':batch-' in key:
                self.db.states[ident] = ('cancelled', None)  # taken back for a gate: the batch is made again
            else:
                self.db.states[ident] = ('succeeded', None)
        self.assertIsNone(self.full.step(self.db))
        again = [each for each in self.made if each['idempotency_key'].endswith(':2')]
        self.assertEqual(len(again), len(bins) - 1)
        for index, each in enumerate(self.made):
            if each['idempotency_key'].endswith(':2'):
                spec = json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))
                self.db.states[f'job-{index + 1}'] = ('failed', json.dumps({'result': 'no answer'}))  # one with no answer: all red
                break
        for index, each in enumerate(self.made):
            if each['idempotency_key'].endswith(':2') and f'job-{index + 1}' not in self.db.states:
                spec = json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))
                self.db.states[f'job-{index + 1}'] = ('succeeded', json.dumps({'answer': {'tests': {
                    name: 'PASS' for name in spec['command'][5].split(',')}}}))
        unanswered = next(json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))['command'][5].split(',')
                          for each in self.made if each['idempotency_key'].endswith(':2'))
        self.assertIsNone(self.full.step(self.db))  # FULL-RUN-ALONE: the red and the unanswered run again, alone
        alone = {each['idempotency_key'].split(':')[2]: f'job-{index + 1}' for index, each in enumerate(self.made)
                 if each['idempotency_key'].endswith(':alone')}
        self.assertEqual(sorted(alone), sorted([failed] + unanswered))
        for test, ident in alone.items():
            self.db.states[ident] = ('failed' if test == failed else 'succeeded', None)  # red alone, or green alone
        self.assertEqual(self.full.step(self.db), 'red')
        said = self.db.said[-1]
        self.assertEqual((said['red'], said['alone']), ([failed], sorted([failed] + unanswered)))
        self.assertEqual(said['n'], 31)

    def test_a_batch_taken_back_keeps_what_its_run_answered_and_is_made_again_with_the_rest(self):
        # FULL-RUN-KEEP: at e8e66675 (13/11 23:47 to 00:14 UTC) 59 runs taken back held 1995 slot-s and 146 of the 215 tests
        # ran more than once: a batch taken back lost every test it had run
        names = [f'scripts/tests/t{n}.test.sh' for n in range(6)]
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.db.states['job-1'] = ('succeeded', json.dumps({'answer': {'tests': names, 'costs': {}, 'batch': True}}))
        self.full.step(self.db)
        self.assertEqual(len(self.made), 2)  # one batch of the six (6 x 5 s of cost, under BATCH_S)
        first = names[:]
        self.db.states['job-2'] = ('cancelled', None, False)  # taken back; its run has not ended yet
        self.assertIsNone(self.full.step(self.db))
        self.assertEqual(len(self.made), 2)  # nothing made until the run's answer is in
        said = {first[0]: 'PASS', first[1]: 'PASS', first[2]: 'FAIL'}
        self.db.states['job-2'] = ('cancelled', json.dumps({'exit': None, 'answer': {'tests': said}}), True)
        self.assertIsNone(self.full.step(self.db))
        made = {each['idempotency_key']: json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))
                for each in self.made}
        self.assertEqual(made[f'fullrun:{ONE}:batch-0:2']['command'][5].split(','), first[3:])  # the rest alone runs again
        self.assertIn(f'fullrun:{ONE}:{first[2]}:alone', made)  # red in the batch: alone (FULL-RUN-ALONE)
        ids = {each['idempotency_key']: f'job-{index + 1}' for index, each in enumerate(self.made)}
        self.db.states[ids[f'fullrun:{ONE}:batch-0:2']] = ('cancelled', json.dumps({'answer': {'tests': {
            name: 'PASS' for name in first[3:]}}}))  # taken back again, after its last test ended
        self.db.states[ids[f'fullrun:{ONE}:{first[2]}:alone']] = ('succeeded', None)
        self.assertEqual(self.full.step(self.db), 'green')  # every test answered: the batch is not made a third time
        verdict = self.db.said[-1]
        self.assertEqual((verdict['n'], verdict['kept'], verdict['alone'], verdict['red']), (6, 5, [first[2]], []))
        self.assertFalse([key for key in (each['idempotency_key'] for each in self.made) if key.endswith(':3')])

    def test_a_batch_command_run_again_is_asked_only_its_unanswered_tests(self):
        self.full.batches, self.full.left = {'batch-0': ['a', 'b', 'c']}, {'batch-0': ['c']}
        self.assertEqual(self.full.command('batch-0')[-1], 'c')
        self.assertEqual(self.full.command('batch-0')[:5],
                         ['env', 'GATE_TEST_CACHE_OFF=1', 'GATE_TEST_WORKERS=1', 'scripts/gate-check', 'tests'])

    def test_a_test_the_last_run_ran_alone_runs_alone_from_the_start_of_the_next(self):
        # FULL-RUN-ALONE-LEARNED: infra-intask-standby was red in its batch and green alone in each of 917f5806, b433350f and
        # ae1fc73c (14/11 00:14 to 00:53 UTC); its batch red in 131 s at e8e66675
        names = [f'scripts/tests/t{n}.test.sh' for n in range(4)]
        listed = json.dumps({'answer': {'tests': names, 'costs': {}, 'batch': True}})

        def keys():
            return {each['idempotency_key']: json.loads(__import__('base64').b64decode(each['input_uri'].split(',', 1)[1]))
                    for each in self.made}

        def ident(key):
            return f'job-{[each["idempotency_key"] for each in self.made].index(key) + 1}'
        self.db.pushes = [('e1', 990.0, pushed(BASE, ONE))]
        self.full.step(self.db)
        self.db.states[ident(f'fullrun:{ONE}:list')] = ('succeeded', listed)
        self.full.step(self.db)
        self.db.states[ident(f'fullrun:{ONE}:batch-0:1')] = ('failed', json.dumps({'answer': {'tests': {
            name: 'FAIL' if name == names[1] else 'PASS' for name in names}}}))
        self.full.step(self.db)
        self.db.states[ident(f'fullrun:{ONE}:{names[1]}:alone')] = ('succeeded', None)  # green alone
        self.assertEqual(self.full.step(self.db), 'green')
        self.assertEqual(self.db.said[-1]['alone'], [names[1]])
        self.db.pushes = [('e2', 995.0, pushed(BASE, TWO))]
        self.full.step(self.db)
        self.db.states[ident(f'fullrun:{TWO}:list')] = ('succeeded', listed)
        self.full.step(self.db)
        made = keys()
        self.assertEqual(made[f'fullrun:{TWO}:{names[1]}:1']['command'][2:4], ['scripts/gate-check', 'test'])  # alone at once
        self.assertEqual(made[f'fullrun:{TWO}:batch-0:1']['command'][5].split(','), [names[0], names[2], names[3]])
        # a new process (a reload) learns it from the log's newest verdict
        again = fullrun.FullRun(clock=lambda: self.now[0], create=self.full.create, cancel=self.full.cancel)
        again.step(self.db)
        self.assertEqual(again.learned, {names[1]})

    def test_the_list_command_names_the_costs_and_whether_the_sha_runs_batches(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'answer.json'
            subprocess.run(fullrun.LIST, cwd=ROOT, env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)}, check=True)
            said = json.loads(answer.read_text())
        self.assertTrue(said['batch'])  # this tree's gate-check has `tests`
        self.assertIn('scripts/tests/infra-fullrun.test.sh', said['tests'])
        self.assertGreater(sum(said['costs'].values()), 0)


if __name__ == '__main__':
    unittest.main()
