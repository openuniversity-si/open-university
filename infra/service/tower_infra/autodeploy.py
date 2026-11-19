"""The deploy that rings itself (AUTO1): after a merge into the deploy base branch, inside AWS, with no human and no token.

The service reads what the ingress already recorded in the log (forge.repository.pushed with a refUpdate of the base
branch) and, when a head newer than the last deployed one has settled, invokes the doorbell Lambda directly with the
task role (lambda:InvokeFunction on that one function). The doorbell starts the deploy build, which reads the base head
from Origin itself, so the caller never chooses what is deployed. Nothing here is on the webhook's path: the ingress is
untouched and this runs in its own thread of the serve process, rate limited to one look every check_every_s.

Per look, in this order, one line says ring or skip with the reason (docs/operations/aws.md, 19):
  off (deploy.auto) / no doorbell configured / the doorbell answered 409 less than running_retry_s ago /
  no push to the base seen / the head is the deployed one (memory, then /tower/deploy/last-sha and last-build) /
  debounce (the newest push is younger than debounce_s: a burst of merges is one build) /
  the head failed in the last build (no clock: only a new push, a fix or the deploy-ended event rings it again) /
  another task holds the advisory lock / a ring whose build has not ended /
  the month's estimated spend is at monthly_usd (the hard stop; alarm_usd, the alarm, speaks first).
DEP7, the slow path: no daily cap and one build in flight; when it ends the next ring takes the CURRENT head (the build
reads the head of Origin itself), so every merge in between is coalesced. A push that only changed fast targets or files
no deploy needs (see slow_path) does not ring: it is recorded as platform.deploy.pending. DEP8: a push that changed a port
Lambda's files is swapped by pointer first (swap(), fastdeploy.py: UpdateFunctionCode, UpdateAlias, smoke, rollback). The
build is selective (infra/aws/deploy.sh classifies last-sha..head itself) and bisects a failed batch; a bisection in
progress is never held back. Every ended build is a platform.deploy.cycle event (seconds, usd, targets)
and the month's total reaching alarm_usd publishes platform.deploy.cost_alarm once and a line in GET /v1/deploy/status.
Every ring is a platform.deploy.rung event of the log and every build that ended is settled with its seconds as a
platform.deploy.settled event: the caps and the budget survive a restart (a deploy replaces this very task) from the
log, and the doorbell, which allows one build at a time, is the last word when two tasks look at once.

DEP-WATCHDOG (a safety timeout for failure, never a timer for waiting): deploy.sh writes last-build at its START (status
in_progress, the current step, `updated` at each step) and records a failed end on ANY exit. A ring whose build has not ended
after deploy.lost_after_s (3000: the deployer budget 2400 + margin), or whose in_progress record stopped updating for longer
than the budget, is LOST: one platform.deploy.lost event ('lost: no ended build after N s') and the current head is rung at
once. GET /v1/deploy/status shows the in_progress build (step, elapsed_s) and the last lost one.

SLOW-PATH-NO-ROLLOUT-WAIT (docs/operations/aws.md 22.10): the live service applies the migrations of the head a build is
deploying, ahead of that head's tasks (migrate(): the code bundle deploy.sh names in last-build.migrate), so the runner's
rollout never waits for the service's. And no build waits for an ECS rollout: deploy.sh starts the update of the service and
runner stacks and ends `rolling`; the build that verifies them (the smoke, the rollback, last-sha) is rung here when each
stack's rollout is seen (rolling(): the stack's new task says it is up, platform.deploy.task_up, or the CloudFormation
event the port records says the stack ended, whichever is first; both wake this look; last-build.rolling.until is the
safety of a rollout that says neither), and nothing else is rung meanwhile. A code-only landing needs no rollout to last: after a swap the
look writes deploy.live_code (live_code(): '<bundle sha256>@<merge>'), which a task ECS starts later boots from
(code_bundle.boot) and which lets deploy.sh leave the service and runner stacks alone.

RELOAD-WITHOUT-STANDBY (docs/operations/aws.md 22.9; live_image.Order): a code-only landing whose bundle is the merge's code
and whose standby pair is not there is not left to the two rollouts: the look orders the ECS tasks to load the bundle in
place (order(): platform.deploy.image_reload {state: ordered}, one order at a time, the newest head after the one in flight
settles), holds that head's ring while they do (reloading(): live_image.ORDER_LIMIT_S from the landing at most), records
their canaries' verdicts and, once both roles are proven, writes deploy.live_code (reloads()): the build that is rung then
finds the head's code live and deploys neither the image nor the two stacks.

FAST-PATH-RELOAD (GATE-SHUTDOWN, D-314; the Torre, 14/11): on GitHub no landing reaches this look and no runner exists,
so a code-only merge's deploy build asks for the reload itself: deploy.sh publishes the head's bundle and names it in
last-build.reload {key, sha256, head} while the build is in progress; the look (build_reload()) orders the service alone to
load it in place (order(): roles ['service'], by: build; one order at a time, never a bundle a reload failed on), and the
service proves its own reload (live_image.PROVE_*); its `proven` wakes this look, which writes deploy.live_code (reloads()),
which deploy.sh reads in GET /v1/deploy/status. An order that cannot be made says {state: declined} so the build does not
wait for it. The build's start is heard by its CodeBuild event (http_port: platform.deploy.started, which wakes this look),
and while that build may still name its reload (ASK_WINDOW_S from its start, until it leaves its classification) the
safety look is ASK_LOOK_S.

The knobs are the registry's deploy.* keys. The service has no registry file: DEFAULTS mirror the registry defaults (a
test pins them), and a `scripts/config set deploy.x` reaches the service as a config.changed event inside the commit
message of the push to train/events, which the ingress logs like any push. Nothing is cached longer than one look.
"""
import calendar
import json
import logging
import os
import re
import threading
import time

from . import canary, code_bundle, config_data, live_image, migrations

LOG = logging.getLogger('tower_infra.autodeploy')
PRODUCER = 'autodeploy'
RUNG, SETTLED, ENDED = 'platform.deploy.rung', 'platform.deploy.settled', 'platform.deploy.ended'
CYCLE, ALARM, PENDING = 'platform.deploy.cycle', 'platform.deploy.cost_alarm', 'platform.deploy.pending'
LOST = 'platform.deploy.lost'  # DEP-WATCHDOG: a ring whose build never reported its end (safety timeout for failure)
# MODE-CHANGE-ALERT (revisão da arquitetura, achado 6): a build that changed how production runs by a guard or a rollback
MODE = 'platform.deploy.mode_changed'
FAST, ROLLEDBACK = 'platform.deploy.fast', 'platform.deploy.rolledback'
LANDED = 'platform.deploy.landed'  # FAST-ON-LANDED: the delivery's word on what a merge changed (Origin's pushes list no files)
# MIGRATED-EVENT (D-331): the migrations a build asked for, applied or not ({bundle, build, state: applied|failed, applied,
# newest}), which deploy.sh's migrate_wait waits for on the status's long poll (a platform.deploy.* insert wakes tower_status)
MIGRATED = 'platform.deploy.migrated'
EVENTS_REF = 'refs/heads/train/events'
LAST_SHA, LAST_BUILD = '/tower/deploy/last-sha', '/tower/deploy/last-build'
DEPLOYER_BUDGET_S = 2400  # DEPLOY_BUDGET_S of the deployer (bootstrap.json): no stack starts after it, so an in_progress build silent for longer is lost
BUILD_MAX_S = 2700  # the deployer project's TimeoutInMinutes (45), pinned by a test against bootstrap.json
LOCK_KEY = 7424001
FAST_LOCK_KEY = 7424002  # the fast deploy: one swap at a time across service tasks (DEP8)
FAST_KEEP = 20  # the swaps GET /v1/deploy/status shows
# FAST-DURABLE: the swaps shown come back from the log after a restart (the list lived only in memory, so the status's
# `fast`, which the slow path reads to skip the port stack (#452), emptied whenever the service restarted)
FAST_SEED = ("select payload::text, extract(epoch from occurred_at)::bigint from log.event where type = 'platform.deploy.fast' "
             "and tenant_id is null and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s")
AWAY, AWAY_S = 'another task is swapping this function', 600  # FAST-SEEN-ACROSS-TASKS: the skip that is read again, and for how long
BISECT_EPOCH = 2  # mirrors BISECT_EPOCH in infra/aws/deploy.sh (a test pins them): an older state is leftover, not a bisection
BISECT_MAX_BUILDS = 8  # mirrors DEPLOY_BISECT_MAX_BUILDS' default
OK = ('succeeded', 'nothing_new')
DEFAULTS = {'auto': True, 'base_branch': 'mod/roadmap-integration', 'debounce_s': 20,
            'lost_after_s': 3000, 'monthly_usd': 30.0, 'alarm_usd': 20.0, 'usd_per_min': 0.005,
            'fast_propagation_s': 10.0, 'fast_activate_s': 120.0,
            'queue_reload': True}  # QUEUE-RELOAD: the merge queue's words order a code-only merge's reload (queue_deploy)
ZERO_OK = ()
# Paths whose change needs the slow path (a stack, the image, the deployer); the service image has no scripts/, so this
# mirrors scripts/lib/deploy_classify.py, and a test pins the two on the repository's real files. An unknown set of
# paths always rings: the build classifies by itself and a no-op costs about a minute.
SLOW_PATHS = ('infra/aws/', 'infra/service/', 'infra/db/', 'infra/ingress/', 'services/runner/')
NOT_SLOW = ('infra/aws/bootstrap.json', 'infra/aws/budget.json')
# STAGED-WORKFLOWS-NONE (#135): the GitHub workflows staged for the owner to install are in no image and no stack
NOT_SLOW_DIRS = ('services/runner/github/',)

PUSHES = ("select occurred_at, payload #> '{delivery,event,payload,refUpdates}' from log.event "
          "where type = 'forge.repository.pushed' and occurred_at > %(since)s "
          "and payload #> '{delivery,event,payload,refUpdates}' @> %(ref)s::jsonb order by occurred_at")
LANDINGS = ("select occurred_at, payload from log.event where type = 'platform.deploy.landed' and occurred_at > %(since)s "
            "order by occurred_at")
OVERLAP_S = 60.0  # LOOK-READS-WHAT-IS-NEW: how far before the newest row it has a 7-day read reads again
LEDGER = ("select type, occurred_at, payload from log.event where type in ('platform.deploy.rung', "
          "'platform.deploy.settled', 'platform.deploy.cycle', 'platform.deploy.cost_alarm', 'platform.deploy.lost') "
          "and occurred_at > %(since)s order by occurred_at")
OBSERVED = 'platform.deploy.observed'
BEAT_PENDING_S = 900  # a skip with heads waiting (daily cap, min interval, budget) is renewed this often: never a stale 'deployed'
BEAT_S = 240  # while a ring is in flight the observation is renewed this often, so a reader can tell a silent service
OBSERVE = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
           "select %(id)s, null, 'platform.deploy.observed', clock_timestamp(), 'autodeploy', 'deploy/status', "
           "%(payload)s::jsonb where not exists (select 1 from log.event where event_id = %(id)s "
           "and type = 'platform.deploy.observed' and occurred_at > now() - interval '2 days')")
RECORD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          "values (%(id)s, null, %(type)s, clock_timestamp(), 'autodeploy', 'deploy/doorbell', %(payload)s::jsonb)")

# IMAGE-PREWARM-C (docs/operations/aws.md 22.9): the image-only swap on landing, and its retirement off the clock
SWAP = 'platform.deploy.image_swap'
ROLES = ('runner', 'service')
SWAP_LIMIT_S = 60  # a swap whose two standbys did not both say image_live by then is undone: the slow path, as before
# LANDING-PREWARM-GONE (D-316): the landing's swap onto the bundle a prewarm job built and its Spot standbys (SWAP_OF,
# BUNDLE_JOB, STANDBYS, promote) left with the prewarm; a code-only merge goes live by queue_deploy's swap or its order
# both pointers in ONE statement (one transaction: the swap is atomic across the roles) and the event that times it.
# IMAGE-SWAP-TIGHTEN: landed_s from the landing's occurred_at the look already read (landed_at), not a lookup of the log
# between the pointers' update and the commit, which delayed the NOTIFY by a scan of log.event (event_id is not its key's lead)
# SWAP-ASYNC-COMMIT: and its commit does not wait for the WAL to reach the disk, as the landing's (LANDING-ASYNC-COMMIT, port.
# LANDED_SWAP; synchronous_commit off for this transaction alone): the pointers' notification leaves at the commit, and
# the rounds by command (SWAP-MEASURE), which swap by this statement, read the pointer 0.03 to 0.85 s after its write
# (13/11), the landings 0.045 to 0.208 s. A crash inside the WAL writer's delay loses the swap's record and its pointers
# together: the ECS tasks work under no pointer, as before any swap
SWAP_WRITE = (
    "with t as (select id from work.tenant where name = %(tenant)s), "
    "c as materialized (select set_config('synchronous_commit', 'off', true) as commit), "
    "w as (insert into work.config_value as v (tenant_id, key, value, actor, reason) "
    "select t.id, k, to_jsonb(%(digest)s::text), 'autodeploy', %(reason)s from t, c, unnest(string_to_array(%(keys)s, ',')) k "
    "on conflict (tenant_id, key) do update set value = excluded.value, version = v.version + 1, actor = excluded.actor, "
    "reason = excluded.reason, updated_at = clock_timestamp() returning v.key, v.version, v.updated_at) "
    "insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
    "select %(id)s, null, 'platform.deploy.image_swap', clock_timestamp(), 'autodeploy', 'deploy/image', "
    "%(payload)s::jsonb || jsonb_build_object('swapped', true, 'versions', (select jsonb_object_agg(key, version) from w), "
    "'wrote_at', (select round(extract(epoch from max(updated_at))::numeric, 3) from w), "
    "'landed_s', (select round((extract(epoch from max(updated_at)) - %(landed_at)s::float8)::numeric, 3) from w)) "
    "where exists (select 1 from w) returning payload::text")
NEWEST_SWAP = ("select payload::text, extract(epoch from occurred_at)::float8 from log.event "
               "where type = 'platform.deploy.image_swap' and tenant_id is null and occurred_at > now() - interval '30 days' "
               "and payload->>'swapped' = 'true' order by occurred_at desc limit 1")
# SLOW-PATH-NO-ROLLOUT-WAIT: deploy.live_code = '<sha256>@<merge>' of the newest swap, written once per swap (a row newer
# than the swap, e.g. emptied by hand, is left alone); answers the value when it wrote. Only the swap of %(head)s, the
# newest head of the base: the datum never names code older than what a build deployed since (an older swap written late,
# after a build deployed a newer head, would make the tasks of that build boot the older bundle)
LIVE_CODE_WRITE = (
    "with s as (select payload->>'digest' as digest, payload->>'head' as head, occurred_at from log.event "
    "where type = 'platform.deploy.image_swap' and tenant_id is null and occurred_at > now() - interval '30 days' "
    "and payload->>'swapped' = 'true' and payload->>'head' = %(head)s order by occurred_at desc limit 1) "
    "insert into work.config_value as v (tenant_id, key, value, actor, reason) "
    "select t.id, 'deploy.live_code', to_jsonb(s.digest || '@' || s.head), 'autodeploy', "
    "'SLOW-PATH-NO-ROLLOUT-WAIT: the code of the newest image swap' from s, work.tenant t "
    "where t.name = %(tenant)s and s.digest ~ '^[0-9a-f]{64}$' and s.head ~ '^[0-9a-f]{7,64}$' "
    "on conflict (tenant_id, key) do update set value = excluded.value, version = v.version + 1, actor = excluded.actor, "
    "reason = excluded.reason, updated_at = clock_timestamp() "
    "where v.value is distinct from excluded.value and v.updated_at < (select occurred_at from s) "
    "returning v.value #>> '{}'")
# RING-AT-TAKEOVER: the swap of a head (the newest that swapped), the roles whose ECS task took its bundle over since
# ({state: reloaded}: by exec in place or by the successor that adopted the role; what deploy.sh's code_live asks of both)
# and whether the swap went back (its pointer emptied by anything but the handover: a red canary, a revert, a failover)
TAKEOVER = (
    "with s as (select payload->>'digest' as digest, occurred_at from log.event where type = 'platform.deploy.image_swap' "
    "and tenant_id is null and occurred_at > now() - interval '2 days' and payload->>'swapped' = 'true' "
    "and payload->>'head' = %(head)s order by occurred_at desc limit 1) "
    "select s.digest, coalesce((select string_agg(distinct e.payload->>'role', ' ' order by e.payload->>'role') "
    "from log.event e where e.type = 'platform.deploy.image_reload' and e.tenant_id is null "
    "and e.occurred_at >= s.occurred_at and e.payload->>'state' = 'reloaded' and e.payload->>'digest' = s.digest), ''), "
    "exists (select 1 from log.event e where e.type = 'platform.deploy.image_retired' and e.tenant_id is null "
    "and e.occurred_at >= s.occurred_at and e.payload->>'digest' = s.digest and e.payload->>'by' <> 'handover') from s")
# SLOW-PATH-NO-ROLLOUT-WAIT: the stacks whose rollout is seen since a time: its operation ended, as the port recorded
# CloudFormation's event (http_port.stack_state), or a task ECS started for it is up (__main__.task_up); the time is the
# build host's, so STACK_SKEW_S of clock difference is allowed for
# RING-AT-STACK-END: with the EventBridge rule in place (the bootstrap's StackStateRule, applied 11/11: an end of a stack
# was recorded in the last 30 days) a rollout is seen at its stack's end only. Rung at the task's up, the verifying build
# came before the stack's end and waited for it in its own seconds (wait:service 41 to 92 s, wait:runner 19 to 75 s); a
# task up still counts where no stack's end was ever recorded (no rule), and last-build.rolling.until is the safety of both
STACKS_ENDED = ("select distinct payload->>'stack' from log.event where tenant_id is null "
                "and occurred_at >= to_timestamp(%(since)s::float8) and ((type = 'platform.deploy.ended' "
                "and payload->>'source' = 'cloudformation') or (type = 'platform.deploy.task_up' and not exists ("
                "select 1 from log.event r where r.tenant_id is null and r.type = 'platform.deploy.ended' "
                "and r.payload->>'source' = 'cloudformation' and r.occurred_at > clock_timestamp() - interval '30 days')))")
STACK_SKEW_S = 30
# DIGEST-FROM-GATE-JOB (revisão da arquitetura, achado 35): the result of the gate's own artifact job of a head (the delivery
# makes it as check:<pr>:<head>:artifact:lambda[:round...], in the configuration's tenant; only its run writes its result).
# The manifest in the store is no proof: the runner's role writes artifacts/lambda/*, and every check of any PR runs there
GATE_DIGESTS = ("select j.result::text from work.job j join work.tenant t on t.id = j.tenant_id where t.name = %(tenant)s "
                "and j.idempotency_key like %(key)s and j.state = 'succeeded' order by j.id desc limit 1")
# VERIFY-AT-UP: the tasks that said they are up since a time, with the image each runs: a stack's rollout is seen when a task
# of its stack is up on the image the build deployed (last-build.rolling.stacks[name].image), rule or no rule. The build so
# rung settles the stack without waiting for its end (deploy.sh): the end, what CloudFormation waits after ECS (the old
# task's exit, Fargate's deprovision, 53 to 93 s more), is verified by the build after it
TASKS_UP = ("select payload->>'stack', payload->>'image' from log.event where tenant_id is null "
            "and type = 'platform.deploy.task_up' and occurred_at >= to_timestamp(%(since)s::float8)")


def mode_changes(last):
    """MODE-CHANGE-ALERT: what a build changed of how production runs, by a guard or a rollback, in a line each."""
    changes = []
    failed = last.get('ack_failed') if isinstance(last.get('ack_failed'), dict) else {}
    if failed.get('sha') and failed.get('sha') == last.get('base_head'):
        path = (last.get('ack') or {}).get('path') if isinstance(last.get('ack'), dict) else None
        changes.append(f'the ACK smoke was red: the ACK is on the {path or "unknown"} path, not sqs')
    back = [each for each in last.get('rolled_back') or [] if isinstance(each, str)]
    if back:
        changes.append(f"a red smoke rolled back {', '.join(back)}")
    return changes


def settled_up(last):
    """VERIFY-AT-UP: {tower-app-<name>: seconds} of the stacks a build settled at their new task's up (last-build.rolling
    with settling: true, each stack's `up`), or {}."""
    roll = last.get('rolling') if isinstance(last.get('rolling'), dict) else {}
    if not roll.get('settling') or not isinstance(roll.get('stacks'), dict):
        return {}
    return {f'tower-app-{name}': each['up'] for name, each in roll['stacks'].items()
            if isinstance(each, dict) and isinstance(each.get('up'), (int, float)) and not isinstance(each.get('up'), bool)}


# SLOW-PATH-NO-ROLLOUT-WAIT: the only bundles whose migrations a build may ask for: the code bundle named by its sha256
MIGRATE_KEY = re.compile(r'artifacts/lambda/tower-code/([0-9a-f]{64})\.zip')
# FAST-PATH-RELOAD: the newest build CodeBuild said started (http_port.build_state) in the last half hour, and its age
STARTED = ("select payload->>'build', extract(epoch from clock_timestamp() - occurred_at)::float8 from log.event "
           "where type = 'platform.deploy.started' and tenant_id is null and occurred_at > now() - interval '30 minutes' "
           "order by occurred_at desc limit 1")
ASK_WINDOW_S = 120.0  # how long after its start a build may still name its reload: the classification is its first seconds
ASK_LOOK_S = 2.0  # the safety look meanwhile (a build's record wakes nothing: Parameter Store has no notification here)
ASK_STEPS = ('', 'classify', 'code-live', 'reload')  # the build's steps before and while it names its reload
LIVE_SEEN = ("select distinct payload->>'role' from log.event where type = 'platform.deploy.image_live' and tenant_id is null "
             "and payload->>'digest' = %(digest)s and occurred_at >= to_timestamp(%(since)s::float8)")
# PROMOTED-RUNNER-WAITS-ALIVE: the roles whose promoted process of a bundle beats live (work.standby_beat.live_at within
# deploy.live_stale_s: what the ECS tasks' watchdog reads): it holds the role though it has taken no work yet
LIVE_BEATING = ("select distinct role from work.standby_beat where digest = %(digest)s "
                "and live_at > clock_timestamp() - make_interval(secs => %(stale_s)s::float8)")
# IN-TASK-STANDBY: the roles with a fresh beat of a bundle (work.standby_beat, the landing's own evidence: port.LANDED_SWAP)
BEATING = ("select coalesce(array_agg(distinct role), '{}')::text from work.standby_beat where digest = %(digest)s "
           "and beat_at > clock_timestamp() - make_interval(secs => %(fresh_s)s::float8)")
CANARY_LOOK_S = 3600  # DEPLOY-CANARY: how long after a swap the look still asks for its canary's verdict
# RELOAD-WITHOUT-STANDBY: the order to load a landed bundle in place, one at a time: recorded unless an order is not settled
# (younger than ORDER_SETTLE_S with neither done nor a failed reload of its digest since: busy, its head) or a reload onto
# this digest failed in 7 days (bad); it wakes the tasks (live_image.WOKEN). Answers (made, busy, bad)
ORDER = ("with busy as (select o.payload->>'head' as head from log.event o "
         f"where o.type = '{live_image.RELOAD}' and o.tenant_id is null and o.payload->>'state' = 'ordered' "
         "and o.occurred_at > clock_timestamp() - make_interval(secs => %(settle_s)s::float8) and not exists ("
         f"select 1 from log.event e where e.type = '{live_image.RELOAD}' and e.tenant_id is null "
         "and e.occurred_at >= o.occurred_at and e.payload->>'digest' = o.payload->>'digest' "
         "and e.payload->>'state' in ('done', 'failed')) order by o.occurred_at desc limit 1), "
         f"bad as (select 1 from log.event f where f.type = '{live_image.RELOAD}' and f.tenant_id is null "
         "and f.occurred_at > now() - interval '7 days' and f.payload->>'state' = 'failed' "
         "and f.payload->>'digest' = %(digest)s limit 1), "
         "said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
         f"select %(id)s, null, '{live_image.RELOAD}', clock_timestamp(), 'autodeploy', 'deploy/image', %(payload)s::jsonb || "
         "jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3), "
         "'landed_s', round((extract(epoch from clock_timestamp()) - %(landed_at)s::float8)::numeric, 3)) "
         "where not exists (select 1 from busy) and not exists (select 1 from bad) and not exists (select 1 from log.event "
         f"where event_id = %(id)s and type = '{live_image.RELOAD}' and occurred_at > now() - interval '2 days') returning type), "
         f"woke as ({live_image.WOKEN}) "
         "select (select count(*) from said), (select head from busy), exists (select 1 from bad), (select count(*) from woke)")
# RELOAD-WITHOUT-STANDBY: the order's end, once both roles' reloads are proven and no reload onto its digest failed:
# {state: done, seconds: the order to now}, and with it deploy.live_code = '<sha256>@<merge>' when the order's head is the
# base's newest (%(newest)s: LIVE_CODE_WRITE's rule; a row written after the order is left alone). Answers the datum written
ORDER_DONE = (
    f"with o as (select payload, occurred_at from log.event where event_id = %(order)s and type = '{live_image.RELOAD}' "
    "and occurred_at > now() - interval '1 hour' and (select count(distinct e.payload->>'role') from log.event e "
    f"where e.type = '{live_image.RELOAD}' and e.tenant_id is null and e.occurred_at > now() - interval '1 hour' "
    "and e.payload->>'order' = %(head)s and e.payload->>'state' = 'proven') = %(roles)s "
    f"and not exists (select 1 from log.event f where f.type = '{live_image.RELOAD}' and f.tenant_id is null "
    "and f.occurred_at > now() - interval '7 days' and f.payload->>'state' = 'failed' "
    "and f.payload->>'digest' = %(digest)s)), "
    "w as (insert into work.config_value as v (tenant_id, key, value, actor, reason) "
    "select t.id, 'deploy.live_code', to_jsonb(%(digest)s::text || '@' || %(head)s::text), 'autodeploy', "
    "'RELOAD-WITHOUT-STANDBY: the code both ECS tasks loaded in place and proved' from o, work.tenant t "
    "where t.name = %(tenant)s and %(newest)s::boolean "
    "on conflict (tenant_id, key) do update set value = excluded.value, version = v.version + 1, actor = excluded.actor, "
    "reason = excluded.reason, updated_at = clock_timestamp() "
    "where v.value is distinct from excluded.value and v.updated_at < (select occurred_at from o) "
    "returning v.value #>> '{}' as value), "
    "said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
    f"select %(id)s, null, '{live_image.RELOAD}', clock_timestamp(), 'autodeploy', 'deploy/image', %(payload)s::jsonb || "
    "jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3), "
    "'seconds', round(extract(epoch from clock_timestamp() - o.occurred_at)::numeric, 3), "
    "'live_code', (select value from w)) from o "
    f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{live_image.RELOAD}' "
    "and occurred_at > now() - interval '2 days') returning type), "
    f"woke as ({live_image.WOKEN}) select (select value from w), (select count(*) from said), (select count(*) from woke)")


def month_start(now):
    moment = time.gmtime(now)
    return calendar.timegm((moment.tm_year, moment.tm_mon, 1, 0, 0, 0))


def slow_path(path):
    """True when a change to this path can need the slow deploy (a stack, the image or the deployer)."""
    path = path.strip().lstrip('./')
    return path.startswith(SLOW_PATHS) and path not in NOT_SLOW and not path.startswith(NOT_SLOW_DIRS)


def coerce(name, value):
    """The value if it has the registry type of the key, else raises ValueError."""
    want = type(DEFAULTS[name])
    if want is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    floor = 0 if name in ZERO_OK else None
    if type(value) is not want or (want in (int, float) and value <= 0 and not (floor == 0 and value == 0)):
        raise ValueError(f'deploy.{name} wants {want.__name__}{" > 0" if want in (int, float) else ""}')
    return value


class AutoDeploy:
    def __init__(self, scope, ssm, invoke, clock=time.time, doorbell='tower-deploy-doorbell', check_every_s=30,
                 running_retry_s=60, idle_safety_s=300, fast=None, config=None):
        self.scope, self.ssm, self.invoke, self.clock = scope, ssm, invoke, clock
        self.doorbell, self.check_every_s, self.running_retry_s = doorbell, check_every_s, running_retry_s
        self.overrides, self.config_since = {}, None
        self.config = config  # DEP9: config_data.Config (work.config_value); its deploy.* values win over the git overrides
        self.publish = None  # MODE-CHANGE-ALERT: publish(said, subject=) to the platform's topic (canary.alert); None: the event only
        self.deployed = None  # a head seen deployed: no SSM read while the newest push is that head
        self.next_look = self.running_until = self.running_since = 0.0
        self.said = (None, 0.0)
        self.view = None  # {'head', 'pending'} of the look being decided, for the observation
        self.published = None  # the key of the last observation written (DEP3)
        # LOOK-READS-WHAT-IS-NEW: the rows of the log each 7-day read has, by read ('pushes:<branch>', 'landings'), and
        # the lock of the two threads that may read (the look, and the standby's read ahead of its takeover)
        self.rows_read, self.reading = {}, threading.Lock()
        self.landed = {}  # merge sha -> its platform.deploy.landed payload (functions, paths, pr_head, base_before, manifest_key)
        self.landed_at = {}  # IMAGE-SWAP-TIGHTEN: merge sha -> its landed event's occurred_at (epoch s)
        self.touched = {}  # head -> the paths its push changed (None: the push did not say), from the last pushes() read
        self.lost_events = []  # the platform.deploy.lost events of the ledger (DEP-WATCHDOG), oldest first
        self.commits = {}  # head -> the commit ids its push listed, newest first (the gate's manifest is named by the PR head)
        self.fast, self.fast_done, self.fast_log = fast, set(), []  # DEP8: the pointer swap, the heads tried, the swaps shown
        self.fast_seeded = False  # FAST-DURABLE: fast_log not yet read back from the log
        self.in_flight, self.idle_safety_s = False, idle_safety_s
        self.due_in = None
        self.cycles, self.alarmed = [], set()  # the month's cycle events (newest last) and the months with an alarm (DEP7)
        # IMAGE-PREWARM-C: the tenant of the pointers (LANDING-PREWARM-GONE: the landings considered for a swap and the
        # standbys' ECS client left with the prewarm, D-316)
        self.tenant = config_data.TENANT
        self.canaries, self.alert = {}, canary.alert  # DEPLOY-CANARY: swap key -> its canary's red line (None: green); the publisher
        # SLOW-PATH-NO-ROLLOUT-WAIT: the store of the code bundles (None: no bucket), the asks (key, sha256) already tried,
        # and whether a build is in progress (it may ask at any step: the safety look stays short meanwhile)
        self.bundles, self.migrated, self.building = None, set(), False
        # RELOAD-WITHOUT-STANDBY: the head whose order to load its bundle in place this look follows; the landing whose
        # order waits for the one in flight to settle (head, digest, key, pr_head); the roles whose canary is settled
        self.reload, self.judged = None, set()
        # FAST-PATH-RELOAD: the last-build this look read, the (head, sha256) a build asked to reload already ordered here,
        # and whether a build that just started may still ask (the safety look is short meanwhile)
        self.seen_build, self.asked, self.asking = {}, set(), False
        self.queue = None  # QUEUE-RELOAD: queue_deploy.QueueReload, the merge queue's prepare and landed (None: off)

    # --- the decision -----------------------------------------------------------------------------------------------
    def step(self, force=False):
        """One look; an event (force) looks at once, otherwise at most every check_every_s (the safety look). Answers
        (action, reason) or None; never raises."""
        now = self.clock()
        if now < self.next_look and not force:
            return None
        self.next_look = now + self.check_every_s
        try:
            return self.decide(now)
        except Exception:  # noqa: BLE001 - a failed look is a line in the log and the next look
            LOG.exception('autodeploy: look failed')
            return None

    def safety_s(self):
        """The longest the loop waits without an event: short while a ring is in flight (the build's end has no push path
        yet, so it is detected here), long when idle (a lost notification only)."""
        longest = self.check_every_s if self.in_flight or self.building else self.idle_safety_s
        if self.asking:  # FAST-PATH-RELOAD: a build that just started may name its reload at any second
            longest = min(longest, ASK_LOOK_S)
        # DEBOUNCE-WAKE: the debounce's end is no event, so a look skipped for it used to come back only at the idle safety
        # (300 s): live 11/11 the build of a landing started 5.6 min after it (#496, #498). The wait is what is left of it.
        return longest if self.due_in is None else min(longest, max(self.due_in, 0) + 0.5)

    def say(self, action, reason, now, **fields):
        line = f'autodeploy: {action} ({reason})' + ''.join(f' {key}={value}' for key, value in fields.items())
        last, at = self.said
        if line != last or now - at >= 600:  # one line per decision; the same skip repeats only every 10 minutes
            LOG.info(line)
            self.said = (line, now)
        return action, reason

    def fast_away(self, now):
        """FAST-SEEN-ACROSS-TASKS: whether a swap this process left to another task (skipped: AWAY) is still not in its
        list, within AWAY_S of the skip: past that the other task never recorded it, and the slow path is the net."""
        return any(each.get('skipped') == AWAY and now - (each.get('at') or 0) < AWAY_S for each in self.fast_log)

    def settings(self):
        values = {**DEFAULTS, **{name: value for name, (_, value) in self.overrides.items()}}
        if self.config is not None:  # a row of the table (a PUT /v1/config) is the newest word; no row, the git override or the default
            values.update({name: value for name, value in self.config.stored('deploy').items() if name in DEFAULTS})
        return values

    def decide(self, now):
        with self.scope() as db:
            if not self.fast_seeded or self.fast_away(now):  # FAST-DURABLE: once per process, before the first observation
                # FAST-SEEN-ACROSS-TASKS: and again while a skip `another task is swapping this function` is not answered:
                # the swap that task recorded is in the log, never in this process's list (live 12/11 03:59 UTC: the
                # status kept tower-port-api at ok null for the head and the slow path applied the port stack, 43 s).
                # The log's swaps, and of this process's own lines those the log has no swap for (function and head)
                said = [{**json.loads(payload), 'at': int(at)} for payload, at in
                        reversed(db.rows(FAST_SEED, {'limit': FAST_KEEP}))]
                told = {(each.get('sha'), each.get('function')) for each in said}
                mine = [each for each in self.fast_log if (each.get('sha'), each.get('function')) not in told]
                self.fast_log = sorted(said + mine, key=lambda each: each.get('at') or 0)
                self.fast_seeded = True
            self.due_in = None  # DEBOUNCE-WAKE: set by a skip that ends on the clock (the debounce), for safety_s
            decision = self.decide_in(db, now)
            self.in_flight = bool(decision) and (decision[1] == 'started'
                                                 or decision[1].startswith(('running', 'rolling', 'reloading')))
            self.observe(db, decision, now)
            return decision

    def observe(self, db, decision, now):
        """DEP3: the deploy state the session cannot read (the port's Lambda has no route to Parameter Store) is written to
        the log as ONE platform.deploy.observed event when it changes (or at start, or each BEAT_S while a ring is in
        flight). The id is the sha, the build, its status and the ring/skip, so a repeat or a restarted task is the same
        event. tenant_id is null like the rung events: the deploy belongs to the installation, and the port serves the
        newest one to the installation and to every tenant. Never raises: the decision already stands."""
        try:
            sha, build = self.ssm(LAST_SHA), self.last_build()
            action, reason = decision or (None, None)
            flight = bool(reason) and (reason == 'started' or reason.startswith(('running', 'rolling')))
            kind = (reason or '').split(':')[0]  # 'daily cap', 'min interval', 'budget', ...: a change of it is news
            seen = self.view or {}
            cfg = self.settings()
            rings, settled = self.ledger(db, now)
            spent = self.spent(rings, settled, cfg['usd_per_min'], now)
            lost = self.lost_events[-1] if self.lost_events and now - self.lost_events[-1]['at'] < 86400 else None
            running = self.in_progress(build, now)
            beat = BEAT_S if flight else BEAT_PENDING_S if seen.get('pending') else 0
            key = (sha, build.get('build_id'), build.get('status'), action, kind, seen.get('head'), seen.get('pending'),
                   int(now // beat) if beat else 0, int(spent), len(self.cycles), len(self.fast_log),
                   sum(1 for each in self.fast_log if each.get('ok') is None))  # FAST-SEEN-ACROSS-TASKS: a skip answered is news
            key += ((running['step'],) if running else ()) + ((len(self.lost_events),) if lost else ())
            if key == self.published:
                return
            ident = f'{OBSERVED}:' + ':'.join(str(part) for part in key)
            payload = {'last_sha': sha, 'last_build': build or None, 'observed_at': int(now),
                       'cycle': self.cycles[-1] if self.cycles else None, 'cycles': [{**c, 'ack_smoke': {k: v for k, v in (c.get('ack_smoke') or {}).items() if k != 'fail_tail'} or None}
                                  for c in self.cycles[-20:]],
                       'ack_failures': [c for c in self.cycles if (c.get('ack_smoke') or {}).get('ok') is False][-5:],
                       'cost': {'month_usd': round(spent, 4), 'alarm_usd': cfg['alarm_usd'], 'monthly_usd': cfg['monthly_usd'],
                                'alarm': spent >= cfg['alarm_usd'], 'stopped': spent >= cfg['monthly_usd'],
                                'line': (f'COST ALARM: US${spent:.2f} this month of US${cfg["alarm_usd"]:.2f}, hard stop at '
                                         f'US${cfg["monthly_usd"]:.2f}' if spent >= cfg['alarm_usd'] else None)},
                       'ring': {'action': action, 'reason': reason, 'at': int(now)} if action else None,
                       'head': seen.get('head'), 'pending': seen.get('pending'), 'fast': self.fast_log[-FAST_KEEP:], 'in_progress': running, 'lost': lost,
                       **self.bisect_view(build or {}, seen.get('head'))}
            db.rows(OBSERVE, {'id': ident, 'payload': json.dumps(payload)})
            self.published = key
        except Exception:  # noqa: BLE001
            LOG.exception('autodeploy: could not publish the deploy observation')

    def decide_in(self, db, now):
        self.view = None
        if self.config is not None:
            self.config.refresh()  # DEP9: on the event that woke this look (config.changed wakes tower_deploy), never on a timer
        self.read_overrides(db, now)
        cfg = self.settings()
        self.migrate(db)  # SLOW-PATH-NO-ROLLOUT-WAIT: whatever the ring decides below
        self.build_reload(db)  # FAST-PATH-RELOAD: the reload a code-only merge's build asks for, ordered at once
        self.queue_look(db, cfg)  # QUEUE-RELOAD: the merge queue's prepare and landed, before the build is even rung
        # DEP8b: the fast path is independent of the slow one: every look (a push wakes it) evaluates the new head's fast targets
        # first, whatever deploy.auto, the doorbell, a build in flight or the debounce say; only the base branch's pushes count
        pushes = self.pushes(db, cfg['base_branch'], now)
        self.image(db, pushes, cfg)  # IMAGE-PREWARM-C: before the Lambda swap, which may take seconds
        self.swap(db, pushes)
        if not cfg['auto']:
            return self.say('skip', 'off: deploy.auto is false', now)
        if not self.doorbell:
            return self.say('skip', 'no doorbell configured', now)
        if now < self.running_until and (self.last_build().get('ended') or 0) >= self.running_since:
            self.running_until = 0.0  # the build the doorbell said was running has ended: the 409 hold is over at once
        if now < self.running_until:
            return self.say('skip', 'running: the doorbell answered 409', now)
        if not pushes:
            return self.say('skip', 'no push to the base seen in 7 days', now)
        head, pushed_at = pushes[-1]
        self.view = {'head': head, 'pending': self.pending(pushes, self.deployed)}
        if head == self.deployed:
            return self.say('skip', 'deployed', now, head=head[:12])
        # RING-AT-LANDING: a head whose landing this look read (platform.deploy.landed: the delivery that merged it says
        # what it landed, and wakes this look) is rung without the debounce: what a build must wait for is said by
        # events below (a rollout, a reload in place, the tasks taking the code over), never by a count of seconds. The
        # debounce stays for a push whose landing is not known (one that was no delivery, or whose landing has not
        # arrived yet: its event wakes the look again): the safety of an event that never comes, not a wait
        if now - pushed_at < cfg['debounce_s'] and head not in self.landed_at:
            self.due_in = cfg['debounce_s'] - (now - pushed_at)  # DEBOUNCE-WAKE: the look comes back when the debounce ends
            return self.say('skip', f'debounce: the newest push is {now - pushed_at:.0f}s old of {cfg["debounce_s"]}s',
                            now, head=head[:12])
        last_sha, last = self.ssm(LAST_SHA), self.last_build()
        status, started = last.get('status'), last.get('started') or 0
        self.view['pending'] = self.pending(pushes, last_sha)
        # DEP-EVENTS: a head is deployed only when the last build left nothing dirty (a failed or incomplete build, or stacks whose
        # recorded hash is not the head's): last-sha equal to the head says nothing about a stack whose last apply failed
        dirty = status in ('failed', 'incomplete') or bool(last.get('dirty'))
        if (last_sha == head and not dirty) or (last.get('base_head') == head and status in OK and not dirty):
            self.deployed = head
            self.view['pending'] = 0
            return self.say('skip', 'deployed', now, head=head[:12])
        self.settle(db, last, cfg)
        # SLOW-PATH-NO-ROLLOUT-WAIT: the last build's stacks are still rolling out; RELOAD-WITHOUT-STANDBY: or the ECS
        # tasks are loading this head's bundle in place: the build rung when they are done deploys no image and no stack
        held = self.rolling(db, last, now) or self.reloading(head, now) or self.taking_over(db, head, now)
        if held:
            return self.say('skip', held, now, head=head[:12], build=last.get('build_id'))
        bisect, bisecting, leftover = self.bisection(last)
        if status in OK and started >= pushed_at and not bisecting and not leftover and not dirty:
            return self.say('skip', 'covered: a build that ended well started after the push', now, head=head[:12])
        if not bisecting and not dirty and status != 'rolling' and not self.slow_needed(pushes, last_sha):
            self.record(db, PENDING, f'{PENDING}:{head}', {'head': head, 'since': last_sha, 'route': 'fast-or-none'})
            return self.say('skip', 'fast only: no slow target since the deployed sha, pending for the fast path (DEP8)',
                            now, head=head[:12])
        if status == 'failed' and last.get('base_head') == head and not bisecting:
            # no clock here: this head was tried and failed; a new push (another head), a published fix or an explicit
            # platform.deploy.ended / push event wakes the look, and only a different head is rung
            return self.say('skip', 'failed: this head was tried; waits for a new push, never for time', now, head=head[:12],
                            build=last.get('build_id'))
        if not db.rows('select pg_try_advisory_lock(%(key)s)', {'key': LOCK_KEY})[0][0]:
            return self.say('skip', 'another service task is deciding', now)
        try:
            return self.ring(db, cfg, head, pushed_at, last, now)
        finally:
            db.rows('select pg_advisory_unlock(%(key)s)', {'key': LOCK_KEY})

    @staticmethod
    def bisection(last):
        """(state, bisecting, leftover) of last-build. bisecting: a half of a failed batch is still to deploy. leftover: a
        state that must be cleared by a build (an older epoch, too many builds, or a culprit, which never blocks), so the head
        is rung even when the last build 'covers' the push: the next build deploys the head and clears it."""
        bisect = last.get('bisect') if isinstance(last.get('bisect'), dict) else {}
        if not bisect:
            return {}, False, False
        if last.get('bisect_epoch') != BISECT_EPOCH or int(bisect.get('builds') or 0) >= BISECT_MAX_BUILDS or bisect.get('culprit'):
            return bisect, False, True
        return bisect, bool(bisect.get('bad')), False

    @staticmethod
    def bisect_view(last, head=None):
        """The status's `bisect` and `culprit`, each with its reason: what is steering the next build, or why a leftover is ignored."""
        bisect, bisecting, leftover = AutoDeploy.bisection(last)
        culprit = bisect.get('culprit')
        note = last.get('bisect_note') or None
        if not bisect:
            return {'bisect': None, 'culprit': None, 'note': note}
        if bisecting:
            reason = bisect.get('reason') or 'a failed batch is being bisected'
            fresh = head and head != bisect.get('head_tried_sha') and head != bisect.get('bad')
            nxt = ('the current head first: a commit landed since the last tried head (it may be the fix); red then bisects (last-sha, head]'
                   if fresh else 'the midpoint of (good, bad], unless a new commit lands (then that head first)')
            return {'bisect': {'state': 'bisecting', 'good': bisect.get('good'), 'bad': bisect.get('bad'), 'n': bisect.get('n'),
                               'builds': bisect.get('builds'), 'next': nxt, 'reason': reason}, 'culprit': None, 'note': note}
        why = ('a culprit does not block: the next build deploys the head' if culprit else
               f'ignored: epoch {last.get("bisect_epoch")} is not {BISECT_EPOCH}' if last.get('bisect_epoch') != BISECT_EPOCH else
               f'ignored: {bisect.get("builds")} builds of {BISECT_MAX_BUILDS}')
        return {'bisect': {'state': 'leftover', 'good': bisect.get('good'), 'bad': bisect.get('bad'), 'reason': why},
                'culprit': {'sha': culprit, 'reason': bisect.get('reason'), 'blocks': False} if culprit else None, 'note': note}

    def settle(self, db, last, cfg=None):
        """The seconds of the build the last ring started, once last-build reports it ended: one settled event each, and
        one platform.deploy.cycle with what the cycle cost (CodeBuild minutes x usd_per_min), its targets and verdict."""
        rings, settled = self.ledger(db, self.clock())
        if rings and last.get('build_id') == rings[-1]['build'] and last.get('ended') and rings[-1]['build'] not in settled:
            seconds = max(0, last['ended'] - (last.get('started') or last['ended']))
            self.record(db, SETTLED, f'{SETTLED}:{last["build_id"]}', {'build': last['build_id'], 'seconds': seconds,
                                                                      'status': last.get('status')})
            # the explicit 'deploy ended' event: log.event notifies (migration 0009), so every waiting side looks at once
            self.record(db, ENDED, f'{ENDED}:{last["build_id"]}', {'build': last['build_id'], 'status': last.get('status'),
                                                                  'sha': last.get('base_head'), 'dirty': last.get('dirty') or []})
            rate = (cfg or self.settings())['usd_per_min']
            self.record(db, CYCLE, f'{CYCLE}:{last["build_id"]}', {
                'build': last['build_id'], 'seconds': seconds, 'usd': round(seconds / 60 * rate, 6),
                'status': last.get('status'), 'targets': last.get('targets'), 'sha': last.get('base_head'),
                'rolled_back': last.get('rolled_back') or [], 'bisect': last.get('bisect'),
                'ack': last.get('ack'), 'ack_smoke': last.get('ack_smoke'),
                # VERIFY-AT-UP: the build's own start and end (the event is written when a look sees the end, up to minutes later)
                'started': last.get('started'), 'ended': last.get('ended'),
                # SLOW-PATH-NO-ROLLOUT-WAIT: of the build that verified a rollout: the seconds the stacks took to be stable
                # after the build that started them ended (on no build's clock), and each stack's rollout
                **({'rollout_wait_s': last['rollout_wait_s'], 'rollout': last.get('rollout')}
                   if last.get('rollout_wait_s') is not None else {}),
                # VERIFY-AT-UP: of the build that settled stacks at their new task's up: each one's seconds from the start
                # of its update to that up (its stack's end is the next build's to verify)
                **({'settled': settled_up(last)} if settled_up(last) else {})})
            self.mode_changed(db, last)
            culprit = (last.get('bisect') or {}).get('culprit') if isinstance(last.get('bisect'), dict) else None
            if culprit:
                self.record(db, 'platform.deploy.culprit', f'platform.deploy.culprit:{culprit}', {
                    'sha': culprit, 'build': last['build_id'], 'tail': str(last.get('tail') or '')[-1500:]})

    def mode_changed(self, db, last):
        """MODE-CHANGE-ALERT (revisão da arquitetura, achado 6: on 10/11 production ran ~24 h on the ACK's Lambda path after a
        guard put it back, and nothing said so): a build that changed how production runs by a guard or a rollback is one
        platform.deploy.mode_changed event and one alert on the platform's topic, once per build: the ACK's smoke red and
        the port stack back on another path (last-build.ack_failed of this build's head), or a red smoke that rolled stacks
        back (last-build.rolled_back). Never raises: the build's record says it either way."""
        changes = mode_changes(last)
        if not changes:
            return
        said = {'build': last.get('build_id'), 'sha': last.get('base_head'), 'changes': changes}
        try:
            self.record(db, MODE, f"{MODE}:{last.get('build_id')}", said)
            if self.publish is not None:
                self.publish(said, subject=f"tower deploy: {'; '.join(changes)}"[:100])
        except Exception:  # noqa: BLE001
            LOG.exception('autodeploy: the mode change of %s was not said', last.get('build_id'))

    def rolling(self, db, last, now):
        """SLOW-PATH-NO-ROLLOUT-WAIT: why the ring waits while the stacks the last build started are rolling out, or None.
        deploy.sh no longer waits for an ECS rollout: it starts the stack's update and ends `rolling`, last-sha untouched,
        with last-build.rolling = {head, until, stacks: {name: {t0}}}. The build that verifies them (the smoke, the
        rollback, last-sha) is rung when the rollout of every one of them is seen, by an event that wakes this look:
        the stack ended (the CloudFormation Stack Status Change the port records as platform.deploy.ended {stack,
        status, source: cloudformation}, with the EventBridge rule: it is also the end of a rollout that fails or starts
        no task; RING-AT-STACK-END: the only sign once the rule is there, so the build finds the stacks complete), or,
        where no stack's end was ever recorded, the stack's new task is up (platform.deploy.task_up, written by the
        task itself: the build then waits in its own seconds for what is left of the rollout, the old task's drain).
        `until` is the safety of a rollout that says neither: the usual seconds of a rollout plus a margin, set by the
        build; from it the build is rung anyway and waits for what is left. Nothing else is rung meanwhile
        (CloudFormation takes one operation per stack): that build takes the current head.
        VERIFY-AT-UP: and a stack whose build named the image it deployed is seen when a task of it says it is up on that
        image (TASKS_UP), with the rule too: that build settles it (deploy.sh), it does not wait for the stack's end."""
        roll = last.get('rolling') if isinstance(last.get('rolling'), dict) else {}
        stacks = roll.get('stacks') if isinstance(roll.get('stacks'), dict) else {}
        if last.get('status') != 'rolling' or not stacks:
            return None
        since = min(float((each or {}).get('t0') or 0) for each in stacks.values()) - STACK_SKEW_S
        seen = {row[0] for row in db.rows(STACKS_ENDED, {'since': since})}
        images = {f'tower-app-{name}': (each or {}).get('image') for name, each in stacks.items()}
        seen |= {stack for stack, image in db.rows(TASKS_UP, {'since': since}) if image and images.get(stack) == image}
        left = sorted(name for name in stacks if f'tower-app-{name}' not in seen)
        until = float(roll.get('until') or 0)
        if not left or now >= until:
            return None
        return f"rolling: {', '.join(left)} still rolling out; the next build verifies at their end (the safety rings at {until:.0f})"

    def migrate(self, db):
        """SLOW-PATH-NO-ROLLOUT-WAIT: the migrations of the head a deploy build is about to roll out, applied here, by the
        live service, before any task of that head starts: the service applied them at its boot and the runner never does,
        which made the runner's rollout wait for the service's. deploy.sh publishes the head's code bundle and names it in
        last-build.migrate {key, sha256}; only the deployer writes last-build, and the bundle is checked against the sha256
        it names. Once per bundle and never raises: with no evidence (GET /v1/health?migration) the build keeps the old
        order, and the new service still applies what is missing at its boot. Migrations are additive: this code and the
        tasks of the last deploy run on the new schema until the new ones are up (deploy.sh never asks for a file marked
        `-- deploy: not-additive`)."""
        try:
            build = self.last_build()
            self.seen_build = build if isinstance(build, dict) else {}
            self.building = build.get('status') == 'in_progress'
            ask = build.get('migrate') if isinstance(build.get('migrate'), dict) else {}
            key, sha = str(ask.get('key') or ''), str(ask.get('sha256') or '')
            if not key or self.bundles is None or (key, sha) in self.migrated:
                return
            self.migrated.add((key, sha))
            named = MIGRATE_KEY.fullmatch(key)
            if not named or named.group(1) != sha:
                raise ValueError(f'{key} is not the code bundle {sha}')
            names = migrations.migrate_bundle(db, code_bundle.fetch(self.bundles, {}, key, sha), PRODUCER)
            self.say('migrate', f"applied {', '.join(names) or 'nothing: the database already had them'}", self.clock(),
                     bundle=sha[:12], build=build.get('build_id'))
            self.said_migrated(db, sha, build, 'applied', applied=list(names), newest=max(names) if names else None)
        except Exception as error:  # noqa: BLE001 - the build then keeps the old order: the new service migrates at its boot
            LOG.exception('autodeploy: the migrations a build asked for were not applied')
            if sha:
                self.said_migrated(db, sha, build, 'failed', why=f'{type(error).__name__}: {error}'[:300])

    def said_migrated(self, db, sha, build, state, **fields):
        """MIGRATED-EVENT: platform.deploy.migrated {bundle, build, state, ...}: the end of migrate(), which the build that
        asked waits for (deploy.sh migrate_wait, on GET /v1/deploy/status's long poll). Never raises: without it the build
        waits its own bound and keeps the old order."""
        build = build if isinstance(build, dict) else {}
        try:
            self.record(db, MIGRATED, f'{MIGRATED}:{sha}:{build.get("build_id")}:{self.clock():.3f}',
                        {'bundle': sha, 'build': build.get('build_id'), 'state': state, **fields})
        except Exception:  # noqa: BLE001 - the wait is bounded; the record is its cue, not its verdict
            LOG.exception('autodeploy: the migrations\' end was not recorded')

    # --- IMAGE-PREWARM-C: the image-only swap on landing --------------------------------------------------------------------
    def image(self, db, pushes, cfg):
        """The orders followed (reloads), then the pointer's way back off the clock (settle_image). Never raises: the slow
        path is the net."""
        heads = [each[0] for each in pushes]
        try:
            self.reloads(db, heads)  # RELOAD-WITHOUT-STANDBY: the order of a landing with no standby pair, followed
            self.settle_image(db, heads)
            self.live_code(db, heads[-1] if heads else None)
        except Exception:  # noqa: BLE001
            LOG.exception('autodeploy: image swap failed')

    def live_code(self, db, head):
        """SLOW-PATH-NO-ROLLOUT-WAIT: the code of the swap of the base's newest head as a durable datum, deploy.live_code
        = '<bundle sha256>@<merge sha>', written here, by the live service's look the landing wakes, not in the swap's
        own statement: nothing is added to the swap's second. Never the swap of an older head: a task follows the datum
        when it is not the value its definition was deployed seeing, which is only right while the datum can change to
        newer code alone (a service that starts after a build deployed a newer head must not write the swap before it).
        The reload in place (IMAGE-SWAP-RELOAD) replaces only a process; a task ECS
        starts later (a crash, Spot, a rollout for another reason) boots the code of its task definition, and with no
        pointer left nothing made it load the swapped bundle, which is why every code-only landing was still followed by
        two ECS rollouts with LiveCode. With the datum that task boots the bundle (code_bundle.boot, unless its
        definition was deployed seeing this very value), and deploy.sh, which reads it in GET /v1/deploy/status, leaves
        the two stacks alone when the head's code is this bundle and both ECS tasks reloaded it."""
        found = db.rows(LIVE_CODE_WRITE, {'tenant': self.tenant, 'head': head}) if head else []
        if found:
            self.say('image', f'deploy.live_code -> {str(found[0][0])[:12]}: a task ECS starts later boots it', self.clock())

    # --- RELOAD-WITHOUT-STANDBY: the landing with no standby pair, loaded in place by the ECS tasks --------------------------
    def order(self, db, head, digest, key, pr_head, **more):
        """The order to load the landed bundle in place: platform.deploy.image_reload {state: ordered, digest, key, head,
        landed_s}, which the ECS runner obeys first and the ECS service once the runner is proven (live_image.Order). One
        order at a time: while another is not settled this one is not made (the queue and the build each say it: their
        orders never wait, LANDING-PREWARM-GONE: the landing's order that waited left with the prewarm); a bundle a
        reload failed on is never ordered again. FAST-PATH-RELOAD: more (roles, by, build) goes in the order: answers
        (made, busy, bad)."""
        made, busy, bad, _ = db.rows(ORDER, {
            'id': f'{live_image.RELOAD}:order:{head}', 'digest': digest, 'settle_s': live_image.ORDER_SETTLE_S,
            'landed_at': self.landed_at.get(head) or self.clock(), 'payload': json.dumps(
                {'state': 'ordered', 'digest': digest, 'key': key, 'head': head, 'pr_head': pr_head, 'order': head, **more})})[0]
        made, bad = bool(int(made)), bad in (True, 't')
        self.reload = head if made or busy == head else self.reload
        alone = live_image.order_roles(more) != live_image.ROLES
        self.say('image', f"ordered: the ECS tasks load {digest[:12]} in place, {'the service alone' if alone else 'the runner first'}"
                 if made else f'the order of {str(busy)[:12]} is not settled: this one is not made' if busy and busy != head else
                 f'not ordered: a reload onto {digest[:12]} failed' if bad else 'ordered already', self.clock(), head=head[:12])
        return made, busy, bad

    def queue_look(self, db, cfg):
        """QUEUE-RELOAD (tower_infra.queue_deploy): the merge queue's words, with deploy.queue_reload; a landing's order is
        the service's alone, by: queue, the order FAST-PATH-RELOAD makes for a build."""
        if self.queue is None or not cfg.get('queue_reload', True):
            return
        self.queue.config, self.queue.tenant = self.config, self.tenant  # QUEUE-SWAP: deploy.standby_fresh_s as it is now
        self.queue.look(db, lambda sha, digest, key: self.order(db, sha, digest, key, None, roles=['service'], by='queue'))
        try:  # QUEUE-SWAP: the heir took the role over: the merge's code is the datum a task ECS starts later boots
            head = self.queue.adopted(db)
            if head:
                self.live_code(db, head)
        except Exception:  # noqa: BLE001 - the build waits for the datum and takes the image without it
            LOG.exception('autodeploy: deploy.live_code of the queue swap was not written')

    def build_reload(self, db):
        """FAST-PATH-RELOAD (the module's docstring): the reload the deploy build in progress names in last-build.reload
        {key, sha256, head}, ordered for the service alone, once per (head, sha256) in this process (a process that starts
        mid-way, the reloaded one, finds the order made and follows it). The ask is the build's own: its head is the build's
        base_head and the key is the bundle of that sha256. An order that cannot be made is said {state: declined} with
        why, so the build goes on to the image at once. Also decides `asking` (the short safety look). Never raises."""
        try:
            build = self.seen_build or {}
            started = db.rows(STARTED, {})
            begun, age = (started[0][0], float(started[0][1])) if started and started[0][0] else (None, None)
            fresh = begun is not None and age < ASK_WINDOW_S
            unseen = fresh and begun != build.get('build_id')  # CodeBuild said it started, its record is not written yet
            self.building = self.building or unseen
            ask = build.get('reload') if build.get('status') == 'in_progress' and isinstance(build.get('reload'), dict) else None
            self.asking = bool(unseen or (fresh and begun == build.get('build_id') and build.get('status') == 'in_progress'
                                          and ask is None and str(build.get('step') or '') in ASK_STEPS))
            if ask is None:
                return
            key, sha, head = str(ask.get('key') or ''), str(ask.get('sha256') or ''), str(ask.get('head') or '')
            if (head, sha) in self.asked:
                return
            self.asked.add((head, sha))
            if self.queue is not None and self.queue.swapping(db, head, sha):
                # QUEUE-SWAP: the merge queue's swap already gave the service's pointer to this bundle's heir: no order
                # (it would reload the process the heir takes over from); the build waits for deploy.live_code
                self.say('image', f'reload not ordered: the queue swap of {head[:12]} is in charge', self.clock())
                return
            named = MIGRATE_KEY.fullmatch(key)
            if not named or named.group(1) != sha or not re.fullmatch(r'[0-9a-f]{40}', head) or head != build.get('base_head'):
                self.say('image', f'reload not ordered: {key} @ {head[:12]} is not the code bundle of the build\'s head',
                         self.clock(), build=build.get('build_id'))
                return
            made, busy, bad = self.order(db, head, sha, key, None, roles=['service'], by='build', build=build.get('build_id'))
            if not made and (bad or (busy and busy != head)):
                why = (f'a reload onto {sha[:12]} failed in the last 7 days' if bad else
                       f'the order of {str(busy)[:12]} is not settled')
                db.rows(live_image.ORDER_SAY, {
                    'id': f'{live_image.RELOAD}:service:{sha}:declined:{head}:build', 'producer': PRODUCER, 'role': 'service',
                    'payload': json.dumps({'role': 'service', 'digest': sha, 'state': 'declined', 'order': head, 'head': head,
                                           'by': 'autodeploy', 'why': why, 'build': build.get('build_id')})})
        except Exception:  # noqa: BLE001 - the build then deploys the image, as before
            LOG.exception('autodeploy: the reload a build asked for was not ordered')

    def reloads(self, db, heads):
        """The order this look follows (the one it made, or the one a service before it left for the newest head): its
        canaries' verdicts recorded and a red one published (canary.settle, as a swap's), and once both roles' reloads
        are proven its end: {state: done} and deploy.live_code (ORDER_DONE). No statement while no order is followed."""
        newest = heads[-1] if heads else None
        order = self.reload and live_image.ordered(db.rows(live_image.ORDER_OF, {'tenant': self.tenant, 'head': self.reload}))
        if not order:
            self.reload, self.judged = None, set()
        elif self.succeed(db, order) or live_image.said(order, None, 'done'):
            self.reload, self.judged = None, set()  # IN-TASK-STANDBY: the successors have it: the swap is in charge
        else:
            roles = live_image.order_roles(order)  # FAST-PATH-RELOAD: an order of the service alone
            for role in roles:
                if role not in self.judged and order['jobs'].get(role):
                    verdict = canary.settle(db, self.tenant, canary.order_key(order['head'], role), publish=self.alert)
                    if verdict is not None and verdict['ok'] is not None:
                        self.judged.add(role)
            proven = all(live_image.said(order, role, 'proven') for role in roles)
            if proven and not order['refused'] and not live_image.said(order, None, 'done'):
                found = db.rows(ORDER_DONE, {
                    'order': f"{live_image.RELOAD}:order:{order['head']}", 'id': f"{live_image.RELOAD}:done:{order['head']}",
                    'head': order['head'], 'digest': order['digest'], 'tenant': self.tenant, 'roles': len(roles),
                    # FAST-PATH-RELOAD: the build's own head is the newest it deploys (no landing names heads on GitHub);
                    # QUEUE-RELOAD: and so is the merge the queue's landing ordered (checked as main's head before the order)
                    'newest': order['head'] == newest or order.get('by') in ('build', 'queue'),
                    'payload': json.dumps({'state': 'done', 'digest': order['digest'], 'head': order['head'],
                                           'order': order['head']})})
                said = 'both ECS tasks run' if roles == live_image.ROLES else f"the ECS task of {' and '.join(roles)} runs"
                self.say('image', f"reloaded in place: {said} {order['digest'][:12]} and proved it"
                         + (f"; deploy.live_code -> {str(found[0][0])[:12]}" if found and found[0][0] else ''),
                         self.clock(), head=order['head'][:12])
            if proven or order['refused'] or order['age_s'] > live_image.ORDER_SETTLE_S:
                self.reload, self.judged = None, set()

    def succeed(self, db, order):
        """IN-TASK-STANDBY: the order of a landing that found no standby, obeyed by the successors the ECS tasks started
        for its bundle: once both roles have a fresh beat of it (deploy.standby_fresh_s, as the landing's own swap asks)
        both pointers are written, platform.deploy.image_swap {by: order, landed_s: the landing to the pointers} under an
        id of its own (the landing's event already said why it did not swap), and the order is said done: from here it
        is a swap like any other (its canary, the role adopted by the successors, deploy.live_code). Not with the datum
        off, past the order's limit, or once a task reloads by exec for it. Answers whether it swapped."""
        cfg = self.config
        if cfg is None or cfg.get(live_image.SUCCESSORS) <= 0 or not live_image.Order.open(order):
            return False
        digest, head = order['digest'], order['head']
        beating = db.rows(BEATING, {'digest': digest, 'fresh_s': cfg.get('deploy.standby_fresh_s')})
        if not beating or not all(role in str(beating[0][0]) for role in ROLES):
            return False
        found = db.rows(SWAP_WRITE, {
            'tenant': self.tenant, 'digest': digest, 'keys': ','.join(live_image.KEYS[role] for role in ROLES),
            'reason': f'IN-TASK-STANDBY: landed {head[:12]}, its successors beat', 'id': f'{SWAP}:{head}:order',
            'landed_at': self.landed_at.get(head) or self.clock() - order['age_s'] - float(order.get('landed_s') or 0), 'payload': json.dumps(
                {'digest': digest, 'key': order['key'], 'head': head, 'pr_head': order.get('pr_head'), 'by': 'order'})})
        if not found:
            return False
        db.rows(live_image.ORDER_SAY, {
            'id': f'{live_image.RELOAD}:done:{head}', 'producer': PRODUCER, 'role': 'service', 'payload': json.dumps(
                {'state': 'done', 'digest': digest, 'head': head, 'order': head, 'by': 'successors'})})
        self.say('image', f'both pointers -> {digest[:12]}: the successors the ECS tasks started for the order beat',
                 self.clock(), head=head[:12], landed_s=json.loads(found[0][0]).get('landed_s'))
        return True

    def reloading(self, head, now):
        """Why the ring of this head waits while the ECS tasks load its bundle in place (or its order waits for the one
        in flight), or None. The build is rung at the order's end, which wakes this look (proven and failed notify
        tower_deploy): both roles proven, it finds deploy.live_code and deploys no image and no stack; failed, it is the
        slow path, as before. Never longer than live_image.ORDER_LIMIT_S after the landing: the look comes back then."""
        landed = self.landed_at.get(head)
        if head != self.reload or landed is None:
            return None
        left = live_image.ORDER_LIMIT_S - (now - landed)
        if left <= 0:
            return None
        self.due_in = left if self.due_in is None else min(self.due_in, left)
        return (f'reloading: the ECS tasks are loading the code of {head[:12]} in place; the build is rung when both '
                f'are proven or one fails, in {left:.0f} s at most')

    def taking_over(self, db, head, now):
        """RING-AT-TAKEOVER: why the ring of a head that swapped waits while the ECS tasks take its code over, or None.
        The landing's swap is the standbys' or the successors'; the build skips the image and the rollouts only once
        the ECS task of both roles runs the bundle ({state: reloaded}, deploy.sh's code_live). Rung after the debounce
        alone, a build read one role only and deployed the slow way a head that was live already (live 11/11, #529: the
        runner still finished its runs). The roles' `reloaded` and their handover wake this look (tower_deploy). Not
        when the swap went back, nor longer than live_image.ORDER_LIMIT_S after the landing: then it is the slow
        path, as before. A look that never saw the landing waits for nothing."""
        landed = self.landed_at.get(head)
        left = None if landed is None else live_image.ORDER_LIMIT_S - (now - landed)
        if left is None or left <= 0:
            return None
        found = db.rows(TAKEOVER, {'head': head})
        if not found or not found[0][0] or found[0][2] in (True, 't'):
            return None
        took = str(found[0][1] or '').split()
        if all(role in took for role in ROLES):
            return None
        self.due_in = left if self.due_in is None else min(self.due_in, left)
        return (f"reloading: the ECS tasks are taking the swapped code of {head[:12]} over (so far: {' '.join(took) or 'none'}); "
                f'the build is rung when both have, in {left:.0f} s at most')

    def pointers(self, db):
        found = {}
        for role in ROLES:
            rows = db.rows(live_image.READ, {'tenant': self.tenant, 'key': live_image.KEYS[role]})
            found[role] = str(json.loads(rows[0][0]) or '').strip() if rows else ''
        return found

    def settle_image(self, db, heads):
        """The pointer's way back, off the swap's clock. Undone when a standby never said image_live within SWAP_LIMIT_S
        (the ECS tasks, not strict, work again under no pointer). Retired once a build that ended well deployed the swap's
        head or a later one: CloudFormation waited for the ECS services to be steady, the ECS tasks carry the bundle as
        LiveCode (deploy.sh) or their own image's code, and the pointers are emptied where they still name S: the strict
        standbys stop working (the runner's slots end after their runs, then the task exits) and
        the ECS tasks work under no pointer, as before any swap."""
        found = db.rows(NEWEST_SWAP)
        if not found:
            return
        swap, at = json.loads(found[0][0]), float(found[0][1])
        digest, head = swap.get('digest'), swap.get('head')
        pointers = self.pointers(db)
        keys = [live_image.KEYS[role] for role in ROLES if pointers[role] == digest]
        red = self.swap_canary(db, swap, at)  # DEPLOY-CANARY: also once no pointer names the digest: the verdict is recorded
        if not keys:
            return
        live = {row[0] for row in db.rows(LIVE_SEEN, {'digest': digest, 'since': at})}
        last = self.last_build()
        roles = set(swap['roles']) & set(ROLES) if isinstance(swap.get('roles'), list) else set()  # QUEUE-SWAP: its own
        missing = (roles or set(ROLES)) - live if self.clock() - at > SWAP_LIMIT_S else set()
        if missing and not red:
            # PROMOTED-RUNNER-WAITS-ALIVE: a role that beats live holds the swap though it took no work yet: an in-task
            # runner successor whose task's slots are all in runs of the process before it waits for a checkout (live
            # 11/11, #537: four long checks in flight; the swap was undone at 60 s and the engine went the slow way)
            stale = self.config.get('deploy.live_stale_s') if self.config is not None else config_data.SPEC['deploy.live_stale_s'][1]
            missing -= {row[0] for row in db.rows(LIVE_BEATING, {'digest': digest, 'stale_s': stale})}
        if red:  # DEPLOY-CANARY: the swap's code does not work end to end: both roles go back to the ECS tasks
            by, why = 'canary', red
        elif missing:
            by, why = 'revert', f"no image_live of the {' and '.join(sorted(missing))} standby in {SWAP_LIMIT_S} s"
        elif (last.get('status') in OK and last.get('ended') and not last.get('dirty') and head in heads
              and last.get('base_head') in heads and heads.index(last['base_head']) >= heads.index(head)):
            by, why = 'reconciled', f"build {last.get('build_id')} deployed {str(last['base_head'])[:12]}"
        else:
            return
        done = db.rows(live_image.EMPTY, live_image.empty(
            self.tenant, keys, digest, 'autodeploy', {'digest': digest, 'head': head, 'by': by, 'why': why},
            f'platform.deploy.image_retired:{digest}:{by}:{head}', f'IMAGE-PREWARM-C: {by}: {why}'))
        self.say('image', f'{by}: pointers of {digest[:12]} emptied ({why})' if done else f'{by}: the pointers had moved',
                 self.clock(), head=str(head)[:12])

    def swap_canary(self, db, swap, at):
        """DEPLOY-CANARY: the canary of the newest swap (tower_infra.canary), keyed by the version the swap gave the
        service's pointer. While that pointer still names the swap at that version and no canary exists, it is fired (the
        service that took the role fires it too, after its first work: the same key, one job); its verdict is recorded
        and a red one published, once. Answers the red verdict's line, else None. Never raises: the swap's own way back
        (revert, reconciled) goes on whatever happens here."""
        digest, version = swap.get('digest'), (swap.get('versions') or {}).get(live_image.KEYS['service'])
        if swap.get('by') == 'queue':  # QUEUE-SWAP: proven by its heir (live_image.RELOAD_OF), no runner takes a canary
            return None
        key = canary.swap_key(digest, version)
        if key in self.canaries:
            return self.canaries[key]  # a red one is answered until the pointers are emptied
        if version is None or self.clock() - at > CANARY_LOOK_S:
            return None
        try:
            found = db.rows(live_image.READ, {'tenant': self.tenant, 'key': live_image.KEYS['service']})
            pointed = bool(found) and json.loads(found[0][0]) == digest and int(found[0][1]) == int(version)
            said = canary.settle(db, self.tenant, key, {'digest': digest, 'head': swap.get('head'), 'by': 'swap'},
                                 fire=pointed, publish=self.alert)
        except Exception:  # noqa: BLE001
            LOG.exception('autodeploy: the canary of the swap to %s was not read', str(digest)[:12])
            return None
        if said is None or said['ok'] is None:
            return None
        self.canaries[key] = None if said['ok'] else said['line']
        if not said['ok']:  # the bundle is not loaded again: no reload onto it, no boot of it from deploy.live_code
            try:
                db.rows(live_image.RELOAD_SAY, {
                    'id': f'{live_image.RELOAD}:service:{digest}:failed:canary', 'producer': 'autodeploy', 'role': 'service',
                    'wrote_at': None, 'started_at': None, 'payload': json.dumps({
                        'role': 'service', 'digest': digest, 'task': 'autodeploy', 'state': 'failed',
                        'why': f"the canary of its swap is red: {said['line']}"})})
            except Exception:  # noqa: BLE001
                LOG.exception('autodeploy: could not record that %s is not to be loaded', str(digest)[:12])
        return self.canaries[key]

    def swap(self, db, pushes):
        """DEP8, the fast path: every push after the deployed sha that changed a port Lambda's files and has a fresh artifact
        from the gate is deployed by swapping the alias live (fastdeploy.py), before the debounce and apart from the slow
        ring (a tower_infra change is also a slow target: the service image follows and the swap is already live). A head is
        tried once; a failure is an event, never an exception, and leaves the slow path to put the head right."""
        if self.fast is None:
            return
        heads = [each[0] for each in pushes]
        todo = [head for head in heads if head not in self.fast_done and self.fast_functions(head)]
        if not todo:
            return
        last_sha = self.ssm(LAST_SHA)
        start = max(index for index, each in enumerate(heads) if each == last_sha) + 1 if last_sha in heads else len(heads) - 1
        todo = [head for head in todo if heads.index(head) >= start]
        if not todo:
            return
        try:
            for head in todo:
                self.fast_done.add(head)
                found = self.fast.manifest(self.manifest_commits(head))
                if found is None:
                    for function in self.fast_functions(head):
                        self.skipped(function, head, 'no artifact from the gate for this push: the slow path deploys it')
                    continue
                trusted = self.gate_digests(db, found.get('head'))  # DIGEST-FROM-GATE-JOB
                base = found.get('base')
                between = ([self.touched.get(each) for each in heads[heads.index(base) + 1:heads.index(head)]]
                           if base in heads and heads.index(base) < heads.index(head) else None)
                for function in self.fast_functions(head):
                    if function not in (found.get('functions') or {}):
                        self.skipped(function, head, 'the gate built no artifact for this function: the slow path deploys it')
                        continue
                    said = ((found.get('functions') or {}).get(function) or {}).get('sha256')
                    if not trusted or trusted.get(function) != said:  # DIGEST-FROM-GATE-JOB
                        self.skipped(function, head, 'the manifest names a package the gate\'s own artifact job of this head did not '
                                     'say it built: the slow path deploys it')
                        continue
                    if not self.fast.fresh(function, found, between):
                        self.skipped(function, head, 'the artifact may predate a change to its files: slow path')
                        continue
                    # one swap at a time PER FUNCTION (across service tasks); other functions and the slow build never wait
                    key = FAST_LOCK_KEY + self.fast_functions_all().index(function)
                    if not db.rows('select pg_try_advisory_lock(%(key)s)', {'key': key})[0][0]:
                        self.skipped(function, head, AWAY)
                        continue
                    try:
                        self.fast.propagation_s = float(self.settings()['fast_propagation_s'])
                        self.fast.activate_s = float(self.settings()['fast_activate_s'])
                        entry = self.fast.deploy(function, found, head)
                    finally:
                        db.rows('select pg_advisory_unlock(%(key)s)', {'key': key})
                    if entry.get('reason') == 'already live':
                        continue
                    self.fast_log.append({**entry, 'at': int(self.clock())})
                    self.record(db, FAST, f'{FAST}:{head}:{function}', entry)
                    if entry['rolled_back']:
                        self.record(db, ROLLEDBACK, f'{ROLLEDBACK}:{head}:{function}', entry)
                    self.say('fast', f'{function} -> version {entry["version"]} in {entry["swap_ms"]} ms (activate {entry["activate_ms"]} ms)' if entry['ok'] else
                             f'{function} failed: {entry["reason"]}', self.clock(), head=head[:12])
        except Exception:  # noqa: BLE001 - the slow path is the net
            LOG.exception('autodeploy: fast deploy failed')

    def gate_digests(self, db, head):
        """DIGEST-FROM-GATE-JOB: {function: sha256} the gate's artifact job of `head` said it built (the last JSON line of its
        log with `digests`), or None when there is no such job, it did not succeed or said none."""
        if not head or not re.fullmatch(r'[0-9A-Za-z]{7,64}', str(head)):  # no LIKE wildcard can reach the key
            return None
        found = db.rows(GATE_DIGESTS, {'tenant': self.tenant, 'key': f'check:%:{head}:artifact:lambda%'})
        if not found or not found[0][0]:
            return None
        tail = (json.loads(found[0][0]) or {}).get('tail') or ''
        for line in reversed(tail.strip().splitlines()):
            try:
                said = json.loads(line)
            except ValueError:
                continue
            if isinstance(said, dict) and isinstance(said.get('digests'), dict):
                return said['digests']
        return None

    def manifest_commits(self, head):
        """The commit ids whose gate manifest to try for a head: for a landed event its pr_head and the sha its manifest_key
        names first (the gate keys the manifest by the PR head, never the merge sha), then the push's commits, then the head."""
        event = self.landed.get(head) or {}
        key = event.get('manifest_key')
        named = key[len('artifacts/lambda/head/'):-len('.json')] if (
            isinstance(key, str) and key.startswith('artifacts/lambda/head/') and key.endswith('.json')) else None
        return list(dict.fromkeys(each for each in [event.get('pr_head'), named, *(self.commits.get(head) or []), head] if each))

    def skipped(self, function, head, why):
        """A fast target that was not swapped is shown in GET /v1/deploy/status too (ok null, skipped why), never silent."""
        self.fast_log.append({'function': function, 'sha': head, 'ok': None, 'skipped': why, 'at': int(self.clock())})
        self.say('fast', f'{function}: {why}', self.clock(), head=head[:12])

    @staticmethod
    def fast_functions_all():
        from . import fastdeploy
        return list(fastdeploy.FUNCTIONS)

    def fast_functions(self, head):
        from . import fastdeploy
        event = self.landed.get(head)
        if event is not None and isinstance(event.get('functions'), list):  # the delivery's word: the gate's fast targets, [] for none
            return sorted(function for function in event['functions'] if function in fastdeploy.FUNCTIONS)
        return fastdeploy.functions_of(self.touched.get(head) or [])  # secondary: the paths a push listed

    def slow_needed(self, pushes, last_sha):
        """False only when every push after the deployed sha is known to have changed no slow path (fast-only, docs, tests,
        config): then a build would only classify and exit. Unknown (the deployed sha is not among the pushes, or a push
        did not list its paths) is True: the build classifies by itself."""
        heads = [each[0] for each in pushes]
        if last_sha not in heads:
            return True
        for head in heads[max(index for index, each in enumerate(heads) if each == last_sha) + 1:]:
            paths = self.touched.get(head)
            if paths is None or any(slow_path(path) for path in paths):
                return True
        return False

    def ring(self, db, cfg, head, pushed_at, last, now):
        rings, settled = self.ledger(db, now)
        if rings:
            tail = rings[-1]
            lost = None
            if tail['build'] not in settled:
                lost = self.lost_why(tail, last, cfg, now)
                if lost is None:
                    return self.say('skip', 'running: the last ring has no ended build yet', now, build=tail['build'])
                self.declare_lost(db, tail, lost, now)
        spent = self.spent(rings, settled, cfg['usd_per_min'], now)
        self.alarm(db, cfg, spent, now)
        if spent >= cfg['monthly_usd']:
            return self.say('skip', f'budget: US${spent:.2f} estimated this month of US${cfg["monthly_usd"]:.2f}', now)
        answer = self.invoke({'source': 'autodeploy'})
        code, body = answer.get('statusCode'), answer.get('body')
        if code == 202:
            build = (json.loads(body) if body else {}).get('build') or f'unknown-{int(now)}'
            self.record(db, RUNG, f'{RUNG}:{build}', {'build': build, 'head': head, 'pushed_at': pushed_at,
                                                       'source': 'autodeploy'})
            return self.say('ring', 'started', now, head=head[:12], build=build)
        self.running_until, self.running_since = now + self.running_retry_s, now
        if code == 409:
            return self.say('skip', 'running: the doorbell answered 409, ring again after it ends', now, head=head[:12])
        LOG.error('autodeploy: the doorbell answered %s %s', code, str(body)[:200])
        return self.say('skip', f'the doorbell answered {code}', now)

    @staticmethod
    def in_progress(build, now):
        """DEP-WATCHDOG: what a build that wrote last-build at its start is doing: {build, step, elapsed_s, idle_s, steps}; else None."""
        if not isinstance(build, dict) or build.get('status') != 'in_progress':
            return None
        started, updated = build.get('started') or now, build.get('updated') or build.get('started') or now
        return {'build': build.get('build_id'), 'step': build.get('step') or None, 'elapsed_s': max(0, int(now - started)),
                'idle_s': max(0, int(now - updated)), 'steps': build.get('steps') or []}

    @staticmethod
    def lost_why(tail, last, cfg, now):
        """None while the ring's build may still report; else why it is lost. The safety timeout for FAILURE, not a timer for
        waiting: (1) the build that writes last-build at its start went silent (no step or stack event) for longer than the
        deployer's budget, or (2) no build ended after lost_after_s since the ring (the project's hard limit plus a margin)."""
        mine = last if last.get('build_id') == tail['build'] else {}
        limit = cfg['lost_after_s']
        if mine.get('status') == 'in_progress':
            idle = now - (mine.get('updated') or mine.get('started') or tail['at'])
            if idle > min(limit, DEPLOYER_BUDGET_S):
                return f'lost: in_progress build with no stack or step event for {idle:.0f} s (step {mine.get("step") or "?"})'
        age = now - tail['at']
        if age >= limit:
            return f'lost: no ended build after {age:.0f} s'
        return None

    def declare_lost(self, db, tail, why, now):
        """One platform.deploy.lost event per build; the next ring (the caller's) takes the current head at once."""
        LOG.warning('autodeploy: %s (build %s); ringing the current head again', why, tail['build'])
        if tail['build'] not in {each['build'] for each in self.lost_events}:
            payload = {'build': tail['build'], 'rung_at': int(tail['at']), 'line': why, 'at': int(now)}
            self.record(db, LOST, f'{LOST}:{tail["build"]}', payload)
            self.lost_events.append(payload)

    def alarm(self, db, cfg, spent, now):
        """The cost alarm (DEP7): the month's estimated spend at alarm_usd publishes platform.deploy.cost_alarm once a month.
        No new paid service: the event is in the log, the line is in GET /v1/deploy/status; deploy.monthly_usd stops the rings."""
        month = time.strftime('%Y-%m', time.gmtime(now))
        if spent < cfg['alarm_usd'] or month in self.alarmed:
            return
        self.record(db, ALARM, f'{ALARM}:{month}', {'month': month, 'usd': round(spent, 4), 'alarm_usd': cfg['alarm_usd'],
                                                    'monthly_usd': cfg['monthly_usd']})
        self.alarmed.add(month)
        LOG.warning('autodeploy: COST ALARM: US$%.2f estimated this month, alarm at US$%.2f', spent, cfg['alarm_usd'])

    # --- what it reads ----------------------------------------------------------------------------------------------
    def newest_push(self, db, branch, now):
        pushes = self.pushes(db, branch, now)
        return pushes[-1] if pushes else None

    @staticmethod
    def pending(pushes, deployed):
        """How many heads of the base were pushed after the deployed one (all of the window when it is not in it)."""
        heads = [each[0] for each in pushes]
        if deployed in heads:
            return len(heads) - 1 - max(index for index, each in enumerate(heads) if each == deployed)
        return len(heads)

    def rows_since(self, db, name, sql, params, now):
        """LOOK-READS-WHAT-IS-NEW: the (occurred_at, payload) rows of a 7-day read of the log, oldest first: all of them
        the first time, and after that only the rows newer than the newest one read, less OVERLAP_S (an event whose
        transaction committed after a newer one was read), joined to the rows kept. Every look read the 7 days again:
        the pushes' payloads, a jsonb path and a containment over each (live 12/11 10:38 UTC: 188 ms active on the
        database inside the second of a swap, the look of the service that had just taken over)."""
        horizon = now - 7 * 86400
        with self.reading:
            kept = self.rows_read.get(name) or []
            since = horizon if not kept else max(horizon, kept[-1][0].timestamp() - OVERLAP_S)
            found = db.rows(sql, {**params, 'since': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since))})
            rows = ([row for row in kept if horizon < row[0].timestamp() <= since]
                    + [row for row in found if row[0].timestamp() > since])
            self.rows_read[name] = rows
            return list(rows)

    def read_ahead(self, db):
        """LOOK-READS-WHAT-IS-NEW: the 7 days read by a service that stands by (once, when it first warms), so the
        first look after it takes over reads only what is new. Reads, and decides nothing."""
        cfg = self.settings()
        return len(self.pushes(db, cfg['base_branch'], self.clock()))

    def pushes(self, db, branch, now):
        """(head, pushed_at) of every push to the base in 7 days, oldest first, consecutive repeats of a head dropped."""
        ref = json.dumps([{'ref': f'refs/heads/{branch}'}])
        found = []
        for occurred_at, updates in self.rows_since(db, f'pushes:{branch}', PUSHES, {'ref': ref}, now):
            for update in updates or []:
                if update.get('ref') == f'refs/heads/{branch}' and not update.get('deleted') and update.get('after'):
                    if not found or found[-1][0] != update['after']:
                        found.append((update['after'], occurred_at.timestamp()))
                    self.touched[update['after']] = self.paths_of(update)
                    self.commits[update['after']] = self.commit_ids(update)
        return self.landings(db, now, found)

    def landings(self, db, now, found):
        """FAST-ON-LANDED: the platform.deploy.landed events of 7 days complete the pushes. The delivery that merged knows the
        files (git diff base..head) and the gate's manifest, which Origin's push events do not carry: its paths replace an
        unknown set, its pr_head names the manifest, and a merge whose push was never seen is a head of the base too."""
        known = {each[0] for each in found}
        for occurred_at, event in self.rows_since(db, 'landings', LANDINGS, {}, now):
            sha = (event or {}).get('merge_sha')
            if not sha:
                continue
            self.landed[sha], self.landed_at[sha] = event, occurred_at.timestamp()  # IMAGE-SWAP-TIGHTEN: landed_s's start
            if isinstance(event.get('paths'), list):
                self.touched[sha] = event['paths']
            if event.get('pr_head'):
                self.commits[sha] = list(dict.fromkeys([event['pr_head'], *self.commits.get(sha, [sha])]))
            if sha not in known:
                known.add(sha)
                found.append((sha, occurred_at.timestamp()))
        found.sort(key=lambda each: each[1])
        return found

    @staticmethod
    def commit_ids(update):
        """The commit ids a push listed, the pushed head first, then the ones it listed (a merge lists the PR's commits)."""
        listed = [update.get('headCommit') or {}] + [each for each in update.get('commits') or [] if isinstance(each, dict)]
        ids = [str(each.get('id') or each.get('sha')) for each in listed if each.get('id') or each.get('sha')]
        return list(dict.fromkeys([update['after']] + ids))

    @staticmethod
    def paths_of(update):
        """The paths a push changed, from the head commit and the commits the forge listed; None when it listed none."""
        commits = [update.get('headCommit') or {}] + [each for each in update.get('commits') or [] if isinstance(each, dict)]
        listed, found = False, set()
        for commit in commits:
            for key in ('added', 'modified', 'removed'):
                if isinstance(commit.get(key), list):
                    listed = True
                    found.update(str(path) for path in commit[key])
        return sorted(found) if listed else None

    def last_build(self):
        raw = self.ssm(LAST_BUILD)
        try:
            value = json.loads(raw) if raw else {}
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    def ledger(self, db, now):
        """(rings oldest first as {'at', 'build'}, {build: seconds}) of the month, which covers the last 24 h too."""
        since = min(month_start(now), now - 86400)
        rings, settled, self.cycles, self.lost_events = [], {}, [], []
        for kind, occurred_at, payload in db.rows(LEDGER, {'since': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since))}):
            if kind == RUNG:
                if payload.get('source', 'autodeploy') != 'autodeploy':
                    continue  # a ring someone else made never counts against the caps (the doorbell writes none today)
                rings.append({'at': occurred_at.timestamp(), 'build': payload.get('build')})
            elif kind == CYCLE:
                self.cycles.append({'at': int(occurred_at.timestamp()), **{key: payload.get(key) for key in (
                    'build', 'seconds', 'usd', 'status', 'targets', 'rolled_back', 'ack', 'ack_smoke')},
                    **{key: payload[key] for key in ('rollout_wait_s', 'rollout', 'settled', 'started', 'ended') if key in payload}})  # SLOW-PATH-NO-ROLLOUT-WAIT
            elif kind == LOST:
                self.lost_events.append({**payload, 'at': payload.get('at') or int(occurred_at.timestamp())})
            elif kind == ALARM:
                self.alarmed.add(payload.get('month'))
            else:
                settled[payload.get('build')] = payload.get('seconds') or 0
        return rings, settled

    @staticmethod
    def spent(rings, settled, usd_per_min, now):
        """US$ estimated for the month: settled builds by their seconds; a ring not settled by the shorter of the
        project's timeout and the time until the next ring (the doorbell runs one build at a time) or now."""
        start, total = month_start(now), 0.0
        for index, each in enumerate(rings):
            if each['at'] < start:
                continue
            if each['build'] in settled:
                seconds = settled[each['build']]
            else:
                follows = rings[index + 1]['at'] if index + 1 < len(rings) else now
                seconds = min(BUILD_MAX_S, max(0, follows - each['at']))
            total += seconds / 60 * usd_per_min
        return total

    def record(self, db, kind, ident, payload):
        db.rows(RECORD, {'id': ident, 'type': kind, 'payload': json.dumps(payload)})

    def read_overrides(self, db, now):
        """The deploy.* changes of `scripts/config set`, from the commit messages of the pushes to train/events."""
        since = self.config_since or now - 90 * 86400
        found = db.rows(PUSHES, {'since': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since)),
                                 'ref': json.dumps([{'ref': EVENTS_REF}])})
        self.config_since = max([row[0].timestamp() for row in found] + [since])
        for _, updates in found:
            for update in updates or []:
                if update.get('ref') != EVENTS_REF:
                    continue
                try:
                    events = json.loads(((update.get('headCommit') or {}).get('message')) or '{}').get('events') or []
                except ValueError:
                    continue
                for event in events:
                    payload = event.get('payload') or {}
                    name = str(payload.get('name', ''))
                    if event.get('type') != 'config.changed' or not name.startswith('deploy.'):
                        continue
                    key, at = name[len('deploy.'):], str(event.get('occurred_at') or payload.get('at') or '')
                    if key not in DEFAULTS or (key in self.overrides and self.overrides[key][0] > at):
                        continue
                    if payload.get('new') is None:
                        self.overrides.pop(key, None)
                        continue
                    try:
                        self.overrides[key] = (at, coerce(key, payload['new']))
                    except ValueError as error:
                        LOG.warning('autodeploy: ignored %s', error)


def from_boto3(scope, environ=None):
    """The service's AutoDeploy, or None when TOWER_DOORBELL_FUNCTION is not set (a local run): boto3 clients with short
    timeouts and no retries, because the doorbell is the one that serialises and the next look rings again."""
    environ = os.environ if environ is None else environ
    function = environ.get('TOWER_DOORBELL_FUNCTION')
    if not function:
        return None
    import boto3
    from botocore.config import Config
    region = environ.get('AWS_REGION')
    settings = Config(connect_timeout=3, read_timeout=15, retries={'max_attempts': 1})
    ssm, lam = boto3.client('ssm', region_name=region, config=settings), boto3.client('lambda', region_name=region, config=settings)

    def read(name):
        try:
            return ssm.get_parameter(Name=name)['Parameter']['Value']
        except ssm.exceptions.ParameterNotFound:
            return None

    def invoke(payload):
        out = lam.invoke(FunctionName=function, InvocationType='RequestResponse', Payload=json.dumps(payload).encode())
        body = json.loads(out['Payload'].read() or b'{}')
        if out.get('FunctionError'):
            raise RuntimeError(f'the doorbell failed: {str(body)[:200]}')
        return body

    fast = None
    if environ.get('TOWER_ARTIFACT_BUCKET'):  # DEP8: the pointer swap needs the gate's artifacts; without the bucket only the slow path
        from . import fastdeploy
        wide = Config(connect_timeout=3, read_timeout=60, retries={'max_attempts': 1})
        fast = fastdeploy.FastDeploy(boto3.client('lambda', region_name=region, config=wide),
                                     boto3.client('s3', region_name=region, config=settings), environ['TOWER_ARTIFACT_BUCKET'])
    found = AutoDeploy(scope, read, invoke, doorbell=function, check_every_s=float(environ.get('TOWER_AUTODEPLOY_CHECK_S', 30)),
                       running_retry_s=float(environ.get('TOWER_AUTODEPLOY_RUNNING_RETRY_S', 60)), fast=fast)
    found.tenant = environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)  # IMAGE-PREWARM-C
    from . import canary
    found.publish = lambda said, subject: canary.alert(said, environ, subject=subject)  # MODE-CHANGE-ALERT
    if environ.get('TOWER_ARTIFACT_BUCKET'):  # SLOW-PATH-NO-ROLLOUT-WAIT: where deploy.sh publishes the head's code bundle
        found.bundles = code_bundle.S3Store(environ['TOWER_ARTIFACT_BUCKET'])
        from . import queue_deploy  # QUEUE-RELOAD: the service prepares the merge's bundle and puts it beside deploy.sh's
        from botocore.exceptions import ClientError
        bucket, s3 = environ['TOWER_ARTIFACT_BUCKET'], boto3.client('s3', region_name=region, config=settings)

        def put(key, data):
            try:
                s3.head_object(Bucket=bucket, Key=key)
            except ClientError:
                s3.put_object(Bucket=bucket, Key=key, Body=data)
        found.queue = queue_deploy.QueueReload(read, put)
    return found


WATCHERS = []  # the process's look, once started


def read_ahead(scope):
    """LOOK-READS-WHAT-IS-NEW: the standing-by service's read of what its first look will need (AutoDeploy.read_ahead);
    None with no look in this process."""
    if not WATCHERS:
        return None
    with scope() as db:
        return WATCHERS[0].read_ahead(db)


LOOK_FAILURES_SAID, LOOK_BACKOFF_MAX_S = 3, 60.0  # AUTODEPLOY-LIVES: failures in a row before the alert; the longest pause


def start(scope, stop, wait=None, config=None, active=None, gate=None, make=None, alert=None):
    """Start the loop in a daemon thread; answers the thread, or None when not configured. active (IMAGE-PREWARM-A: the
    service's live_image gate) answers False while this image stands by: no look, no ring, no swap; None looks always.
    gate (IMAGE-SWAP-RELOAD: that gate) counts a look as work in flight (engaged), which a reload of the task waits for (a
    fast swap takes seconds); once a reload holds the gate no look starts."""
    def made():
        found = make()
        if found is not None:
            found.config = config
            WATCHERS[:] = [found]  # LOOK-READS-WHAT-IS-NEW: for the standby's read ahead (read_ahead())
        return found
    make = make or (lambda: from_boto3(scope))
    # LOOKS-AFTER-WORK: a process the role waits for (the reserve told to go at a drill) makes its look's AWS clients in
    # the look's thread after its first work, not before its first pass: five clients' service models on 0.25 vCPU were
    # most of the 0.27 to 0.30 s between its settings and its loop (after_read) in every drill of 13/11
    later = live_image.waited_for(gate) and bool(os.environ.get('TOWER_DOORBELL_FUNCTION'))
    watcher = None if later else made()
    if watcher is None and not later:
        LOG.info('autodeploy: off (TOWER_DOORBELL_FUNCTION is not set)')
        return None

    def loop():
        nonlocal watcher
        if watcher is None:
            gate.worked.wait(live_image.FIRST_WORK_S)
            watcher = made()
            if watcher is None:
                return
        # DEP-EVENTS: the look is triggered by events (a push or a deploy-ended row of the log, via LISTEN/NOTIFY); the wait
        # below is only the safety timeout that detects a build that never ends or a lost notification, never a retry gate
        # AUTODEPLOY-LIVES (AWS-REVIEW, the Torre 16/11/2026): step() never raises, but the wait, active() and engaged()
        # could, and the thread then ended with a traceback on stderr while the task stayed healthy (the main tick keeps
        # its health file fresh): no more deploys, and nothing said so. A pass that fails is logged and the look goes on
        # after a pause that doubles up to LOOK_BACKOFF_MAX_S; LOOK_FAILURES_SAID failures in a row are published once.
        failures = 0
        while not stop.is_set():
            try:
                if wait is None:
                    if stop.wait(watcher.check_every_s):
                        break
                else:
                    wait(watcher.safety_s())
                    if stop.is_set():
                        break
                with live_image.engaged(gate, 'autodeploy') as free:
                    if free and (active is None or active()):
                        watcher.step(force=True)
            except Exception as error:  # noqa: BLE001 - the deploy's look never ends on an error
                failures += 1
                LOG.exception('autodeploy: the look failed (%d in a row); it goes on', failures)
                if failures == LOOK_FAILURES_SAID:
                    (alert or canary.alert)({'key': 'autodeploy', 'ok': False, 'line': (
                        f'the deploy look failed {failures} times in a row: {type(error).__name__}: {error}')[:300]},
                        subject='tower autodeploy failing')
                if stop.wait(min(LOOK_BACKOFF_MAX_S, 2.0 ** failures)):
                    break
                continue
            failures = 0
    thread = threading.Thread(target=loop, name='autodeploy', daemon=True)
    thread.start()
    LOG.info('autodeploy: watching the pushes to the base, ringing %s', watcher.doorbell if watcher is not None
             else 'its doorbell once the role worked (LOOKS-AFTER-WORK)')
    return thread
