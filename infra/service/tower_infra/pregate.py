"""PRE-GATE (docs/operations/aws.md 22.9; the Torre's decision of 13/11 09:56 BRT): the long work of a gate runs while a PR
is authored, not after it is delivered.

At each push of a unit branch (forge.repository.pushed, in the log within a second, notified on tower_deploy), the live
service asks the runner for the gate's plan of base...head with the check jobs' own bodies (scripts/gate-check plan jobs,
by the head's adapter, in the runner's checkout: PLAN-ON-RUNNER's job, the same input_digest, so the delivery's gate gets
its plan from the cache) and makes those jobs, memoized by content: each check's input_digest is the suite and the hash of
what it covers (or the stage and the trees it reads). The delivery's gate makes the same jobs: what the pre-gate ran green
is answered by the port's cache with no run, what it is still running is waited for (mechanisms.TWIN), and only what
changed since the last push runs. A head pushed again leaves the earlier head's pre-gate to the cache as it ends.

GATE-SHUTDOWN (14/11/2026, D-314; #17, #22): this look served the AWS gate on Origin, which is shut down (the gate is
GitHub's tower/gate and its merge queue): serve() starts it only under service.gate_looks, false by default. Its code
stays whole, so a row of work.config_value turns it back on at the next start.
"""
import hashlib
import json
import logging
import re
import time
from . import engine  # ENGINE-REPO

LOG = logging.getLogger('tower_infra.pregate')
UNITS = 'refs/heads/units/'
REPO = engine.DEFAULT  # ENGINE-REPO: the default; engine.repo() is what runs
SHA = re.compile(r'^[0-9a-f]{40}$')
QUEUE, PLAN_RANK, TIMEOUT_S = 'checks', 1000000, 300  # gate-infra.check_queue; gate_infra.planned's rank
# GATE-OUTRANKS-PREGATE (criterion 3): the pre-gate's jobs rank under every delivery's (whose ranks reach PLAN_RANK): a
# delivery's gate waited behind another PR's pre-gate at the same ranks (#711, 13/11 00:07 UTC: 125.9 s); the gate that
# asks for a queued pre-gate job by its key lifts it to the gate's rank (port.create_job)
PREGATE_DROP = 1000000
ENDED = ('succeeded', 'failed', 'stopped', 'cancelled')
# PREGATE-WINDOW: a look that starts reads the pushes of the last WINDOW_S only: an hour's (the first version) planned
# the heads of branches long delivered, at the service's start after #650's deploy, from before `plan jobs` (5 runs
# refused with gate-check's usage) or already landed
OVERLAP_S, WINDOW_S = 5.0, 120.0
EVENTS = ("select event_id, extract(epoch from occurred_at)::float8, (payload #> '{delivery,event,payload}')::text "
          "from log.event where type = 'forge.repository.pushed' and occurred_at > to_timestamp(%(since)s::float8) "
          "order by occurred_at")
# OBSERVE-ON-PUSH: a PR opened or pushed carries its number and head; the pre-gate pre-observes it, so `pr metadata` at the
# delivery (which held #652's landing 7.5 s) finds the observation done
PR_EVENTS = ("select event_id, extract(epoch from occurred_at)::float8, (payload #> '{delivery,event,payload}')::text "
             "from log.event where type in ('forge.pull_request.created', 'forge.pull_request.head_ref.pushed') "
             "and occurred_at > to_timestamp(%(since)s::float8) order by occurred_at")
BASE = ("select (payload #> '{delivery,event,payload,refUpdates}')::text from log.event where type = 'forge.repository.pushed' "
        "and occurred_at > now() - interval '7 days' and payload #> '{delivery,event,payload,refUpdates}' @> %(ref)s::jsonb "
        "order by occurred_at")
JOBS = "select id::text, state, result::text from work.job where id = any(string_to_array(%(ids)s, ',')::uuid[])"
# PREMERGE (the Torre's choice of 13/11: a PR behind the base had its combination judged at its delivery: #678, 85.5 s of
# merge and 47 s of the checks only that combination needs): when the base moves, the newest heads of the unit branches
# pushed in PREMERGE_WINDOW_S that it does not hold (PREMERGE_MAX of them, the newest) are merged with it by the live
# service (branches.Merger.premerge, a ref of their own) and that merge is pre-gated; the delivery's merge is the same
# commit, so its plan and its checks are answered by the cache
PREMERGE_WINDOW_S, PREMERGE_MAX = 6 * 3600, 4
RECENT = ("select (payload #> '{delivery,event,payload}')::text from log.event where type = 'forge.repository.pushed' "
          "and occurred_at > now() - make_interval(secs => %(window)s::float8) order by occurred_at")
PREMERGED = ("select event_id, extract(epoch from occurred_at)::float8, payload::text from log.event "
             "where type = 'platform.forge.branch_merge' and tenant_id is null and payload->>'state' = 'premerged' "
             "and occurred_at > to_timestamp(%(since)s::float8) order by occurred_at")
TENANT_ID = "select id::text from work.tenant where name = %(tenant)s"
SAID = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        "select %(id)s, null, 'platform.gate.pregate', clock_timestamp(), 'pregate', 'gate/pregate', %(payload)s::jsonb "
        "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.gate.pregate')")


def digest(*parts):
    """gate_infra.digest: the input_digest the delivery's gate gives the same job."""
    return 'sha256:' + hashlib.sha256('\0'.join(str(part) for part in parts).encode('utf-8')).hexdigest()


def encode(action):
    import base64
    return 'data:application/json;base64,' + base64.b64encode(json.dumps(action, sort_keys=True).encode()).decode()


def ours(body, repo):
    where = (body or {}).get('repository') or {}
    return f"{(where.get('owner') or {}).get('slug')}/{where.get('name')}" == repo


class Pregate:
    @property
    def repo(self):
        """ENGINE-REPO: the one given, else the engine's repository as configured now (engine.repo())."""
        return self._repo or engine.repo()

    def __init__(self, base_branch='mod/roadmap-integration', repo=None, tenant=None, clock=time.time,
                 create=None, observe=None):
        from . import config_data, observations, port
        self.base_branch, self._repo, self.clock = base_branch, repo, clock
        self.tenant = tenant or config_data.TENANT
        self.create = create or port.create_job
        self.observe = observe or observations.ask  # OBSERVE-ON-PUSH: pre-observe a PR's head
        self.since, self.seen, self.since_pr, self.seen_pr, self.planning = None, {}, None, {}, {}
        self.since_merged, self.seen_merged = None, {}

    def base(self, db):
        ref, found = f'refs/heads/{self.base_branch}', None
        for (updates,) in db.rows(BASE, {'ref': json.dumps([{'ref': ref}])}):
            for update in json.loads(updates or 'null') or []:
                if update.get('ref') == ref and not update.get('deleted') and SHA.match(str(update.get('after') or '')):
                    found = update['after']
        return found

    def who(self, db):
        return ('tenant', db.rows(TENANT_ID, {'tenant': self.tenant})[0][0])

    def say(self, db, head, **payload):
        db.rows(SAID, {'id': f"pregate:{head}:{payload.get('state')}", 'payload': json.dumps({'head': head, **payload})})

    def follow(self, db):
        """The unit branches' newest pushes since the last look: a plan job for each new head."""
        since = self.since if self.since is not None else self.clock() - WINDOW_S
        newest, moved = {}, None
        for event, at, body in db.rows(EVENTS, {'since': since}):
            self.since = max(self.since or since, float(at) - OVERLAP_S)
            if event in self.seen:
                continue
            self.seen[event] = float(at)
            body = json.loads(body or 'null') or {}
            if not ours(body, self.repo):
                continue
            for update in body.get('refUpdates') or []:
                ref, after = str(update.get('ref') or ''), str(update.get('after') or '')
                if ref.startswith(UNITS) and not update.get('deleted') and SHA.match(after) and set(after) != {'0'}:
                    newest[ref[len('refs/heads/'):]] = after
                if ref == f'refs/heads/{self.base_branch}' and not update.get('deleted') and SHA.match(after):
                    moved = after  # PREMERGE: the base moved
        self.since = since if self.since is None else self.since
        self.seen = {event: at for event, at in self.seen.items() if at > self.since}
        base = self.base(db) if newest else None
        for branch, head in newest.items():
            if base:
                self.plan(db, branch, head, base)
        if moved:
            self.premerge(db, moved, skip=set(newest))
        return len(newest)

    def premerge(self, db, onto, skip=()):
        """PREMERGE: the base moved to `onto`: the newest heads of the recent unit branches asked to be merged with it (the
        live service's Merger, by the same event as a delivery's merge); one the base holds is said `landed` there."""
        from . import branches
        heads = {}
        for (body,) in db.rows(RECENT, {'window': PREMERGE_WINDOW_S}):
            body = json.loads(body or 'null') or {}
            if not ours(body, self.repo):
                continue
            for update in body.get('refUpdates') or []:
                ref, after = str(update.get('ref') or ''), str(update.get('after') or '')
                if ref.startswith(UNITS) and SHA.match(after) and set(after) != {'0'}:
                    branch = ref[len('refs/heads/'):]
                    heads.pop(branch, None)
                    if not update.get('deleted'):
                        heads[branch] = after  # the newest last
        asked = 0
        for branch, head in list(heads.items())[-PREMERGE_MAX:]:
            if branch in skip:
                continue  # pushed in this look: its own pre-gate is planned on the new base already
            branches.say(db, f'premerge:{head[:12]}:{onto[:12]}', 'asked', 'pregate', branch=branch, head=head,
                         base=self.base_branch, premerge=True, onto=onto)
            asked += 1
        LOG.info('pregate: the base moved to %s: %d premerge(s) asked', onto[:12], asked)
        return asked

    def premerged(self, db):
        """PREMERGE: each merge the Merger pushed to its ref, planned like a push: its check jobs made, by content."""
        since = self.since_merged if self.since_merged is not None else self.clock() - WINDOW_S
        planned = 0
        for event, at, payload in db.rows(PREMERGED, {'since': since}):
            self.since_merged = max(self.since_merged or since, float(at) - OVERLAP_S)
            if event in self.seen_merged:
                continue
            self.seen_merged[event] = float(at)
            said = json.loads(payload or 'null') or {}
            if SHA.match(str(said.get('sha'))) and SHA.match(str(said.get('onto'))) and str(said.get('ref', '')).startswith('premerge/'):
                self.plan(db, said['ref'], said['sha'], said['onto'])
                planned += 1
        self.since_merged = since if self.since_merged is None else self.since_merged
        self.seen_merged = {event: at for event, at in self.seen_merged.items() if at > self.since_merged}
        return planned

    def plan(self, db, branch, head, base):
        spec = {'repo': self.repo, 'ref': f'refs/heads/{branch}', 'commit': head, 'base': base, 'timeout_s': TIMEOUT_S,
                'command': ['scripts/gate-check', 'plan', 'jobs', '--base', base]}
        made = self.create(db, self.who(db), {
            'queue': QUEUE, 'rank': PLAN_RANK - PREGATE_DROP, 'selector': {'adapter': 'container'}, 'memoize': True,
            'input_uri': encode(spec), 'input_digest': digest('gate-plan', head, base),
            'idempotency_key': f'pregate:plan:{head}:{base}'})
        self.planning[made['id']] = (branch, head, base)
        LOG.info('pregate: %s pushed %s: plan job %s', branch, head[:12], made['id'])

    def settle(self, db):
        """The plan jobs that ended: their answered check jobs made, memoized by content."""
        if not self.planning:
            return 0
        made = 0
        for job, state, result in db.rows(JOBS, {'ids': ','.join(self.planning)}):
            if state not in ENDED:
                continue
            branch, head, base = self.planning.pop(job)
            answer = (json.loads(result or 'null') or {}).get('answer') or {}
            jobs = answer.get('jobs')
            if state != 'succeeded' or not isinstance(jobs, list):
                self.say(db, head, state='skipped', branch=branch, why=f"plan {state}: {answer.get('refused') or 'no jobs'}")
                continue
            for each in jobs:
                body = each.get('body') or {}
                if body.get('memoize') and body.get('input_digest'):
                    self.create(db, self.who(db), dict(body, rank=(body.get('rank') or 0) - PREGATE_DROP))
                    made += 1
            self.say(db, head, state='made', branch=branch, base=base, jobs=made)
            LOG.info('pregate: %s %s: %d check job(s) made', branch, head[:12], made)
        return made

    def preobserve(self, db):
        """OBSERVE-ON-PUSH: a PR opened or pushed, pre-observed by its number and head, so the delivery's `pr metadata`
        finds it done. The observation is idempotent on (pr, head): the delivery's own ask gets this one."""
        since = self.since_pr if self.since_pr is not None else self.clock() - WINDOW_S
        asked = 0
        for event, at, body in db.rows(PR_EVENTS, {'since': since}):
            self.since_pr = max(self.since_pr or since, float(at) - OVERLAP_S)
            if event in self.seen_pr:
                continue
            self.seen_pr[event] = float(at)
            body = json.loads(body or 'null') or {}
            if not ours(body, self.repo):
                continue
            pr = (body.get('pullRequest') or {})
            number, head = pr.get('number'), ((pr.get('head') or {}).get('sha') or '')
            if str(number or '').isdigit() and SHA.match(head) and not pr.get('merged') and pr.get('state') == 'open':
                self.observe(db, self.who(db), {'pr': int(number), 'head': head})
                asked += 1
        self.since_pr = since if self.since_pr is None else self.since_pr
        self.seen_pr = {event: at for event, at in self.seen_pr.items() if at > self.since_pr}
        return asked

    def step(self, db):
        self.follow(db)
        self.premerged(db)
        self.preobserve(db)
        return self.settle(db)


def start(scope, stop, wait, active=None):
    import threading
    pregate = Pregate()

    def loop():
        while not stop.is_set():
            if active is None or active():
                try:
                    with scope() as db:
                        pregate.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('pregate: look failed')
            wait(60)  # woken by tower_deploy (a push) and tower_work (a plan job's end)
    thread = threading.Thread(target=loop, name='pregate', daemon=True)
    thread.start()
    return thread
