"""FULL-RUN (revisão da arquitetura, achado 29; the Torre's item 3 of 13/11 12:10 BRT): every script test of the base, run
whole and with no cache at each landing, below the gates, the result bound to the landed sha.

A gate runs the tests its covers select and answers the rest from the cache, keyed by what each test covers: a test can
go red on the base for something its covers do not name (a clock, a tool, a neighbour's fixture) and no gate sees it. So
at each push to the base (forge.repository.pushed, a merge: in the log within a second, notified on tower_deploy) the live
service asks the runner for the list of the landed sha's script tests (a job that lists them from its own checkout, in its
answer file) and makes one job per test: memoize false (no cache answers it, none is written), the lowest rank of the
checks' queue and `yield` in its selector, so the dispatcher never starts one while a gate's job waits and takes one back
(cancelled, never failed) when a gate's job finds no free slot (mechanisms.YIELD_HELD, mechanisms.PREEMPT): by the event of
a job that cannot go, never by a clock. A test taken back is made again, as a new job, until it ran. When every test of
the sha ran, platform.gate.full {sha, state: green|red, red, n, seconds} is said, and a red one is published to the
platform's topic. One full run at a time, no cost on top of the runner that is there. FULL-RUN-COALESCE: a landing while
one runs waits for it (platform.gate.full {state: waiting, behind}) and the newest landed sha starts when it ends; the shas
landed in between are judged by it, as their tree is in its. (A newer landing took over, cancelling the older run: with no
cache, #697, a run is longer than the time between two landings, and none ended: 4c340fc4 and aaf65b73, 13/11 22:09 to
22:15 UTC, both dropped.)
"""
import json
import logging
import re
import time

from .pregate import ENDED, REPO, SHA, TENANT_ID, digest, encode, ours

LOG = logging.getLogger('tower_infra.fullrun')
QUEUE, RANK, TIMEOUT_S = 'checks', 0, 900  # the checks' queue; below every gate's and pre-gate's rank; gate-infra's timeout
SELECTOR = {'adapter': 'container', 'yield': True}  # mechanisms: never ahead of a waiting gate, taken back for one
# FULL-RUN-LIST-RANK: the list job (a glob, under a second) ranks as a one-check head's job and never yields: at the
# lowest rank with yield it waited behind every gate's and pre-gate's job, 6 min at 7935bd72 (13/11 22:34:15 to 22:40:20
# UTC) and 5.5 at f3d933ba (22:15:41 to 22:21:09), the run's tests not yet made
LIST_RANK, LIST_SELECTOR = 999000, {'adapter': 'container'}
PUSHES = ("select event_id, extract(epoch from occurred_at)::float8, (payload #> '{delivery,event,payload}')::text "
          "from log.event where type = 'forge.repository.pushed' and occurred_at > to_timestamp(%(since)s::float8) "
          "order by occurred_at")
# FULL-RUN-KEEP: and whether its run ended (no lease): a job taken back has its run's answer only once that run ended
JOBS = ("select id::text, state, result::text, lease_run_id is null from work.job "
        "where id = any(string_to_array(%(ids)s, ',')::uuid[])")
SAID = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        "select %(id)s, null, 'platform.gate.full', clock_timestamp(), 'fullrun', 'gate/full', %(payload)s::jsonb "
        "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.gate.full')")
# the list of the sha's script tests, written by a command of its own checkout to the runner's answer file
# FULL-RUN-BATCH: and the tests' costs (scripts/tests/costs.json) and whether the sha's gate-check runs a batch (`tests`)
LIST = ['python3', '-c', "import glob, json, os; tests = sorted(glob.glob('scripts/tests/*.test.sh')); "
                         "costs = json.load(open('scripts/tests/costs.json')) if os.path.exists('scripts/tests/costs.json') else {}; "
                         "json.dump({'tests': tests, 'costs': {k: v for k, v in costs.items() if k in tests and "
                         "isinstance(v, (int, float))}, 'batch': '  tests)' in open('scripts/gate-check').read()}, "
                         "open(os.environ['TOWER_ANSWER_FILE'], 'w'))"]
# FULL-RUN-BATCH (the Torre's item 3 of 13/11 22:59Z): the first uncached run, 7935bd72, took 1365.9 s: 215 jobs, one
# `gate-check test` each, 3878 slot-s of the four slots' 5464 (645 of them lost in 67 runs taken back for gates), against
# 1279 s of costs. A batch of tests, longest first into bins of about BATCH_S of cost (BATCH_MAX tests at most), runs in
# one `gate-check tests` (one start, the fork server, the jobserver) and answers each test's PASS or FAIL; a batch taken
# back loses one batch. A sha whose gate-check has no `tests` runs one job per test, as before
BATCH_S, BATCH_MAX = 60.0, 12
# FULL-RUN-KEEP: a batch taken back for a gate lost every test it had run: at e8e66675 (13/11 23:47 to 00:14 UTC) 59 runs
# taken back held 1995 slot-s (one 444 s), and 146 of the 215 tests ran more than once, the run 1618.2 s. The batch's
# gate-check says each test's verdict in the answer file as it ends (gate_test_cache --progress); the runner hands a
# cancelled run's answer to the job as any other's. The batch made again runs only the tests it had not answered: a PASS
# is kept, a FAIL runs alone (FULL-RUN-ALONE)


def batches(tests, costs):
    """The tests in bins: longest first, each to the bin with the least cost so far (LPT), about BATCH_S a bin."""
    weigh = {name: float(costs.get(name) or 5.0) for name in tests}
    count = max(1, round(sum(weigh.values()) / BATCH_S), -(-len(tests) // BATCH_MAX))
    bins = [[0.0, []] for _ in range(count)]
    for name in sorted(tests, key=lambda each: (-weigh[each], each)):
        open_ = [each for each in bins if len(each[1]) < BATCH_MAX] or bins
        chosen = min(open_, key=lambda each: each[0])
        chosen[0] += weigh[name]
        chosen[1].append(name)
    return [sorted(names) for _, names in bins if names]
TEST = re.compile(r'^scripts/tests/[A-Za-z0-9_.-]+\.test\.sh$')
# UID0-FROM-BASE: gate-infra.root_from_base_tests' default (the registry is the gate's; test_infra_fullrun holds them equal)
ROOT_FROM_BASE = ('scripts/tests/uid0-probe.test.sh',)
OVERLAP_S, WINDOW_S = 5.0, 120.0  # pregate's: a look that starts reads the last two minutes only
# FULL-RUN-RECOVER: the run a process had open was its memory alone; a code landing reloads the service, and the run went
# with it (f3d933ba at #698's swap, 13/11 22:30 UTC; 9b02bb50 at #699's, 22:34): with landings minutes apart none ended.
# A process that starts reads the day's states back: the open run (listing or running, with no verdict) is taken again by
# its jobs' keys (the same key answers the same job), and the sha waiting behind it waits again
ENDS = ('green', 'red', 'skipped', 'dropped')
# FULL-RUN-ALONE-LEARNED: a test the last run had to run alone (red in its batch, FULL-RUN-ALONE) runs alone from the start:
# infra-intask-standby was red in its batch and green alone in each of 917f5806, b433350f and ae1fc73c (14/11 00:14 to 00:53
# UTC), and its batch red in 131 s at e8e66675. The last verdict's `alone` (this process's, or the log's after a restart),
# LEARNED_MAX at most
LEARNED_MAX = 12
STATES = ("select payload::text, extract(epoch from occurred_at)::float8 from log.event where type = 'platform.gate.full' "
          "and tenant_id is null and occurred_at > now() - interval '1 day' order by occurred_at desc limit 200")


class FullRun:
    def __init__(self, base_branch='mod/roadmap-integration', repo=REPO, tenant=None, clock=time.time, create=None,
                 cancel=None, publish=None):
        from . import config_data, port
        self.base_branch, self.repo, self.clock = base_branch, repo, clock
        self.tenant = tenant or config_data.TENANT
        self.create, self.cancel = create or port.create_job, cancel or port.cancel_job
        self.publish = publish
        self.since, self.seen = None, {}
        self.sha, self.listing, self.tests, self.began = None, None, {}, None  # tests: name -> [job id, try]
        self.batches = {}  # FULL-RUN-BATCH: batch label -> its tests
        self.alone = set()  # FULL-RUN-ALONE: the tests a batch had red, run again alone
        self.left, self.kept, self.finished = {}, set(), set()  # FULL-RUN-KEEP: a batch's tests not answered yet; those
        # a taken-back run answered PASS; the batches every test of which a taken-back run answered
        self.waiting = None  # FULL-RUN-COALESCE: the newest landed sha behind the open run
        self.recovered = False  # FULL-RUN-RECOVER: the day's states read back once, at the first look
        self.learned = set()  # FULL-RUN-ALONE-LEARNED: the tests the last verdict ran alone

    def who(self, db):
        return ('tenant', db.rows(TENANT_ID, {'tenant': self.tenant})[0][0])

    def say(self, db, state, sha=None, **payload):
        sha = sha or self.sha
        db.rows(SAID, {'id': f'fullrun:{sha}:{state}', 'payload': json.dumps({'sha': sha, 'state': state, **payload})})

    def command(self, name):
        """A test's command, or a batch's (FULL-RUN-BATCH): no store of the slot answers it (FULL-RUN-NO-CACHE)."""
        if name in self.batches:
            # FULL-RUN-BATCH-ONE: one test at a time in the slot, the start shared, the slot's CPU each test's
            names = self.left.get(name, self.batches[name])  # FULL-RUN-KEEP: what a taken-back run did not answer
            return ['env', 'GATE_TEST_CACHE_OFF=1', 'GATE_TEST_WORKERS=1', 'scripts/gate-check', 'tests', ','.join(names)]
        return ['env', 'GATE_TEST_CACHE_OFF=1', 'scripts/gate-check', 'test', name]

    def job(self, db, name, command, key, listing=False):
        # CHECK-NOT-ROOT: the base's whole battery as the check user, so each landing proves it before the runner's default
        # becomes that user (a test that needs root says so here, red, with no gate of a PR at stake)
        spec = {'repo': self.repo, 'ref': f'refs/heads/{self.base_branch}', 'commit': self.sha, 'base': self.sha,
                'timeout_s': TIMEOUT_S, 'command': command,
                # UID0-FROM-BASE: a test that needs a real uid 0 process asks for root; the sha is the base's, landed
                'user': 'root' if name in ROOT_FROM_BASE else 'tower-check'}
        return self.create(db, self.who(db), {
            'queue': QUEUE, 'rank': LIST_RANK if listing else RANK, 'selector': LIST_SELECTOR if listing else SELECTOR,
            'memoize': False, 'input_uri': encode(spec),
            'input_digest': digest('full-run', self.sha, name), 'idempotency_key': key})['id']

    def follow(self, db):
        """The base's newest push since the last look: its full run starts, and an older one still open is dropped."""
        since = self.since if self.since is not None else self.clock() - WINDOW_S
        newest, ref = None, f'refs/heads/{self.base_branch}'
        for event, at, body in db.rows(PUSHES, {'since': since}):
            self.since = max(self.since or since, float(at) - OVERLAP_S)
            if event in self.seen:
                continue
            self.seen[event] = float(at)
            body = json.loads(body or 'null') or {}
            if not ours(body, self.repo):
                continue
            for update in body.get('refUpdates') or []:
                after = str(update.get('after') or '')
                if update.get('ref') == ref and not update.get('deleted') and SHA.match(after) and set(after) != {'0'}:
                    newest = after
        self.since = since if self.since is None else self.since
        self.seen = {event: at for event, at in self.seen.items() if at > self.since}
        if newest is None or newest in (self.sha, self.waiting):
            return None
        if self.sha is not None:  # FULL-RUN-COALESCE: it waits for the open run, which ends as it would
            self.waiting = newest
            self.say(db, 'waiting', sha=newest, behind=self.sha)
            return None
        return self.begin(db, newest)

    def begin(self, db, newest):
        self.sha, self.tests, self.began, self.waiting, self.batches, self.alone = newest, {}, self.clock(), None, {}, set()
        self.left, self.kept, self.finished = {}, set(), set()
        self.listing = self.job(db, 'list', LIST, f'fullrun:{newest}:list', listing=True)
        self.say(db, 'listing')
        LOG.info('fullrun: %s landed: list job %s', newest[:12], self.listing)
        return newest

    def settle(self, db):
        """The ended jobs of the open full run: the list made into a job per test, a test taken back made again, and the
        verdict once every test ran."""
        ids = [ident for ident in [self.listing, *(each[0] for each in self.tests.values())] if ident]
        if not ids:
            return None
        states = {ident: (state, result, free in (True, 't')) for ident, state, result, free in
                  db.rows(JOBS, {'ids': ','.join(ids)})}
        if self.listing and states.get(self.listing, (None,))[0] in ENDED:
            state, result, _ = states[self.listing]
            answer = (json.loads(result or 'null') or {}).get('answer') or {}
            tests = [each for each in answer.get('tests') or [] if isinstance(each, str) and TEST.match(each)]
            self.listing = None
            if state == 'cancelled':  # taken back for a gate before it listed: listed again
                self.listing = self.job(db, 'list', LIST, f'fullrun:{self.sha}:list:{int(self.clock())}', listing=True)
                return None
            if state != 'succeeded' or not tests:
                self.say(db, 'skipped', why=f'the list job {state}: {answer.get("refused") or "no tests"}')
                self.sha = None
                if self.waiting:
                    self.begin(db, self.waiting)
                return None
            self.batches = {}
            alone = [name for name in tests if name in ROOT_FROM_BASE or not answer.get('batch') or name in self.learned]
            self.alone.update(name for name in alone if name in self.learned)  # FULL-RUN-ALONE-LEARNED: said alone again
            for name in alone:
                self.tests[name] = [self.job(db, name, self.command(name), f'fullrun:{self.sha}:{name}:1'), 1]
            together = [name for name in tests if name not in alone]
            for index, names in enumerate(batches(together, answer.get('costs') or {})):
                label = f'batch-{index}'
                self.batches[label] = names
                self.tests[label] = [self.job(db, label, self.command(label), f'fullrun:{self.sha}:{label}:1'), 1]
            self.say(db, 'running', n=len(tests), jobs=len(self.tests))
            return None
        if not self.tests or self.listing:
            return None
        red, done = [], 0
        for name, each in list(self.tests.items()):
            if name in self.finished:
                done += 1
                continue
            state, result, free = states.get(each[0], (None, None, True))
            if state == 'cancelled' and name in self.batches:  # FULL-RUN-KEEP: what its run answered is kept
                if not free:  # its run not ended yet: its answer comes with the run's end (run.ended wakes the look)
                    continue
                said = ((json.loads(result or 'null') or {}).get('answer') or {}).get('tests') or {}
                left = self.left.get(name, self.batches[name])
                for test in left:
                    if said.get(test) == 'PASS':
                        self.kept.add(test)
                    elif said.get(test) is not None and test not in self.tests:  # red in the batch: alone, as below
                        self.tests[test] = [self.job(db, test, self.command(test), f'fullrun:{self.sha}:{test}:alone'), 1]
                        self.alone.add(test)
                self.left[name] = [test for test in left if test not in said]
                if not self.left[name]:
                    self.finished.add(name)
                    done += 1
                    continue
            if state == 'cancelled':  # FULL-RUN: taken back for a gate's job (mechanisms.PREEMPT): the test runs again
                each[1] += 1
                each[0] = self.job(db, name, self.command(name), f'fullrun:{self.sha}:{name}:{each[1]}')
            elif state in ENDED:
                done += 1
                names = self.left.get(name, self.batches.get(name))  # FULL-RUN-KEEP: the tests this run was asked
                if names is None:
                    if state != 'succeeded':
                        red.append(name)
                    continue
                said = ((json.loads(result or 'null') or {}).get('answer') or {}).get('tests') or {}
                # FULL-RUN-ALONE: a test red in a batch (or one the batch did not answer) runs again alone, one job of its
                # own, and is red only if it is red there: a batch of three or more runs under the fork server, and
                # infra-intask-standby's processes ran out of time under it (e8e66675, 13/11 23:53 UTC; green alone)
                for test in names:
                    if said.get(test) != 'PASS' and test not in self.tests:
                        self.tests[test] = [self.job(db, test, self.command(test), f'fullrun:{self.sha}:{test}:alone'), 1]
                        self.alone.add(test)
        if done < len(self.tests):
            return None
        verdict = 'red' if red else 'green'
        tested = sorted({test for name in self.tests for test in self.batches.get(name, [name])})
        said = {'n': len(tested), 'red': sorted(red), 'seconds': round(self.clock() - self.began, 1), 'jobs': len(self.tests),
                'alone': sorted(self.alone), 'kept': len(self.kept),
                'retried': sorted(test for name, each in self.tests.items() if each[1] > 1
                                  for test in self.batches.get(name, [name]))}
        self.say(db, verdict, **said)
        self.learned = set(sorted(self.alone)[:LEARNED_MAX])  # FULL-RUN-ALONE-LEARNED: the next run starts them alone
        LOG.info('fullrun: %s %s: %d test(s), red %s', self.sha[:12], verdict, len(self.tests), red)
        if red and self.publish is not None:
            try:
                self.publish({'sha': self.sha, **said}, subject=f'tower base RED at {self.sha[:12]}: {", ".join(red)}'[:100])
            except Exception:  # noqa: BLE001 - the event says it either way
                LOG.exception('fullrun: the red base was not published')
        self.sha, self.tests = None, {}
        if self.waiting:  # FULL-RUN-COALESCE: the newest landing behind it starts now
            self.begin(db, self.waiting)
        return verdict

    def recover(self, db):
        """FULL-RUN-RECOVER: the open run and the sha waiting behind it, from the log; the run's jobs found by their keys."""
        self.recovered = True
        ended, listed, waiting, open_ = set(), {}, None, None
        learned = None
        for payload, at in db.rows(STATES):  # newest first
            said = json.loads(payload or 'null') or {}
            sha, state = said.get('sha'), said.get('state')
            if not sha or not SHA.match(str(sha)):
                continue
            if learned is None and state in ('green', 'red') and isinstance(said.get('alone'), list):
                learned = {each for each in said['alone'] if isinstance(each, str) and TEST.match(each)}
                self.learned = set(sorted(learned)[:LEARNED_MAX])  # FULL-RUN-ALONE-LEARNED: the newest verdict's
            if state == 'listing':
                listed.setdefault(sha, float(at))
            if state in ENDS:
                ended.add(sha)
            elif sha not in ended and open_ is None:
                if state == 'waiting':
                    waiting = waiting or sha
                elif state in ('listing', 'running'):
                    open_ = sha
        if open_ is None:
            if waiting and waiting not in ended:
                self.begin(db, waiting)
            return None
        self.sha, self.tests, self.began, self.batches, self.alone = open_, {}, listed.get(open_, self.clock()), {}, set()
        self.left, self.kept, self.finished = {}, set(), set()
        self.waiting = waiting if waiting not in (None, open_) and waiting not in ended else None
        self.listing = self.job(db, 'list', LIST, f'fullrun:{open_}:list', listing=True)  # the same key: the same job
        LOG.info('fullrun: %s taken again after a restart (waiting: %s)', open_[:12], (self.waiting or '-')[:12])
        return open_

    def step(self, db):
        if not self.recovered:
            self.recover(db)
        self.follow(db)
        return self.settle(db)


def start(scope, stop, wait, active=None, environ=None):
    """The look in a daemon thread, woken by tower_deploy (a push) and tower_work (a job's end)."""
    import os
    import threading
    from . import canary
    environ = os.environ if environ is None else environ
    full = FullRun(publish=lambda said, subject: canary.alert(said, environ, subject=subject))

    def loop():
        while not stop.is_set():
            if active is None or active():
                try:
                    with scope() as db:
                        full.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('fullrun: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='fullrun', daemon=True)
    thread.start()
    return thread
