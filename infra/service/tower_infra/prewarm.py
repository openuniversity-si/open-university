"""IMAGE-PREWARM-B2 (docs/operations/aws.md 22.9): on each authoring push, a standby task per role with the head's code.

Only the live service does this (its live_image gate; a standby looks at nothing). It follows the pushes of the unit
branches (forge.repository.pushed with a refUpdate of refs/heads/units/*, which the ingress records; the look wakes on
tower_deploy, migration 0009, and on tower_work, migration 0006, when the bundle's job ends). For a new head it makes one
job of the container executor, `scripts/gate-check artifact code --base <the base's head>`, idempotent by the head: in a
checkout of the head, deploy_classify.code_only of base...head and, for a code-only head, the code bundle
(lambda_package.gate_code, B1's artifacts/lambda/tower-code/<sha256>.zip). Its answer, the last JSON line of the job's log
tail, names the bundle's key and sha256 S. For S, one RunTask per role on FARGATE_SPOT in the tasks' subnets and group:
the runner from the family tower-runner, the service from tower-service-standby (30-service.json: the service's task
without its init container, so the owner's dbinit never runs per standby), with TOWER_CODE_KEY, TOWER_CODE_SHA256,
TOWER_IMAGE_DIGEST = S and TOWER_STANDBY=1 (live_image's strict gate: no work until the pointer names S), tagged with
role, digest and branch.

The lifecycle follows events, never a timer:
  - a branch's newer head moves the branch: to the same bundle, nothing; to another, that bundle's standbys; to the slow
    path (not code-only, or its job failed), none. A bundle's tasks stop (StopTask) once no branch holds it: two heads
    with the same bundle share its tasks.
  - a deleted branch (its refUpdate deleted) or a closed PR (forge.pull_request.closed, by its head ref) lets go of it.
  - deploy.prewarm_max_tasks (default 0, off: DEFAULTS-AS-LIVE) is the number of bundles with standbys, so the tasks of each role:
    over it the newest push wins, the oldest bundle's tasks stop and its branches fall back to the slow path (logged).
  - a bundle the pointer names (deploy.live_image_<role>) is never stopped or counted here: the swap is phase C's.
  - IMAGE-PREWARM-C: a bundle the landing promoted (a platform.deploy.image_swap names it) is retired once no pointer names
    it any more, whatever branch still holds it: its service task is stopped; its runner task is never StopTask'd (SIGTERM
    would end its runs in flight as lost): it is `retiring` until it exits on its own (its gate retired it: the slots end
    after their runs), RETIRE_LIMIT_S at most. A retiring bundle is not counted against the cap.
Every transition is platform.deploy.standby {role, digest, task, branch, state: started|healthy|retiring|stopped|failed,
at, started_at} (tenant_id null, the installation's), shown in GET /v1/deploy/status as `standby`; they also give the tasks
back after a restart of the service, and started_at to stopped `at` is what scripts/medir prices as prewarm_task_usd.

IN-TASK-STANDBY (tower_infra.live_image, tower_infra.supervisor): with deploy.intask_standbys above 0 the bundle a head holds
also gets a successor process inside the ECS task of each role: the want is recorded here, platform.deploy.successor
{digest, key, branch, state: wanted}, with a NOTIFY of tower_config that each task's process reads it on, and withdrawn
the same way where a bundle's Spot tasks are stopped (a newer push, a closed PR, the slot given to another head, a
promoted bundle the tasks took over). The slot's rules are the same ones: the bundles held are the larger of the two
data, and PREWARM-TRAIN-SLOT keeps the slot of a delivery in the train. deploy.prewarm_max_tasks 0 runs no Spot task and
the successors alone stand by. A restart of the service finds the wants in the log, as it finds the tasks.

Health is DescribeTasks' healthStatus, the container's health check over the standby's own beat. The one poll: while a
task is starting, the look runs at least every POLL_S (15 s; never more than two of them blind) and a task not healthy in
START_LIMIT_S fails; with none starting only events wake the look (and SAFETY_S, the timeout of a lost notification).

GATE-SHUTDOWN (14/11/2026, D-314; #17, #22): this look served the AWS gate on Origin, which is shut down (the gate is
GitHub's tower/gate and its merge queue): serve() starts it only under service.gate_looks, false by default. Its code
stays whole, so a row of work.config_value turns it back on at the next start.
"""
import hashlib
import json
import logging
import os
import re
import time

from . import config_data, fastdeploy, forge, live_image, port
from . import engine  # ENGINE-REPO

LOG = logging.getLogger('tower_infra.prewarm')
PRODUCER = 'prewarm'
UNITS = 'refs/heads/units/'
# PREWARM-PREMERGE (criterion 3): a PR behind the base lands the premerge's commit (premerge/<branch>/<base12>, the same sha
# its delivery's merge pushes), whose code no standby had: #699 and #701 waited 12.1 s at the train's front for their
# successors (13/11 22:34 and 22:45 UTC). A premerge's push is its unit branch's newest head, its bundle made from that ref
PREMERGE = re.compile(r'^refs/heads/premerge/(units/[A-Za-z0-9._/-]+)/[0-9a-f]{12}$')


def unit_of(ref):
    """(branch, ref to fetch) of a push the prewarm follows: a unit branch's own, or a premerge of one; None otherwise."""
    if ref.startswith(UNITS):
        return ref[len('refs/heads/'):], ref
    found = PREMERGE.match(ref)
    return (found.group(1), ref) if found else None
ROLES = ('runner', 'service')
FAMILIES = {'runner': 'tower-runner', 'service': 'tower-service-standby'}  # 50-runner.json, 30-service.json
CONTAINERS = {'runner': 'runner', 'service': 'service'}
REPO = engine.DEFAULT  # ENGINE-REPO: the default; engine.repo() is what runs
QUEUE, RANK, TIMEOUT_S = 'checks', 999000, 300  # gate-infra.check_queue; the rank gate_infra gives a one-check head
POLL_S, SAFETY_S, START_LIMIT_S, OVERLAP_S = 15, 300, 900, 10
# IMAGE-PREWARM-C: a retiring runner standby not gone by then is stopped. PREWARM-MERGED-RELEASED: 20 min, not an hour: a
# check's own limit is 900 s (gate-infra.check_timeout_s), so a run still there after it is lost anyway, and a standby
# left retiring by mistake holds six of the database's connections meanwhile
RETIRE_LIMIT_S = 1200
ALIVE, ENDED = ('started', 'healthy'), ('succeeded', 'failed', 'stopped', 'cancelled')
# PREWARM-RETRY: a role with no task (RunTask refused: 'Capacity is unavailable at this time' on FARGATE_SPOT, live 10/11; or
# its standby stopped before the landing) is tried again on a later look, RETRY_S apart, RETRY_MAX times a role and bundle:
# without it the pair stayed half (no swap at the landing, the other standby paid for nothing) until a new push
RETRY_S, RETRY_MAX = 60, 10
# PREWARM-TRAIN-SLOT: the single slot (deploy.prewarm_max_tasks) belongs to the delivery that is in the merge train, not to
# the newest push: live 11/11 the pair of #495 was stopped 4 min before its landing by another branch's push, and #495
# landed by the slow path. A bundle whose head is in the train is not evicted; the pusher's bundle starts when the slot frees.
TRAIN_HAS = ('select 1 from work.train where ended_at is null and lease_until > clock_timestamp() '
             'and head = any(%(heads)s) limit 1')
# LANDING-KEEPS-STANDBY: a merged PR's bundle keeps its standbys until the landing of that head is said (the delivery's
# platform.deploy.landed, whose statement swaps onto them), not from the forge's merge event: live 11/11 23:45 UTC the
# merge event of #546 reached the look 1.5 s before the landing, the bundle's want was withdrawn, the one successor slot
# went to the branch that waited (#547), and the landing found no standby: 16.6 s instead of under one. LANDING_S bounds
# a landing that is never said (the delivery died between the merge and its word)
LANDED = ("select 1 from log.event where type = 'platform.deploy.landed' and occurred_at > now() - interval '1 day' "
          "and payload->>'pr_head' = %(head)s limit 1")
LANDING_S = 30
RETIRING = 'retiring'  # IMAGE-PREWARM-C: a promoted runner standby finishing its runs in flight before it exits
PROMOTED = ("select 1 from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
            "and occurred_at > now() - interval '7 days' and payload->>'digest' = %(sha)s and payload->>'swapped' = 'true' "
            "limit 1")
SHA = re.compile(r'^[0-9a-f]{40}$')

EVENTS = ("select event_id, extract(epoch from occurred_at)::float8, type, (payload #> '{delivery,event,payload}')::text "
          "from log.event where type in ('forge.repository.pushed', 'forge.pull_request.closed', 'forge.pull_request.merged') "
          "and occurred_at > to_timestamp(%(since)s::float8) order by occurred_at")
BASE = ("select (payload #> '{delivery,event,payload,refUpdates}')::text from log.event where type = 'forge.repository.pushed' "
        "and occurred_at > now() - interval '7 days' and payload #> '{delivery,event,payload,refUpdates}' @> %(ref)s::jsonb "
        "order by occurred_at")
JOBS = "select id::text, state, result::text from work.job where id = any(string_to_array(%(ids)s, ',')::uuid[])"
TENANT_ID = "select id::text from work.tenant where name = %(tenant)s"
RECORD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          "select %(id)s, null, 'platform.deploy.standby', clock_timestamp(), 'prewarm', 'deploy/standby/' || %(role)s, "
          "%(payload)s::jsonb where not exists (select 1 from log.event where event_id = %(id)s "
          "and type = 'platform.deploy.standby')")
# IN-TASK-STANDBY: a want said or withdrawn, once per id, and the tasks' processes woken (their gates' listeners)
WANT = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        f"select %(id)s, null, '{live_image.SUCCESSOR}', clock_timestamp(), 'prewarm', 'deploy/successor', %(payload)s::jsonb "
        f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{live_image.SUCCESSOR}' "
        "and occurred_at > now() - interval '2 days') "
        "returning type) select pg_notify('tower_config', type) from said")
# the bundles wanted now, as the log has them: the newest want of each digest in a day is `wanted`
WANTED = ("select payload::text from (select distinct on (payload->>'digest') payload, occurred_at from log.event "
          f"where type = '{live_image.SUCCESSOR}' and tenant_id is null and occurred_at > now() - interval '1 day' "
          "and payload->>'state' in ('wanted', 'withdrawn') order by payload->>'digest', occurred_at desc) w "
          "where payload->>'state' = 'wanted' order by occurred_at")
# PREWARM-ONE-LOOK: the look's turn. Two services can be live at once (an ECS rollout keeps the old task until the new one
# is healthy; a promoted standby and the task that takes the role back), each with its own memory of the tasks: live
# 11/11 each started a pair for the same bundle, twice (four Spot tasks, 65 of the database's 79 connections), and the
# pair the other service started was in nobody's memory any more. One statement takes the look's lock (a session
# advisory lock, on the look's connection) and reads the newest thing any prewarm said; another gives the lock back and
# reads it again. A look that does not get the lock, or finds something said since its own last look, forgets its
# memory and reads the log again (restore), where the other service's tasks are.
LOCK_KEY = 7424003
SAID = ("coalesce((select event_id from log.event where type in ('platform.deploy.standby', "
        f"'{live_image.SUCCESSOR}') and tenant_id is null and producer = 'prewarm' "
        "and occurred_at > now() - interval '7 days' order by occurred_at desc limit 1), '')")
TURN = f'select pg_try_advisory_lock(%(key)s), {SAID}'
TURN_END = f'select pg_advisory_unlock(%(key)s), {SAID}'
# PREWARM-RESTART-WINDOW: how far back a prewarm that starts reads the pushes and the closed PRs. With the in-task
# successors every landing gives the role to a new process, so "a restart" is every landing: a branch pushed before
# the window had its standbys (the log gives them back) but no head here, the train was never asked for it
# (PREWARM-TRAIN-SLOT asks by head) and a later push took its slot. Hours of pushes are a few dozen rows, read once.
RESTART_S = 3 * 3600
EXTRA_TRIES = 3  # a StopTask of a second standby that fails is tried again on this many looks
KNOWN = ("select distinct on (payload->>'task') payload::text from log.event where type = 'platform.deploy.standby' "
         "and tenant_id is null and occurred_at > now() - interval '7 days' and payload->>'task' <> '' "
         "order by payload->>'task', occurred_at desc")

# SWAP-MEASURE: a round of the image swap asked by command (POST /v1/deploy/measure, canary.measure), carried out here by the
# look, the one that wants successors for a push. The published head's bundle, built with the round's mark (the same code,
# another digest: scripts/gate-check artifact code --salt), gets its successor in each ECS task as a pushed head's does
# (want); once both said `warm` the drill, when asked, names both roles (SWAP-DRILL) and the readiness question is asked
# (port.READY_ROLES: what the delivery at the front asks before it merges); once both successors said they rehearsed on
# it (and, drilled, that they are armed) the pointers are swapped by the autodeploy's statement (SWAP_WRITE), and the
# round is done when both roles said image_live. Each step is platform.deploy.measure {round, state}, so a look that
# took the role over (the swap gives the role to a new process) carries the round on from the log
MEASURE = 'platform.deploy.measure'
MEASURE_LIMIT_S = 540  # a round not done by then fails (canary.MEASURE_BUSY_S, 600, is when another may be asked)
MEASURE_HEAD = 'measure/'  # the branch a round's bundle is held by, as a push's head is
MEASURES = ("select payload::text, extract(epoch from occurred_at)::float8 from log.event where type = 'platform.deploy.measure' "
            "and tenant_id is null and occurred_at > now() - interval '1 hour' order by occurred_at")
MEASURE_SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
               "select %(id)s, null, 'platform.deploy.measure', clock_timestamp(), 'prewarm', 'deploy/measure', %(payload)s::jsonb "
               "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
               "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.measure' "
               "and occurred_at > now() - interval '1 day') returning type) select pg_notify('tower_deploy', type) from said")
SAID_BY = (f"select payload->>'role', payload->>'state', coalesce(payload->>'armed', ''), extract(epoch from occurred_at)::float8 "
           f"from log.event where type = '{live_image.SUCCESSOR}' and tenant_id is null "
           "and occurred_at > to_timestamp(%(since)s::float8) and payload->>'digest' = %(digest)s "
           "and payload->>'state' in ('warm', 'rehearsed', 'reserve')")
# SWAP-RESERVE-WAIT: and the reserve of each role's task said how it stands (held: loaded and waiting; or why none) before
# the readiness question, RESERVE_WAIT_S at most after both were warm. A landing comes minutes after its push (the
# delivery's checks), so its successors' reserves were there; the first round (13/11 01:12 UTC) swapped 2 s after the
# service's successor was warm, before its reserve (it settles 60 s first): the drill left the role no reserve and a new
# process booted (boot_s 4.39, the service's code at work 5.87 s after the pointer)
RESERVE_WAIT_S = 180
DRILL_ASK = (f"insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
             f"select %(id)s, null, '{live_image.DRILL_EVENT}', clock_timestamp(), 'prewarm', 'deploy/drill', %(payload)s::jsonb "
             "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
             f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{live_image.DRILL_EVENT}' "
             "and occurred_at > now() - interval '1 day')")
LIVE_ROLES = ("select distinct type || ':' || (payload->>'role') from log.event where tenant_id is null "
              "and (type = 'platform.deploy.image_live' or (type = 'platform.deploy.image_reload' and payload->>'state' = 'reloaded')) "
              "and payload->>'digest' = %(digest)s and occurred_at >= to_timestamp(%(since)s::float8)")
BEAT_ROLES = ("select coalesce(string_agg(distinct role, ',' order by role), '') from work.standby_beat where digest = %(digest)s "
              "and beat_at > clock_timestamp() - make_interval(secs => %(fresh_s)s::float8)")


answer = port.bundle_answer  # IMAGE-SWAP-TIGHTEN: in the port, which the landing's swap runs in


class Prewarm:
    @property
    def repo(self):
        """ENGINE-REPO: the one given, else the engine's repository as configured now (engine.repo())."""
        return self._repo or engine.repo()

    def __init__(self, scope, ecs, cluster, network, tenant=config_data.TENANT, config=None, repo=None, clock=time.time,
                 warm=None):
        self.scope, self.ecs, self.cluster, self.network = scope, ecs, cluster, network
        self.warm = warm  # PORT-WARM-ON-PUSH: asks the port's live alias for its health, as an event (None: nothing)
        self.tenant, self.config, self._repo, self.clock = tenant, config, repo, clock
        self.since, self.seen = None, {}  # the newest event read less OVERLAP_S, and the ids read since (read once)
        self.heads = {}  # branch -> its newest head seen
        self.refs = {}  # PREWARM-PREMERGE: head -> the ref its bundle job fetches (a premerge's own, else the branch's)
        self.pending = {}  # head -> the id of its bundle job
        self.bundles = {}  # head -> (key, sha256), or None: the slow path
        self.holds = {}  # branch -> the sha256 of the bundle its head runs on a standby
        self.standbys = {}  # sha256 -> {'at', 'branches': set, 'tasks': {role: {'task', 'state', 'since', 'branch'}}}
        self.restored, self.described = False, 0.0
        self.said = None  # PREWARM-ONE-LOOK: the newest thing a prewarm said when this one's last look ended
        self.extras = []  # PREWARM-ONE-LOOK: [sha, role, task, branch, started_at, tries] of a second standby of a bundle's role
        self.promoted = set()  # IMAGE-PREWARM-C: the bundles a landing swapped the pointers to
        self.waiting = {}  # PREWARM-TRAIN-SLOT: branch -> the head whose bundle waits for the slot a train entry holds
        self.landing = {}  # LANDING-KEEPS-STANDBY: branch -> (the merged PR's head, since when) until its landing is said
        self.measuring = None  # SWAP-MEASURE: the round in flight, as the log has it

    # --- the look ---------------------------------------------------------------------------------------------------
    def step(self):
        """One look; never raises. Answers the wait until the next one: POLL_S while a task starts, else SAFETY_S."""
        try:
            with self.scope() as db:
                mine, said = db.rows(TURN, {'key': LOCK_KEY})[0]  # PREWARM-ONE-LOOK
                if mine not in (True, 't'):
                    self.forget()  # another live service is looking now: what it starts is in the log, read on the next look
                    LOG.info('prewarm: another service is looking; this one reads the log again on its next look')
                else:
                    try:
                        if self.restored and said != self.said:
                            self.forget()  # another service said something since this one's last look
                        if not self.restored:
                            self.restore(db)
                        self.follow(db)
                        self.settle(db)
                        self.watch(db)
                        self.measure(db)  # SWAP-MEASURE
                    finally:
                        self.said = db.rows(TURN_END, {'key': LOCK_KEY})[0][1]
        except Exception:  # noqa: BLE001 - a failed look is a line in the log; the next event looks again
            LOG.exception('prewarm: look failed')
        if self.measuring:  # SWAP-MEASURE: each step is an event; the bound of a round is looked at within POLL_S
            return POLL_S
        if self.landing:  # LANDING-KEEPS-STANDBY: the landing's word wakes the look; its bound is looked at when due
            return LANDING_S
        return POLL_S if self.starting() else RETRY_S if self.missing() or self.waiting else SAFETY_S  # PREWARM-RETRY

    def forget(self):
        """IMAGE-SWAP-FAILOVER: while this service is not the live one its memory of the tasks is no longer the truth
        (another service runs them); the log gives them back (restore) on its first look once it is live again."""
        self.restored, self.standbys, self.holds, self.extras, self.landing = False, {}, {}, [], {}

    def starting(self):
        return any(task['state'] in ('started', RETIRING)  # IMAGE-PREWARM-C: a retiring runner's exit is seen within POLL_S
                   for group in self.standbys.values() for task in group['tasks'].values())

    def in_train(self, db, sha):
        """PREWARM-TRAIN-SLOT: whether a head that runs on this bundle's standbys is in the merge train now."""
        heads = [self.heads[branch] for branch in self.standbys[sha]['branches'] if self.heads.get(branch)]
        return bool(heads) and bool(db.rows(TRAIN_HAS, {'heads': heads}))

    def missing(self):
        """PREWARM-RETRY: (sha, role) of every held bundle's role with no task that may still be tried."""
        return [(sha, role) for sha, group in self.standbys.items() if group['branches'] and group.get('key')
                and self.cap() > 0  # IN-TASK-STANDBY: with the Spot standbys off no task is missing
                and not self.retiring(sha) and sha not in self.promoted
                for role in ROLES if role not in group['tasks'] and group['tries'].get(role, 0) < RETRY_MAX]

    def cap(self):
        # a Prewarm with no configuration at all (the Spot pair's own tests) has the pair; the engine passes its configuration,
        # whose default is off (config_data, DEFAULTS-AS-LIVE)
        return self.config.get('deploy.prewarm_max_tasks') if self.config is not None else 1

    def intask(self):
        """IN-TASK-STANDBY: deploy.intask_standbys: the successors each ECS task holds (0: off)."""
        return self.config.get(live_image.SUCCESSORS) if self.config is not None else 0

    def want(self, db, sha, group, branch, state='wanted', why=None):
        """IN-TASK-STANDBY: the bundle's want said (or withdrawn) to the ECS tasks: platform.deploy.successor and the NOTIFY."""
        at = self.clock()
        db.rows(WANT, {'id': f'{live_image.SUCCESSOR}:{sha}:{state}:{at:.3f}', 'payload': json.dumps(
            {'digest': sha, 'key': group.get('key'), 'branch': branch, 'state': state, 'at': int(at),
             **({'why': why} if why else {})})})
        group['wanted'] = state == 'wanted'
        LOG.info('prewarm: a successor of %s in each ECS task is %s%s', sha[:12], state, f': {why}' if why else '')

    def restore(self, db):
        """The tasks the log says are alive (a restart of the service); DescribeTasks confirms them on this look."""
        for (payload,) in db.rows(KNOWN):
            event = json.loads(payload)
            if event.get('state') not in ALIVE + (RETIRING,) or event.get('role') not in ROLES:
                continue
            group = self.standbys.setdefault(event['digest'], {'at': event.get('at') or 0, 'branches': set(), 'tasks': {}})
            # (since: when the log said that state, not this restore: a task left retiring is stopped RETIRE_LIMIT_S
            # after it began to, however many processes took the role meanwhile; PREWARM-MERGED-RELEASED)
            found = {'task': event['task'], 'state': event['state'], 'since': float(event.get('at') or self.clock()),
                     'branch': event.get('branch'), 'started_at': event.get('started_at')}
            known = group['tasks'].get(event['role'])
            if known is not None:  # PREWARM-ONE-LOOK: one standby per role: the healthy one stays, the other is stopped (watch)
                found, known = (found, known) if known['state'] == 'healthy' or found['state'] != 'healthy' else (known, found)
                self.extras.append([event['digest'], event['role'], found['task'], found['branch'], found['started_at'], 0])
                found = known
            group['tasks'][event['role']] = found
            if event.get('branch'):
                group['branches'].add(event['branch'])
                self.holds[event['branch']] = event['digest']
        # IN-TASK-STANDBY: and the wants, which hold a slot like the tasks (with the datum off, nothing is read)
        for (payload,) in db.rows(WANTED) if self.intask() > 0 else ():
            event = json.loads(payload)
            group = self.standbys.setdefault(event['digest'], {'at': event.get('at') or 0, 'branches': set(), 'tasks': {}})
            group.update(key=group.get('key') or event.get('key'), wanted=True)
            for name in ('tries', 'tried', 'why'):
                group.setdefault(name, {})
            if event.get('branch'):
                group['branches'].add(event['branch'])
                self.holds[event['branch']] = event['digest']
        self.restored = True

    def follow(self, db):
        """The pushes of the unit branches and the closed PRs since the last look."""
        first = self.since is None
        since = self.since if not first else self.clock() - RESTART_S  # PREWARM-RESTART-WINDOW
        found = db.rows(EVENTS, {'since': since})
        last = {}  # on the first read, a branch's older pushes are history: only its newest is its head (one bundle job)
        for event, at, kind, body in found if first else ():
            for update in (json.loads(body or 'null') or {}).get('refUpdates') or [] if kind != 'forge.pull_request.closed' else ():
                last[str(update.get('ref') or '')] = event
        for event, at, kind, body in found:
            self.since = max(self.since or since, float(at) - OVERLAP_S)  # a late commit is still read, and only once
            if event in self.seen:
                continue
            self.seen[event] = float(at)
            body = json.loads(body or 'null') or {}
            if not self.ours(body):
                continue
            if kind in ('forge.pull_request.closed', 'forge.pull_request.merged'):
                # PREWARM-MERGED-RELEASED: a merged PR's branch is done like a closed one's. Only `closed` was read: a
                # prewarm that started and read hours of pushes (PREWARM-RESTART-WINDOW) took every merged branch for a
                # live one and started a pair for each in turn (live 11/11 22:14 UTC: six bundles, five runner standbys
                # left behind, the database at its connections' limit and the port answering 500 for four minutes)
                ref = str(((body.get('pullRequest') or {}).get('head') or {}).get('ref') or '')
                branch = ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ref
                if branch.startswith('units/') and kind.endswith('merged') and branch in self.holds:
                    # LANDING-KEEPS-STANDBY: its standbys are what the landing swaps onto: kept until it is said (watch)
                    head = str(((body.get('pullRequest') or {}).get('head') or {}).get('sha') or '')
                    self.landing[branch] = (head if SHA.match(head) else self.heads.get(branch), self.clock())
                elif branch.startswith('units/'):
                    self.heads.pop(branch, None)
                    self.release(db, branch, 'its PR was merged' if kind.endswith('merged') else 'its PR was closed')
                continue
            for update in body.get('refUpdates') or []:
                ref, after = str(update.get('ref') or ''), str(update.get('after') or '')
                found = unit_of(ref)
                if found is None or last.get(ref, event) != event:
                    continue
                branch, fetched = found
                if fetched != f'refs/heads/{branch}' and (update.get('deleted') or set(after) == {'0'}):
                    continue  # a premerge ref deleted (the next one replaced it): the branch itself stays
                if SHA.match(after):
                    self.refs[after] = fetched
                if update.get('deleted') or set(after) == {'0'}:
                    self.heads.pop(branch, None)
                    self.release(db, branch, 'the branch was deleted')
                elif SHA.match(after) and self.heads.get(branch) != after:
                    self.heads[branch] = after
                    self.consider(db, branch, after)
        if self.since is None:
            self.since = since
        self.seen = {event: at for event, at in self.seen.items() if at > self.since}

    def ours(self, body):
        repository = body.get('repository') or (body.get('pullRequest') or {}).get('repository') or {}
        owner = (repository.get('owner') or {}).get('slug')
        return not (owner and repository.get('name')) or f"{owner}/{repository['name']}" == self.repo

    def consider(self, db, branch, head):
        if head in self.bundles:
            self.resolve(db, branch, head)
        elif head not in self.pending:
            self.job(db, branch, head)

    def job(self, db, branch, head):
        """The head's bundle job, `scripts/gate-check artifact code`, on the container executor (the gate's queue)."""
        base = self.base(db)
        if base is None:
            self.bundles[head] = None
            LOG.warning('prewarm: no push of the base seen in 7 days: %s of %s stays on the slow path', head[:12], branch)
            self.resolve(db, branch, head)
            return
        spec = {'repo': self.repo, 'ref': self.refs.get(head, f'refs/heads/{branch}'), 'commit': head, 'base': base,
                'timeout_s': TIMEOUT_S,
                'command': ['scripts/gate-check', 'artifact', 'code', '--base', base]}
        tenant = db.rows(TENANT_ID, {'tenant': self.tenant})[0][0]
        made = port.create_job(db, ('tenant', tenant), {
            'queue': QUEUE, 'rank': RANK, 'selector': {'adapter': 'container'}, 'memoize': False,
            'input_uri': forge.encode(spec), 'input_digest': 'sha256:' + hashlib.sha256(
                f'prewarm-code\0{head}\0{base}'.encode()).hexdigest(), 'idempotency_key': f'prewarm:code:{head}'})
        self.pending[head] = made['id']
        LOG.info('prewarm: %s pushed %s: bundle job %s (base %s)', branch, head[:12], made['id'], base[:12])
        # PORT-WARM-ON-PUSH: a head was pushed, a delivery of it is coming: the port's Lambda is asked for its health
        # now, without waiting for the answer, so an environment is warm when the delivery's first call comes (a cold one
        # costs it about 1.9 s, the login to the database alone 1 s: live 12/11). By the event, never by a clock
        if self.warm is not None:
            try:
                self.warm()
            except Exception as error:  # noqa: BLE001 - a courtesy: the delivery's first call is then the cold one
                LOG.warning('prewarm: the port was not warmed for %s: %s', head[:12], error)

    def base(self, db):
        branch = self.config.get('deploy.base_branch') if self.config is not None else 'mod/roadmap-integration'
        ref, found = f'refs/heads/{branch}', None
        for (updates,) in db.rows(BASE, {'ref': json.dumps([{'ref': ref}])}):
            for update in json.loads(updates or 'null') or []:
                if update.get('ref') == ref and not update.get('deleted') and SHA.match(str(update.get('after') or '')):
                    found = update['after']
        return found

    def settle(self, db):
        """The bundle jobs that ended: each head waiting on one moves its branches."""
        if not self.pending:
            return
        heads = {job: head for head, job in self.pending.items()}
        for job, state, result in db.rows(JOBS, {'ids': ','.join(heads)}):
            if state not in ENDED:
                continue
            head = heads[job]
            del self.pending[head]
            self.bundles[head], why = answer(state, result)
            if why:
                LOG.info('prewarm: %s is on the slow path: %s', head[:12], why)
            for branch in [branch for branch, at in self.heads.items() if at == head]:
                self.resolve(db, branch, head)

    def resolve(self, db, branch, head):
        bundle = self.bundles.get(head)
        if bundle is None:
            self.release(db, branch, f'its head {head[:12]} is on the slow path')
            return
        key, sha = bundle
        if self.holds.get(branch) == sha:
            return
        self.release(db, branch, f'its head moved to {head[:12]}')
        if sha not in self.standbys and not self.start(db, sha, key, branch):
            return
        self.standbys[sha]['branches'].add(branch)
        self.holds[branch] = sha

    def release(self, db, branch, why):
        sha = self.holds.pop(branch, None)
        group = self.standbys.get(sha)
        if group is not None:
            group['branches'].discard(branch)
            if not group['branches']:
                self.stop(db, sha, f'{branch}: {why}')

    # --- SWAP-MEASURE ---------------------------------------------------------------------------------------------------
    def measure(self, db):
        """The round in flight, one step a look: what the log says of it is where it is."""
        rounds = {}
        for payload, at in db.rows(MEASURES):
            event = json.loads(payload)
            rounds.setdefault(str(event.get('round')), {})[event.get('state')] = dict(event, occurred=float(at))
        open_ = [said for said in rounds.values() if 'asked' in said and not {'done', 'failed'} & set(said)]
        self.measuring = None
        if not open_:
            return
        said = min(open_, key=lambda each: each['asked']['occurred'])
        self.measuring = str(said['asked']['round'])
        try:
            self.measure_step(db, said)
        except Exception as error:  # noqa: BLE001 - a round that cannot go on says why, and another may be asked
            LOG.exception('prewarm: the measured round %s failed', self.measuring)
            self.measured(db, said, 'failed', why=f'{type(error).__name__}: {error}'[:300])

    def measured(self, db, said, state, **more):
        """A step of the round said (once each): platform.deploy.measure {round, drill, state, ...}."""
        asked = said['asked']
        payload = {'round': asked['round'], 'drill': asked.get('drill', True), 'state': state, **more}
        db.rows(MEASURE_SAY, {'id': f"{MEASURE}:{asked['round']}:{state}", 'payload': json.dumps(payload)})
        said[state] = dict(payload, occurred=self.clock())
        if state in ('done', 'failed'):
            branch = MEASURE_HEAD + str(asked['round'])
            self.heads.pop(branch, None)
            self.release(db, branch, f'its measured round is {state}')  # a bundle the pointers name stays (stop())
            self.measuring = None
        LOG.info('prewarm: measured round %s %s%s', asked['round'], state, f': {more}' if more else '')

    def measure_step(self, db, said):
        asked, round_ = said['asked'], str(said['asked']['round'])
        drill, branch = asked.get('drill', True) is not False, MEASURE_HEAD + round_
        if self.clock() - asked['occurred'] > MEASURE_LIMIT_S:
            return self.measured(db, said, 'failed', why=f'not done in {MEASURE_LIMIT_S} s', reached=sorted(said))
        if 'swapped' in said:
            return self.measure_live(db, said)
        if self.intask() <= 0:
            return self.measured(db, said, 'failed', why=f'{live_image.SUCCESSORS} is 0: no successor to swap onto')
        if 'built' not in said:
            return self.measure_build(db, said, round_)
        sha, key, base = said['built']['digest'], said['built']['key'], said['built']['base']
        if 'wanted' not in said:
            if base != self.base(db):
                return self.measured(db, said, 'failed', why='the base moved while the bundle was built')
            live = set(self.pointers(db).values())
            if sha in live:
                return self.measured(db, said, 'failed', why=f'the pointers name {sha[:12]} already')
            held = [each for each in self.standbys if each not in live and each != sha and not self.retiring(each)]
            if held:  # the slot is a delivery's: a round never takes it (a push takes it from a round: start())
                return self.measured(db, said, 'failed', why=f"the successor slot holds {held[0][:12]} of "
                                     f"{', '.join(sorted(self.standbys[held[0]]['branches'])) or 'no branch'}")
            group = self.standbys.setdefault(sha, {'at': self.clock(), 'branches': set(), 'tasks': {}, 'key': key,
                                                   'tries': {}, 'tried': {}, 'why': {}})
            group['branches'].add(branch)
            self.holds[branch], self.heads[branch] = sha, base
            self.want(db, sha, group, branch)  # the successors, as for a pushed head (no Spot task: no cost of its own)
            return self.measured(db, said, 'wanted', digest=sha)
        if self.holds.get(branch) != sha:
            return self.measured(db, said, 'failed', why='its successors were withdrawn (a push took the slot)')
        fresh_s = self.config.get('deploy.standby_fresh_s') if self.config is not None else 10
        roles = {}
        for role, state, armed, at in db.rows(SAID_BY, {'since': said['wanted']['occurred'] - OVERLAP_S, 'digest': sha}):
            roles.setdefault(state, {}).setdefault(role, []).append((float(at), armed == 'true'))
        if 'ready' not in said:
            beating = set(filter(None, str((db.rows(BEAT_ROLES, {'digest': sha, 'fresh_s': fresh_s}) or [('',)])[0][0]).split(',')))
            if not set(ROLES) <= set(roles.get('warm', {})) or not set(ROLES) <= beating:
                return None  # their `warm` and beats wake the look (tower_deploy)
            warm_at = max(min(at for at, _ in roles['warm'][role]) for role in ROLES)
            if not set(ROLES) <= set(roles.get('reserve', {})) and self.clock() - warm_at < RESERVE_WAIT_S:
                return None  # each reserve's word wakes the look; the bound is looked at within POLL_S
            for role in ROLES if drill else ():  # SWAP-DRILL: born before it, both successors end as they turn live
                db.rows(DRILL_ASK, {'id': f'{live_image.DRILL_EVENT}:{role}:{sha}:{MEASURE}:{round_}', 'payload': json.dumps(
                    {'digest': sha, 'role': role, 'kind': 'lost-at-swap', 'round': round_})})
            found = db.rows(port.READY_ROLES, {'digest': sha, 'fresh_s': fresh_s})  # the delivery's question, its NOTIFY
            if not found or found[0][1] is None:
                return None  # a beat went stale meanwhile: the next one wakes the look
            return self.measured(db, said, 'ready', digest=sha, reserves=sorted(roles.get('reserve', {})))
        ready_at = said['ready']['occurred']
        heard = {role: [armed for at, armed in roles.get('rehearsed', {}).get(role, []) if at >= ready_at - 1]
                 for role in ROLES}
        if not all(any(each) if drill else each for each in heard.values()):
            return None  # each successor's rehearsal on the readiness reading (armed, drilled) wakes the look
        beating = set(filter(None, str((db.rows(BEAT_ROLES, {'digest': sha, 'fresh_s': fresh_s}) or [('',)])[0][0]).split(',')))
        if not set(ROLES) <= beating:
            return None
        at = self.clock()
        found = db.rows(autodeploy_swap(), {
            'tenant': self.tenant, 'digest': sha, 'keys': ','.join(live_image.KEYS[role] for role in ROLES),
            'reason': f'SWAP-MEASURE: round {round_}, {base[:12]} again, its successors beat', 'landed_at': at,
            'id': f'platform.deploy.image_swap:measure:{round_}', 'payload': json.dumps(
                {'digest': sha, 'key': key, 'head': base, 'by': 'measure', 'round': round_, 'drill': drill})})
        if not found:
            return self.measured(db, said, 'failed', why=f'no pointer written (no tenant {self.tenant})')
        swap = json.loads(found[0][0])
        return self.measured(db, said, 'swapped', digest=sha, head=base, landed_s=swap.get('landed_s'),
                             versions=swap.get('versions'))

    def measure_build(self, db, said, round_):
        """The published head's bundle with the round's mark: the push's bundle job (`artifact code`), its base its head."""
        base = said.get('building', {}).get('base') or self.base(db)
        if base is None:
            return self.measured(db, said, 'failed', why='no push of the base seen in 7 days')
        salt = f'measure-{round_}'
        spec = {'repo': self.repo, 'ref': 'refs/heads/' + (self.config.get('deploy.base_branch') if self.config is not None
                                                           else 'mod/roadmap-integration'),
                'commit': base, 'base': base, 'timeout_s': TIMEOUT_S,
                'command': ['scripts/gate-check', 'artifact', 'code', '--base', base, '--salt', salt]}
        tenant = db.rows(TENANT_ID, {'tenant': self.tenant})[0][0]
        made = port.create_job(db, ('tenant', tenant), {
            'queue': QUEUE, 'rank': RANK, 'selector': {'adapter': 'container'}, 'memoize': False,
            'input_uri': forge.encode(spec), 'input_digest': 'sha256:' + hashlib.sha256(
                f'prewarm-code\0{base}\0{salt}'.encode()).hexdigest(), 'idempotency_key': f'prewarm:code:{base}+{salt}'})
        if 'building' not in said:
            return self.measured(db, said, 'building', base=base, job=made['id'])
        found = db.rows(JOBS, {'ids': made['id']})
        if not found or found[0][1] not in ENDED:
            return None  # the job's end wakes the look (tower_work)
        bundle, why = answer(found[0][1], found[0][2])
        if bundle is None:
            return self.measured(db, said, 'failed', why=why)
        return self.measured(db, said, 'built', base=base, key=bundle[0], digest=bundle[1])

    def measure_live(self, db, said):
        """Done once both roles said image_live of the round's bundle after its swap and the ECS task of each took it over
        ({state: reloaded}): the round ends where a landing does, so the next one starts from the same place."""
        sha, since = said['swapped']['digest'], said['swapped']['occurred'] - OVERLAP_S
        seen = {row[0] for row in db.rows(LIVE_ROLES, {'digest': sha, 'since': since})}
        if all(f'platform.deploy.{kind}:{role}' in seen for kind in ('image_live', 'image_reload') for role in ROLES):
            return self.measured(db, said, 'done', digest=sha, head=said['swapped'].get('head'))
        return None

    # --- the tasks ----------------------------------------------------------------------------------------------------
    def pointers(self, db):
        """{role: the digest deploy.live_image_<role> names} ('' for none)."""
        found = {}
        for role, key in live_image.KEYS.items():
            rows = db.rows(live_image.READ, {'tenant': self.tenant, 'key': key})
            found[role] = str(json.loads(rows[0][0]) or '').strip() if rows else ''
        return found

    def start(self, db, sha, key, branch):
        """One standby per role for the bundle, within the cap (the newest push wins); answers whether it started."""
        if self.was_promoted(db, sha):  # PREWARM-MERGED-RELEASED: a landing swapped onto this bundle already: it is the
            LOG.info('prewarm: %s of %s landed already: no standby of it', sha[:12], branch)  # code that runs, or ran
            return False
        spot, live = self.cap(), set(self.pointers(db).values())
        cap = max(spot, self.intask())  # IN-TASK-STANDBY: the bundles held: a Spot pair, a successor in each task, or both
        while True:
            counted = [each for each in self.standbys if each not in live and not self.retiring(each)]
            if len(counted) < cap:
                break
            if not counted:
                LOG.info('prewarm: deploy.prewarm_max_tasks is %d: %s of %s stays on the slow path', cap, sha[:12], branch)
                return False
            oldest = min(counted, key=lambda each: self.standbys[each]['at'])
            # PREWARM-TRAIN-SLOT; LANDING-KEEPS-STANDBY: nor while its merged PR's landing is still to be said
            if self.in_train(db, oldest) or self.standbys[oldest]['branches'] & set(self.landing):
                LOG.info('prewarm: the slot stays with %s, whose delivery is in the merge train: %s of %s waits for it',
                         oldest[:12], sha[:12], branch)
                self.waiting[branch] = self.heads.get(branch)
                return False
            LOG.warning('prewarm: over deploy.prewarm_max_tasks=%d: the newest push (%s) wins; %s of %s fall back to the '
                        'slow path', cap, branch, ', '.join(sorted(self.standbys[oldest]['branches'])) or 'no branch',
                        oldest[:12])
            for each in self.standbys[oldest]['branches']:
                self.holds.pop(each, None)
            self.standbys[oldest]['branches'].clear()
            if not self.stop(db, oldest, f'over deploy.prewarm_max_tasks={cap}: {branch} pushed later'):
                return False
        group = self.standbys[sha] = {'at': self.clock(), 'branches': set(), 'tasks': {}, 'key': key, 'tries': {},
                                      'tried': {}, 'why': {}}
        for role in ROLES if spot > 0 else ():
            self.run(db, sha, key, branch, role, group)
        if self.intask() > 0:
            self.want(db, sha, group, branch)
        return True  # PREWARM-RETRY: a bundle with no task yet is kept: watch() tries its roles again

    def run(self, db, sha, key, branch, role, group):
        environment = [{'name': 'TOWER_CODE_KEY', 'value': key}, {'name': 'TOWER_CODE_SHA256', 'value': sha},
                       {'name': 'TOWER_IMAGE_DIGEST', 'value': sha}, {'name': live_image.STANDBY, 'value': '1'}]
        group.setdefault('tries', {})[role] = group['tries'].get(role, 0) + 1  # PREWARM-RETRY
        group.setdefault('tried', {})[role] = self.clock()
        try:
            out = self.ecs.run_task(
                cluster=self.cluster, taskDefinition=FAMILIES[role], count=1, platformVersion='LATEST',
                capacityProviderStrategy=[{'capacityProvider': 'FARGATE_SPOT', 'weight': 1}],
                networkConfiguration={'awsvpcConfiguration': self.network}, startedBy=PRODUCER,
                overrides={'containerOverrides': [{'name': CONTAINERS[role], 'environment': environment}]},
                tags=[{'key': 'project', 'value': 'tower'}, {'key': 'role', 'value': role}, {'key': 'digest', 'value': sha},
                      {'key': 'branch', 'value': branch[:256]}])
            if not out.get('tasks'):
                raise RuntimeError(f"no task: {out.get('failures')}")
            task = out['tasks'][0]['taskArn']
        except Exception as error:  # noqa: BLE001 - that role stays on the slow path; the other may still stand by
            LOG.error('prewarm: RunTask of the %s standby of %s failed: %s', role, sha[:12], error)
            if group.setdefault('why', {}).get(role) != str(error)[:300]:  # PREWARM-RETRY: the same refusal is one event
                group['why'][role] = str(error)[:300]
                self.record(db, role, sha, '', branch, 'failed', str(error)[:300])
            return
        group.setdefault('why', {}).pop(role, None)
        group['tasks'][role] = {'task': task, 'state': 'started', 'since': self.clock(), 'branch': branch,
                                'started_at': int(self.clock())}
        self.record(db, role, sha, task, branch, 'started', started_at=group['tasks'][role]['started_at'])
        LOG.info('prewarm: %s standby of %s started for %s: %s', role, sha[:12], branch, task)

    def stop(self, db, sha, why):
        """StopTask of the bundle's live tasks; answers whether they are gone. One the pointer names stays (phase C)."""
        group = self.standbys[sha]
        if sha in set(self.pointers(db).values()):
            LOG.info('prewarm: %s is the pointer\'s: its standbys stay (%s)', sha[:12], why)
            return False
        promoted = self.was_promoted(db, sha)
        for role, task in list(group['tasks'].items()):
            if task['state'] == RETIRING:
                continue
            if promoted and role == 'runner':  # IMAGE-PREWARM-C: it exits on its own once its runs in flight end
                task.update(state=RETIRING, since=self.clock())
                self.record(db, role, sha, task['task'], task['branch'], RETIRING, why, task.get('started_at'))
                LOG.info('prewarm: the promoted runner standby of %s is retiring: %s', sha[:12], task['task'])
                continue
            if task['state'] in ALIVE:
                # STANDBY-GRACE: recorded before the StopTask: the standby reads it at its SIGTERM and leaves at once (one
                # that the engine did not dismiss stays through Spot's warning); the same event again if StopTask fails
                self.record(db, role, sha, task['task'], task['branch'], 'stopped', why, task.get('started_at'))
                try:
                    self.ecs.stop_task(cluster=self.cluster, task=task['task'], reason=f'IMAGE-PREWARM-B2: {why}'[:255])
                except Exception:  # noqa: BLE001 - kept: the next look stops it again (watch)
                    LOG.exception('prewarm: StopTask of %s failed', task['task'])
                    return False
            del group['tasks'][role]
        if group.get('wanted'):  # IN-TASK-STANDBY: the ECS tasks stop their successors of it (one that adopted the role stays)
            self.want(db, sha, group, None, 'withdrawn', why)
        if group['tasks']:  # IMAGE-PREWARM-C: only the retiring runner is left; watch() sees it go
            return True
        del self.standbys[sha]
        LOG.info('prewarm: the standbys of %s stopped: %s', sha[:12], why)
        return True

    def was_promoted(self, db, sha):
        """IMAGE-PREWARM-C: whether a landing swapped the pointers to this bundle (platform.deploy.image_swap, swapped)."""
        if sha not in self.promoted and db.rows(PROMOTED, {'sha': sha}):
            self.promoted.add(sha)
        return sha in self.promoted

    def retiring(self, sha):
        tasks = self.standbys[sha]['tasks'].values()
        return bool(tasks) and all(task['state'] == RETIRING for task in tasks)

    def spare(self, db):
        """PREWARM-ONE-LOOK: the second standby of a bundle's role the log gave back (restore) is stopped: recorded
        `stopped` first, as any standby the engine dismisses (STANDBY-GRACE), then StopTask. Not while the pointer names
        its bundle (a promoted standby that is stopped hands the pointer back: the swap would go back with it); a promoted
        runner leaves by itself once its runs end. A StopTask that fails is tried on EXTRA_TRIES looks."""
        if not self.extras:
            return
        live, left = set(self.pointers(db).values()), []
        for sha, role, task, branch, started_at, tries in self.extras:
            if sha in live:
                left.append([sha, role, task, branch, started_at, tries])
                continue
            why = 'one standby per role of a bundle: another service started this one too'
            if role == 'runner' and self.was_promoted(db, sha):
                self.record(db, role, sha, task, branch, RETIRING, why, started_at)
                continue
            self.record(db, role, sha, task, branch, 'stopped', why, started_at)
            try:
                self.ecs.stop_task(cluster=self.cluster, task=task, reason=f'PREWARM-ONE-LOOK: {why}'[:255])
                LOG.warning('prewarm: stopped a second %s standby of %s: %s', role, sha[:12], task)
            except Exception:  # noqa: BLE001 - tried again on the next looks, then left to Spot and to the next restore
                LOG.exception('prewarm: StopTask of the second %s standby %s failed', role, task)
                if tries + 1 < EXTRA_TRIES:
                    left.append([sha, role, task, branch, started_at, tries + 1])
        self.extras = left

    def watch(self, db):
        """A bundle no branch holds is stopped (again, if StopTask failed); then the health of the live tasks."""
        self.spare(db)  # PREWARM-ONE-LOOK
        for sha in [sha for sha, group in self.standbys.items() if not group['branches']]:
            self.stop(db, sha, 'no branch holds it')
        if self.standbys:  # IMAGE-PREWARM-C: a promoted bundle no pointer names any more is retired, branch or not
            live = set(self.pointers(db).values())
            for sha in [sha for sha in self.standbys if sha not in live and not self.retiring(sha)
                        and self.was_promoted(db, sha)]:
                self.stop(db, sha, 'retired: the ECS tasks took its role over')
        for branch, (head, since) in list(self.landing.items()):  # LANDING-KEEPS-STANDBY: released by the landing's word
            said = bool(head) and bool(db.rows(LANDED, {'head': head}))
            if said or branch not in self.holds or self.clock() - since >= LANDING_S:
                del self.landing[branch]
                self.heads.pop(branch, None)
                self.release(db, branch, 'its PR was merged' if said else 'its PR was merged and no landing was said')
        for branch, head in list(self.waiting.items()):  # PREWARM-TRAIN-SLOT: the slot may be free now (a landing is an event)
            del self.waiting[branch]
            if self.heads.get(branch) == head and branch not in self.holds:
                self.resolve(db, branch, head)
        for sha, role in self.missing():  # PREWARM-RETRY: a role with no task is tried again, RETRY_S apart
            group = self.standbys[sha]
            if self.clock() - group['tried'].get(role, 0) >= RETRY_S and sha not in set(self.pointers(db).values()):
                self.run(db, sha, group['key'], sorted(group['branches'])[0], role, group)
        tasks = {task['task']: (sha, role, task) for sha, group in self.standbys.items()
                 for role, task in group['tasks'].items() if task['state'] in ALIVE + (RETIRING,)}
        if not tasks or self.clock() - self.described < POLL_S:
            return
        self.described = self.clock()
        out = self.ecs.describe_tasks(cluster=self.cluster, tasks=list(tasks)[:100])
        seen = {each['taskArn']: each for each in out.get('tasks') or []}
        for arn, (sha, role, task) in tasks.items():
            found = seen.get(arn) or {'lastStatus': 'STOPPED', 'stoppedReason': 'ECS does not know the task'}
            if task['state'] == RETIRING:
                self.retired(db, sha, role, task, found)
            elif found.get('lastStatus') == 'STOPPED' or found.get('desiredStatus') == 'STOPPED':
                # STANDBY-GRACE: a task ECS is stopping (Spot's warning: desiredStatus STOPPED two minutes before the end)
                # is replaced now, not when it is gone: it stands by meanwhile (live_image.on_term)
                self.failed(db, sha, role, task, found.get('stoppedReason') or found.get('stopCode') or 'stopped')
            elif task['state'] == 'started' and found.get('healthStatus') == 'HEALTHY':
                task['state'] = 'healthy'
                self.standbys[sha].setdefault('tries', {})[role] = 0  # STANDBY-GRACE: RETRY_MAX counts refusals in a row, not a day's interruptions
                self.record(db, role, sha, arn, task['branch'], 'healthy', started_at=task.get('started_at'))
                LOG.info('prewarm: %s standby of %s is healthy: %s', role, sha[:12], arn)
            elif task['state'] == 'started' and self.clock() - task['since'] > START_LIMIT_S:
                try:
                    self.ecs.stop_task(cluster=self.cluster, task=arn, reason=f'IMAGE-PREWARM-B2: not healthy in {START_LIMIT_S} s')
                except Exception:  # noqa: BLE001 - recorded failed all the same; a task stuck starting stops itself
                    LOG.exception('prewarm: StopTask of %s failed', arn)
                self.failed(db, sha, role, task, f'not healthy in {START_LIMIT_S} s')

    def retired(self, db, sha, role, task, found):
        """IMAGE-PREWARM-C: a retiring runner standby: gone once ECS says STOPPED (it exited: its runs ended); one still up
        after RETIRE_LIMIT_S is stopped."""
        if found.get('lastStatus') != 'STOPPED':
            if self.clock() - task['since'] <= RETIRE_LIMIT_S:
                return
            try:
                self.ecs.stop_task(cluster=self.cluster, task=task['task'],
                                   reason=f'IMAGE-PREWARM-C: still retiring after {RETIRE_LIMIT_S} s')
            except Exception:  # noqa: BLE001 - the next look tries again
                LOG.exception('prewarm: StopTask of %s failed', task['task'])
                return
            found = {'stoppedReason': f'still retiring after {RETIRE_LIMIT_S} s: stopped'}
        group = self.standbys[sha]
        del group['tasks'][role]
        self.record(db, role, sha, task['task'], task['branch'], 'stopped',
                    f"retired: {found.get('stoppedReason') or 'it exited'}", task.get('started_at'))
        LOG.info('prewarm: the promoted %s standby of %s is gone: %s', role, sha[:12], task['task'])
        if not group['tasks']:
            del self.standbys[sha]

    def failed(self, db, sha, role, task, why):
        group = self.standbys[sha]
        del group['tasks'][role]
        self.record(db, role, sha, task['task'], task['branch'], 'failed', why, task.get('started_at'))
        LOG.warning('prewarm: %s standby of %s failed (%s): %s on the slow path for that role', role, sha[:12], why,
                    ', '.join(sorted(group['branches'])) or 'no branch')
        # STANDBY-GRACE: a standby that was healthy and was taken away (Spot) is replaced in this look, not RETRY_S later
        # (live 11/11: 51 s to the retry, then ~95 s to healthy); a RunTask refused is PREWARM-RETRY's, as before
        if task['state'] == 'healthy' and group['branches'] and sha not in set(self.pointers(db).values()):
            self.run(db, sha, group['key'], sorted(group['branches'])[0], role, group)
        if not group['tasks'] and not group.get('wanted'):  # IN-TASK-STANDBY: a bundle with a successor wanted is still held
            for branch in group['branches']:
                self.holds.pop(branch, None)
            del self.standbys[sha]

    def record(self, db, role, sha, task, branch, state, why=None, started_at=None):
        at = int(self.clock())
        payload = {'role': role, 'digest': sha, 'task': task, 'branch': branch, 'state': state, 'at': at,
                   **({'why': why} if why else {}),
                   **({'started_at': started_at} if started_at else {})}  # IMAGE-PREWARM-C: prewarm_task_usd
        db.rows(RECORD, {'id': f'platform.deploy.standby:{role}:{sha}:{task or at}:{state}', 'role': role,
                         'payload': json.dumps(payload)})



def autodeploy_swap():
    """SWAP-MEASURE: the pointers' statement of the autodeploy's swaps (autodeploy.SWAP_WRITE: both pointers and the
    image_swap event in one statement), imported when a round swaps (autodeploy imports what this module does not)."""
    from . import autodeploy
    return autodeploy.SWAP_WRITE


PORT = 'tower-port-api'


def port_warm(lam):
    """PORT-WARM-ON-PUSH: the call that warms the port: its live alias asked for GET /v1/health as an event (202 at
    once; Lambda runs it on an idle environment or starts one). The service's role already invokes this function (the
    fast deploy's smoke)."""
    def warm():
        lam.invoke(FunctionName=PORT, Qualifier=fastdeploy.ALIAS, InvocationType='Event',
                   Payload=json.dumps(fastdeploy.SMOKE[PORT]).encode())
    return warm


def configured(environ=None):
    """Whether the environment names the cluster, the network and the bucket the look needs (from_boto3)."""
    environ = os.environ if environ is None else environ
    return bool(environ.get('TOWER_STANDBY_CLUSTER', '').strip() and environ.get('TOWER_STANDBY_SUBNETS', '').strip()
                and environ.get('TOWER_STANDBY_SECURITY_GROUPS', '').strip() and environ.get('TOWER_ARTIFACT_BUCKET'))


def from_boto3(scope, config=None, environ=None):
    """The live service's Prewarm, or None without TOWER_STANDBY_CLUSTER (a local run) or the network to run tasks in."""
    environ = os.environ if environ is None else environ
    cluster = environ.get('TOWER_STANDBY_CLUSTER', '').strip()
    subnets = [each.strip() for each in environ.get('TOWER_STANDBY_SUBNETS', '').split(',') if each.strip()]
    groups = [each.strip() for each in environ.get('TOWER_STANDBY_SECURITY_GROUPS', '').split(',') if each.strip()]
    if not (cluster and subnets and groups and environ.get('TOWER_ARTIFACT_BUCKET')):
        return None
    import boto3
    from botocore.config import Config
    ecs = boto3.client('ecs', region_name=environ.get('AWS_REGION'),
                       config=Config(connect_timeout=3, read_timeout=15, retries={'max_attempts': 2}))
    lam = boto3.client('lambda', region_name=environ.get('AWS_REGION'),
                       config=Config(connect_timeout=2, read_timeout=5, retries={'max_attempts': 1}))
    return Prewarm(scope, ecs, cluster, {'subnets': subnets, 'securityGroups': groups, 'assignPublicIp': 'ENABLED'},
                   tenant=environ.get('TOWER_CONFIG_TENANT', config_data.TENANT), config=config,
                   repo=environ.get('TOWER_PREWARM_REPO') or engine.repo(environ), warm=port_warm(lam))


def start(scope, stop, wait, config=None, active=None, environ=None, gate=None, make=None):
    """The look in a daemon thread; answers the thread, or None when not configured. active (the service's live_image gate)
    answers False while this image stands by: a standby makes no job and runs no task. gate (IMAGE-SWAP-RELOAD: that gate)
    counts a look as work in flight (engaged), which a reload of the task waits for (a RunTask, a StopTask); once a reload
    holds the gate no look starts."""
    import threading
    make = make or (lambda: from_boto3(scope, config, environ))
    # LOOKS-AFTER-WORK: a process the role waits for makes the look's ECS and Lambda clients after its first work
    later = live_image.waited_for(gate) and configured(environ)
    watcher = None if later else make()
    if watcher is None and not later:
        LOG.info('prewarm: off (no TOWER_STANDBY_CLUSTER, subnets, groups or artifact bucket)')
        return None

    def loop():
        nonlocal watcher
        if watcher is None:
            gate.worked.wait(live_image.FIRST_WORK_S)
            watcher = make()
            if watcher is None:
                return
        while not stop.is_set():
            with live_image.engaged(gate, 'prewarm') as free:
                pause = watcher.step() if free and (active is None or active()) else None
            if pause is None:  # IMAGE-SWAP-FAILOVER: an ECS service that takes the role back resumes from the log, not its memory
                watcher.forget()
                # ADOPTED-LOOKS: a process live but not yet the role's only one (a promoted successor before it adopted
                # the role, seconds) looks again within POLL_S: its adoption is said in the log but wakes nothing here, and
                # the round of 13/11 01:36 UTC was said done 5 min after its end (SAFETY_S). A standby waits as before
                pause = POLL_S if gate is not None and getattr(gate, 'active', lambda: False)() else SAFETY_S
            wait(pause)
    thread = threading.Thread(target=loop, name='prewarm', daemon=True)
    thread.start()
    if watcher is not None:
        LOG.info('prewarm: following the unit branches, at most %d standby bundle(s)', watcher.cap())
    return thread
