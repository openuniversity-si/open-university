"""IMAGE-PREWARM-A (docs/operations/aws.md 22.9): the live image of each role as data, and the standby.

An image-only deploy of the service or the runner is a pointer swap to a version already up and healthy. The pointer is
the row deploy.live_image_<role> of work.config_value (DEP9): the digest (or content tag) of the image that takes the
role's work. Each process knows its own image from TOWER_IMAGE_DIGEST. A process whose digest is set and differs from a
non-empty pointer stands by: it stays healthy (it beats) and takes no work: a runner claims no run, a service runs no
dispatcher tick and none of the service's other single-writer duties. Several standbys of different digests may exist at
once; only the pointer's digest works. With no pointer (no row, or '') or no TOWER_IMAGE_DIGEST every process works, as
before, and gate() answers None so the callers run exactly their old path.

The swap is seen at once, never on a poll: a write of the row fires migration 0010's trigger (NOTIFY tower_config), and
config_data.listen() refreshes the gate on it; its timeout is only the safety of a lost notification. A standby that
turns live sets an event its waits block on, so it takes work within the same instant, and records
platform.deploy.image_live {role, digest, version, task, swap_s} (tenant_id null: the installation's, like
platform.runner.warm), swap_s timing the pointer's write to the role's first work (IMAGE-SWAP-TIGHTEN, below). A process
the pointer leaves stops taking new work, finishes what it has in flight, and is retired: the runner's slots end and the
task exits; the service only stands by. Standard library only.

What the digest names (IMAGE-PREWARM-B1): a code version, not only an image. A task on an image built for its head has the
image's digest or content tag; a task started on an image already built with a code bundle (TOWER_CODE_KEY,
TOWER_CODE_SHA256; tower_infra.code_bundle) has the bundle's sha256, which code_bundle sets as TOWER_IMAGE_DIGEST only once
it runs that code, and a bundle that cannot be loaded exits before any work. Either way the pointer's value is compared as
an opaque string; the semantics here are the same.

A standby the prewarm starts (IMAGE-PREWARM-B2, tower_infra.prewarm) has TOWER_STANDBY=1: its gate is strict, so no pointer
is not live for it; it works only once the pointer names its digest. Without that, a head's standby started while no pointer
is written would take the role's work with an authoring branch's code. OnceLive runs a start that a standby must not run
before it turns live (the service's DBOS.launch: its system-schema migrations, version registration and recovery; since
IMAGE-SWAP-SERVICE-READY only for an ECS task that starts standing by: the prewarm's standby launches at once, verifying).

IMAGE-PREWARM-C: the ECS tasks carry TOWER_IMAGE_DIGEST too (their image's reference, or the bundle the slow path deployed
them with, LiveCode), and are never strict: with no pointer they work, under a pointer naming another digest they stand by.
After a swap to S the slow path deploys the ECS service with bundle S; that task is live at once (the pointer names its
digest) beside the promoted standby, so once it is up it hands the role over (handover: the service's pointer written ''
only if it still names S, and platform.deploy.image_retired): the strict standby stops working, the ECS task, not strict,
goes on. sole() is active() less that short overlap, for the duties two live services must not share (the prewarm's tasks).

IMAGE-SWAP-TIGHTEN: platform.deploy.image_live is recorded when the role really takes work, not when the read turns it
live: the runner after its first TAKE, the service after its first dispatch tick (DBOS.launch, deferred as above, before
it). Its swap_s is notify_s (READ's third column: the pointer's write to this read, on the database clock) + work_s (the
read to the work, this process's clock), with the service's launch_s apart; the record's own statement runs after the
measure. A standby also beats (beat(): work.standby_beat, migration 0014) on every standby pass, the evidence the landing
swaps on (port.deploy_landed).

IMAGE-SWAP-SERVICE-READY: the role is ready before the swap, so the swap is only the wake. The prewarm's service standby
(strict) launches DBOS while it stands by (tower_infra.__main__.serve), not at the swap: live on 10/11 the launch at the
swap cost 2.76 s and the first tick after it ~6.1 s more on the task's 0.25 vCPU. The service's image_live is timed when its
first dispatch is committed (workflows.tick's dispatched hook: claims made, a container run takeable), before the workflows
start, with dispatch_s (reap and dispatch) apart; the runner's carries take_s (its first TAKE's round trip), so work_s splits
into the wake and the work. after_work(check) is check() for the threads that wake on the same notifications as the swap
(the autodeploy's and the prewarm's looks, the landing's tower_deploy): after a swap they wait for the first work
(FIRST_WORK_S at most), so the dispatch has the task's CPU first.

IMAGE-SWAP-TICK: the role's first work part by part, with nothing else on the swap's second. The service's loop keeps a
connection of its own (tower_infra.__main__.serve: container.Reconnecting, autocommit): the standby's beat goes through it
every pass and the first tick finds it open, with no pool checkout and no login, each statement one round trip. work_s
ends at the role's first work (working(): the runner's first TAKE answered; the service's first committed claim,
first_work(), or the end of a first pass with nothing to claim) and is said in parts that add up to it: wake_s, connect_s
and take_s, or reap_s and dispatch_s (workflows.tick), with pass_s and jobs for the service's whole first pass.
A look the landing's commit wakes is left as it was (after_work): it asks before the gate's listener has read the pointer,
so the service the swap retires runs the landing's look and the one it promotes does not. Making it read the pointer first
(#502) moved that look, with the Lambdas it swaps, to the promoted service's 0.25 vCPU: live 11/11 its first work came in
0.116 s and then no good tick for 10 s (the ECS task failed the role over; the swap's canary was dispatched in 10.5 s).
A standby also keeps its wake listening and drained (tower_infra.wake: the service's loop, each runner slot), so the first
wait after its first work neither logs in nor misses what was notified during that pass.

IMAGE-SWAP-FAILOVER: a promoted standby that dies or hangs never leaves its role without a live process. On 10/11 both
standbys a swap had promoted were interrupted by Spot and exited cleanly with the pointer still naming their bundle: the
ECS tasks stood by and nothing was dispatched for 23 minutes. (1) The live beat: a process that is live because the pointer
names its digest (pointed(): the promoted standby, the reconciled ECS task while sharing) stamps work.standby_beat.live_at
(migration 0016) while it works, LIVE_BEAT_S apart at most (live_beat(): the service after each good dispatch tick, so a
hung or failing loop stops beating; the runner at each TAKE and from the keeper of each run in flight, pace(), so a runner
whose slots are all busy never looks dead). With no pointer nothing beats: today's path. (2) The watchdog: the standby pass
of an ECS task (not strict; a pointer names another digest) is one statement (WATCH): its own beat, the pointer, and the
seconds since the pointed digest's newest live beat or the pointer's write, whichever is later, on the database clock.
Past deploy.live_stale_s (registry, 10 s) it empties the pointer by the same compare-and-swap (release(): one of the
handover, the failover and the autodeploy's revert wins, and platform.deploy.image_retired says who: by failover, with
stale_s) and, not strict, works at once. The roles fail over apart; a pointer the pass finds changed (a lost
notification) is read then. An ECS runner the pointer leaves stays up standing by (runner.loop), so it is there to do it.
(3) The handback, the first answer to a Spot interruption (it sends SIGTERM about two minutes ahead; both standbys of
10/11 had 40 s between it and their end): on SIGTERM a promoted standby (strict) first gives its role back (on_term(),
Gate.handback(): one statement, LEAVE, on a connection of its own with short timeouts) and only then stops taking work:
it beats no more, its beat is withdrawn (the landing never swaps onto a standby that is leaving) and the pointer is
emptied if it still names it (by handback), so the ECS task works at once, with no stale window. The watchdog stays the
net for what sends no SIGTERM (a hard kill, a lost host) and for a loop that hangs.

IMAGE-SWAP-RELOAD: after a swap the role returns to the ECS tasks in seconds, not at the reconciliation's rollout (6 to 13
min on a Spot pair, and on a failover the role fell back to the ECS task's old code). The ECS task standing by under a
swapped bundle S loads S in place and takes the role over (Reload: a look on its standby pass, after the beat).
(1) The trigger, one bounded read (RELOAD_OF), no sooner than RELOAD_ASK_S after the task saw the swap, so no statement
of the reload is on the swap's clock: a platform.deploy.image_swap names S (its key), the promoted standby recorded
image_live for this pointer version (a swap that reverts is not chased), and no reload of S failed in this role.
(2) The bundle is staged while the task stands by (code_bundle.stage: fetched, its sha256 and requirements checked,
unpacked); one that cannot be loaded is recorded failed, with nothing touched. (3) The drain: nothing in flight is exec'd
over. Gate.engaged() counts the work of the process (each runner slot's pass, its run included; the autodeploy's and the
prewarm's looks); it counts before it reads the answer and the reload holds the gate (reloading) before it counts, so of
the two one backs off. The service also waits for its DBOS workflows (pending), DRAIN_S at most. (4) The claim
(RELOAD_START), one statement: platform.deploy.image_reload {state: started}, only while the pointer still names S at
that version (a failover, a handback or the revert that emptied it cancels the reload) and one task per turn: its
occurred_at is the pointer's write, so with its id the log's primary key lets one insert through. Then
code_bundle.reload execs the same command on S. (5) The reloaded task (Gate.reloaded) is live at once, sharing with the
promoted standby; at its first work Gate.back() records {state: reloaded, reload_s: the pointer's write to that work}
and hands the role over by EMPTY's compare-and-swap (ALONE: not while another ECS task of the role still stands by on
the code this one left, which would then work on it), the runner's pointer like the service's. The strict standby stands
by and the prewarm retires it. (6) The guard: a started with no reloaded after RELOAD_LIMIT_S is a task that died on the
bundle (ECS restarted it on its task definition's code): the next look records it failed, and a digest that failed is
never reloaded again in that role: the promoted pair keeps the role until the slow path, as before this unit.

DEPLOY-CANARY (tower_infra.canary): a role that beats but does not really work is failed over too. The live beat proves a
loop that turns, not that a job is dispatched, taken and run. After a swap the service that took the role fires a canary
job keyed by the service's pointer (swap:<digest>:<version>). The ECS task standing by on the previous code is its judge,
in the same statement of its standby pass (WATCH's fourth column: that job's state, its age on the database clock and
deploy.canary_limit_s): a canary that ended and not succeeded, or is still open past the limit, empties both pointers by
the same compare-and-swap (platform.deploy.image_retired, by: canary, from whichever ECS task sees it first) and the ECS
tasks work at once. And nothing reloads onto a bundle that has not proven itself: the reload's trigger (RELOAD_OF) also
wants that canary ended succeeded; with none in deploy.canary_limit_s the task stays (the promoted pair keeps the role
until the slow path). A bundle whose canary is red is also recorded as one that must not be loaded (Gate.refuse:
platform.deploy.image_reload {state: failed}, the record a failed reload leaves): no task reloads onto it, and a task ECS
starts later does not boot it from deploy.live_code (code_bundle.newer), which the look wrote when the swap landed.

RELOAD-WITHOUT-STANDBY: a code-only landing with no healthy standby pair is live in seconds too. The swap needs both roles'
Spot standbys beating at the landing; without them the landed bundle S went to the slow path's two ECS rollouts (minutes).
Here the ECS tasks load S in place, one role at a time, with nothing to fall back on but themselves (Order: step() on each
good pass of a live ECS task, not strict and under no pointer). (1) The order: the live service's autodeploy records
platform.deploy.image_reload {state: ordered, digest, key, head} for the landing it could not swap (autodeploy.order: the
swap's own merge-vs-head rule, one order at a time), and notifies. Nothing is read on a pass with no order: a look is owed
at the task's start and when the gate's listener read the pointer again (every notification of tower_config: Gate.reads),
then ORDER_ASK_S apart while the order is open. (2) The runner first: it stages S, takes no new run from then on (its
drain: the runs in flight end, none is killed), claims {state: started, order} in one statement (ORDER_START: only while
the role's pointer is empty and no reload onto S failed, one task per turn) and execs S; its first TAKE records reloaded
(Gate.back). (3) Its judge is the service, still on the code it had: it fires a canary job (order:<head>:runner) and reads
it: green is {state: proven}; red, or a runner that never came up within RELOAD_LIMIT_S, is {state: failed}, the record
that keeps S from being loaded again (Reload.plan, code_bundle.newer). (4) Only then the service: it goes on dispatching
while it waits for its looks, sessions and workflows, and execs S between two ticks, so the dispatcher is away for its exec
and boot alone. It fires its own canary after its first tick (canary.Live: order:<head>:service) and its judge is the
runner. (5) Until its judge says proven a reloaded task does not touch its health file (trusted()): a task that neither
proves itself nor obeys is replaced by ECS, which boots what deploy.live_code named before. (6) The way back: a task
running a bundle that failed (its own reload or the other role's) drains the same way and execs afresh
(code_bundle.afresh): the code a task ECS starts would boot, in place. (7) Both proven, the autodeploy writes
deploy.live_code = S@head (autodeploy.reloads), which the build reads to skip the image and both rollouts. A swap that
lands meanwhile is in charge (the claim wants the pointer empty, and a task standing by follows Reload); past ORDER_LIMIT_S
no task starts a reload and the slow path deploys the head.

IN-TASK-STANDBY: the standby is a successor process inside the ECS task of its role (tower_infra.supervisor), not a Spot
task, and after a swap it keeps the role: nothing reloads by exec. (1) The want: the live service's prewarm records
platform.deploy.successor {digest, key, state: wanted|withdrawn} for the bundle a head holds (tower_infra.prewarm), and
notifies; the open order of a landing with no standby is a want too. Each ECS task's process reads them where it looks
at the order (Order.step: only when a look is owed) and tells its supervisor the set (deploy.intask_standbys of them at
most; 0, the default, is off: nothing here happens). (2) The successor is the prewarm's standby inside the task: strict,
TOWER_STANDBY=intask, its beat's task `<the task>:<bundle, 12>`, DBOS launched, its first statements warmed; its first
beat says platform.deploy.successor {state: up} and notifies the look. A SIGTERM is its dismissal or the task's stop: it
never stays through a grace. (3) The landing swaps onto its beats as onto a Spot standby's (port.LANDED_SWAP). With none
beating at the landing the order is the want, and the look swaps (autodeploy.reloads, by: order) once both roles beat.
The order's bundle stays wanted after that swap (Order.held), whatever pointer a task's look has read by then.
(4) The swap's canary green (the process on the previous code judges, as before), that process, instead of reloading,
gives the role away for good (Reload.heir): once its successor has a live beat it records {state: yielded, from, heir},
never takes work again (Gate.gone), tells the supervisor and ends when what it has in flight ended (the runner's runs, the
service's workflows and looks: finish()). No drain holds the new code: the successor already works. (5) The successor,
told by the supervisor (SIGUSR1: heed()), adopts the role (Gate.adopt, on its next good pass): it reads that yield and is
from then on what a reloaded ECS task is: not strict, {state: reloaded} recorded, and the pointer handed over by ALONE's
compare-and-swap (never while another ECS task of the role still stands by on the code the yielder ran), so it is live
with no pointer and deploy.live_code names its bundle. (6) Canary red: the previous process empties the pointers and
works (by: canary, as before), the bundle is refused, and the want drops it: the supervisor stops the successor.
"""
import contextlib
import json
import logging
import os
import pathlib
import signal
import socket
import threading
import time
import uuid

from . import canary, code_bundle, config_data, database, supervisor

LOG = logging.getLogger('tower_infra.live_image')
STANDBY = 'TOWER_STANDBY'  # IMAGE-PREWARM-B2: set by the prewarm on the standbys it starts: a strict gate
KEYS = {'service': 'deploy.live_image_service', 'runner': 'deploy.live_image_runner'}
# IN-TASK-STANDBY (the module's docstring): TOWER_STANDBY's value for a successor inside the ECS task; the datum that bounds
# them (0: off); the event of a want and of a successor that is up; what the supervisor's SIGUSR1 leaves (heed())
INTASK, SUCCESSORS, SUCCESSOR = code_bundle.INTASK, 'deploy.intask_standbys', 'platform.deploy.successor'
# WARM-PER-PROCESS: when this process was born, in the ids of what a successor says once (up, warm): once per process.
# They were once per (role, bundle, task) in two days, so a successor started again in the same task (its want
# withdrawn and given back, its process ended and restarted) said nothing, and its first process's `warm` stood for it
BORN = str(int(time.time()))
TOLD = []
# SWAP-DRILL: the induced loss of a standby at the instant of the swap (Daniel, 11/11: the swap is measured over N
# landings, the standby Spot took included; the Torre, 12/11: do not wait for chance, induce it by an event). A drill is
# an event that names a bundle and a role; that bundle's successor of that role, if it was born before the drill, ends
# with DRILL_EXIT as its gate turns live (no handback, no beat withdrawn: what a kill is)
DRILL_EVENT, DRILL_EXIT = 'platform.deploy.drill', 137
# SWAP-SECOND: the readings of the database a process that covers takes, at most. SAMPLES-OFF: 0 unless the environment
# asks (TOWER_COVER_SAMPLES): the reading of pg_stat_activity itself took 471 ms of the database's CPU in the second it
# measured (the drill of 13/11 00:08 UTC); what it found is in the board, and it is turned on again to look once more
SAMPLES = int(os.environ.get('TOWER_COVER_SAMPLES', '0') or 0)
COVER_MARGIN_S = 0.3  # SUCCESSOR-LOST: a live beat this much newer than the cover's start is the bundle's new process
WITHDRAW = 'delete from work.standby_beat where role = %(role)s and digest = %(digest)s and task = %(task)s'
DRILL = (f"select 1 from log.event where type = '{DRILL_EVENT}' and tenant_id is null "
         "and occurred_at > to_timestamp(%(born)s::float8) and payload->>'digest' = %(digest)s "
         "and payload->>'role' = %(role)s limit 1")
FIRST_WORK_S = 5  # IMAGE-SWAP-SERVICE-READY: the longest a look woken with the swap waits for the role's first work
LIVE_BEAT_S = 2  # IMAGE-SWAP-FAILOVER: the live beat's cadence: one statement per task this often, whoever calls
HANDBACK_S = 5  # IMAGE-SWAP-FAILOVER: the longest a stopping standby waits for its handback, and its connection's timeouts
# STANDBY-GRACE (architecture review, finding 30): Spot warns a task two minutes ahead (SIGTERM; SIGKILL after the
# container's StopTimeout, 120 s on the standbys). A standby that left at the warning took the landing's swap with it:
# live 11/11 two landings 70 s and 21 s after an interruption found no beat and fell to the reload in place (29 s). A
# standby the engine did not dismiss stays GRACE_S: it beats, a landing may promote it, and the swap needs it only until
# the ECS tasks reload and take the role over (~25 s). DISMISSED: the newest platform.deploy.standby of its role and
# bundle is `stopped` (prewarm records it before its StopTask): that one leaves at once, as before
GRACE_S, GRACE_TICK_S = 100, 0.5
DISMISSED = ("select payload->>'state' from log.event where type = 'platform.deploy.standby' and tenant_id is null "
             "and occurred_at > now() - interval '1 day' and payload->>'role' = %(role)s and payload->>'digest' = %(digest)s "
             "order by occurred_at desc limit 1")
# IMAGE-SWAP-TIGHTEN: the third column, the seconds from the pointer's write to this read on the database clock, is the
# swap's notify_s (the NOTIFY's delivery and the read) when the read turns this image live
READ = ("select v.value::text, v.version, extract(epoch from clock_timestamp() - v.updated_at)::float8 "
        "from work.config_value v join work.tenant t on t.id = v.tenant_id where t.name = %(tenant)s and v.key = %(key)s")
# IMAGE-SWAP-TIGHTEN: recorded once the role has really taken work (Gate.working), with the seconds measured before this
# statement runs (%(parts)s: swap_s, notify_s, work_s, launch_s), so its own lookup is never on the swap's clock; the
# lookup is bounded by occurred_at (the primary key's lead), never a scan of the whole log
LIVE = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        "select %(id)s, null, 'platform.deploy.image_live', clock_timestamp(), %(producer)s, 'deploy/image/' || %(role)s, "
        "jsonb_build_object('role', %(role)s::text, 'digest', %(digest)s::text, 'version', v.version, 'task', %(task)s::text) "
        "|| %(parts)s::jsonb from work.config_value v join work.tenant t on t.id = v.tenant_id "
        "where t.name = %(tenant)s and v.key = %(key)s and v.version = %(version)s::int "
        "and not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.image_live' "
        "and occurred_at > now() - interval '2 days')")
# SWAP-RECORD-WARM: the record's own rehearsal, never committed: LIVE's insert for the role's pointer whatever its version,
# under an id no record has. STALL-SAYS-WHAT (live 12/11 09:25 UTC): the pass of the service that stalled 0.47 s within a
# second of the swap was its own record: this insert, 365 ms on a backend that had never written to log.event
REHEARSE = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            "select %(id)s, null, 'platform.deploy.image_live', clock_timestamp(), %(producer)s, 'deploy/image/' || %(role)s, "
            "jsonb_build_object('role', %(role)s::text, 'digest', %(digest)s::text, 'version', v.version, 'task', %(task)s::text) "
            "from work.config_value v join work.tenant t on t.id = v.tenant_id "
            "where t.name = %(tenant)s and v.key = %(key)s "
            "and not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.image_live' "
            "and occurred_at > now() - interval '2 days')")
# SWAP-TAIL-EVIDENCE (architecture review, finding 19): what the database was doing while the role took its first work: the
# statements of the other backends that began inside the swap's window, by their text's start (literals removed), with how
# many backends ran each, the longest in ms and how many are still running; and the backends open in all. Live 11/11 both
# roles were slow together at two swaps (reap 1.0 s with TAKE 0.85 s; reap 0.58 s with TAKE 0.42 s): the database at the
# landing's instant, and nothing said what held it. Read after the seconds were measured: never on the swap's clock
# SWAP-TAIL-WAITS (live 12/11 02:31 UTC: a swap of 1.049 s; an insert into log.event still running after 0.99 s, the
# delivery's train release after 0.55 s, a beat after 0.49 s): the evidence named the statements and not what held them.
# waits: what each one still running waits on (pg_stat_activity's wait event, type:event; 'cpu' with none: it runs, or
# waits for a core), so a lock, the disk and the CPU are told apart. of: the first literal of the statement that is a
# dotted name of the engine's own families (platform., deploy., service., forge., job., run.: an event type or a key, a
# name of the code; any other literal stays out, as before), so the engine's inserts into log.event, which share their
# first 64 characters, are told apart. Neither is in the record when there is nothing to say
# DB-STALL-EVIDENCE (live 12/11 03:26 UTC, the first swap with waits: 1.32 s, every statement still running waiting on
# nothing, a BEGIN for 127 ms and a 1 ms insert for 1.3 s: the database's host stalled, not a statement). ago: how long
# before this read the group's first statement began, so the window's statements can be put in order. logins (the
# statement's third column): the connections opened inside the window by application name (database.named: who and what
# for), the read's own left out: a login is a fork, a TLS handshake and an IAM token's check on the database's host
BUSY = ("select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object('q', q, 'n', n, 'ms', ms, 'active', active, 'of', named, "
        "'waits', waits, 'ago', ago)) order by ms desc), '[]'::jsonb)::text, "
        "(select count(*) from pg_stat_activity where datname = current_database()), "
        "(select jsonb_object_agg(app, n)::text from (select coalesce(nullif(application_name, ''), '-') as app, count(*) as n "
        "from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid() "
        "and backend_start > clock_timestamp() - %(window)s * interval '1 second' group by 1) born) from ("
        "select left(regexp_replace(regexp_replace(query, '''[^'']*''', '?', 'g'), '\\s+', ' ', 'g'), 64) as q, "
        "substring(query from '''((?:platform|deploy|service|forge|job|run)(?:\\.[a-z_]+)+)''') as named, count(*) as n, "
        "round(max(extract(epoch from (case when state = 'active' then clock_timestamp() else state_change end) - query_start)) "
        "* 1000) as ms, count(*) filter (where state = 'active') as active, "
        "jsonb_agg(distinct coalesce(wait_event_type || ':' || wait_event, 'cpu')) filter (where state = 'active') as waits, "
        "round(max(extract(epoch from clock_timestamp() - query_start)) * 1000) as ago "
        "from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid() "
        "and query_start > clock_timestamp() - %(window)s * interval '1 second' group by 1, 2 order by 4 desc limit 10) recent")
# IMAGE-SWAP-TIGHTEN: a standby's beat (migration 0014), on each standby pass; a beat older than a day goes with it
# SWAP-TAIL-CUT (architecture review, finding 19; the evidence of #518's swap, 11/11: five backends in this statement at the
# swap's instant, up to 253 ms each): the sweep left every beat. It was a delete over the whole table in each of them, once a
# second per slot and per process; the live service runs it on its hourly pass (sweep())
SWEEP_OLD = "delete from work.standby_beat where beat_at < clock_timestamp() - interval '1 day'"
# ... and a process beats once a pass, not once a slot: the four slots of a runner wrote the same row (role, digest, task)
# one after the other, each waiting for the row the one before held. A beat from another connection than the last one's,
# within BEAT_MIN_S of it, is answered with what that one read
BEAT_MIN_S = 0.9
UPSERT = ("insert into work.standby_beat as b (role, digest, task, beat_at) values (%(role)s, %(digest)s, %(task)s, clock_timestamp()) "
          "on conflict (role, digest, task) do update set beat_at = excluded.beat_at")
BEAT = UPSERT
# IMAGE-SWAP-FAILOVER: the standby pass of an ECS task (not strict), still one round trip: that beat, and of its role the
# pointer, the seconds (database clock) since the pointed digest's newest live beat or the pointer's write, whichever is
# later, and deploy.live_stale_s as stored (null: the default). No row: no pointer row
STALE = 'deploy.live_stale_s'
# DEPLOY-CANARY: and, fourth, the canary of the swap the pointer belongs to: the job keyed by the service's pointer while
# it names the same digest (its unique key: one index probe), as {id, state, age_s on the database clock, limit:
# deploy.canary_limit_s as stored}; null: no such canary
SWAP_CANARY = ("(select jsonb_build_object('id', j.id, 'state', j.state, 'age_s', "
               "extract(epoch from clock_timestamp() - uuid_extract_timestamp(j.id)), 'limit', (select s.value "
               f"from work.config_value s where s.tenant_id = p.tenant_id and s.key = '{canary.LIMIT}'))::text "
               "from work.config_value p join work.job j on j.tenant_id = p.tenant_id "
               f"and j.idempotency_key = '{canary.PREFIX}swap:' || (p.value #>> '{{}}') || ':' || p.version "
               f"where p.tenant_id = v.tenant_id and p.key = 'deploy.live_image_service' and p.value = v.value)")
WATCH = (f"with beat as ({UPSERT}) " + "select v.value #>> '{}', extract(epoch from clock_timestamp() - greatest(v.updated_at, "
         "(select max(l.live_at) from work.standby_beat l where l.role = %(role)s and l.digest = v.value #>> '{}')))::float8, "
         f"(select s.value::text from work.config_value s where s.tenant_id = v.tenant_id and s.key = '{STALE}'), {SWAP_CANARY} "
         "from work.config_value v join work.tenant t on t.id = v.tenant_id where t.name = %(tenant)s and v.key = %(key)s")
# IMAGE-SWAP-FAILOVER: the beat of a process that is live because the pointer names its digest: live_at (migration 0016),
# and beat_at with it (the row is not swept; the landing still counts the image healthy)
LIVE_BEAT = ("insert into work.standby_beat as b (role, digest, task, beat_at, live_at) "
             "values (%(role)s, %(digest)s, %(task)s, clock_timestamp(), clock_timestamp()) "
             "on conflict (role, digest, task) do update set beat_at = excluded.beat_at, live_at = excluded.live_at")
# IMAGE-PREWARM-C: the pointer emptied only while it still names this digest (compare-and-swap), and the event, one statement
EMPTY_IF = ("with t as (select id from work.tenant where name = %(tenant)s), "
            "w as (update work.config_value v set value = '\"\"'::jsonb, version = v.version + 1, actor = %(actor)s, "
            "reason = %(reason)s, updated_at = clock_timestamp() from t where v.tenant_id = t.id and v.key = any(string_to_array(%(keys)s, ',')) "
            "and v.value = to_jsonb(%(digest)s::text)")
EMPTY_THEN = (" returning v.key, v.version) "
              "insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
              "select %(id)s, null, 'platform.deploy.image_retired', clock_timestamp(), %(actor)s, 'deploy/image', "
              "%(payload)s::jsonb || jsonb_build_object('keys', (select jsonb_agg(key order by key) from w)) "
              "where exists (select 1 from w) returning (select jsonb_agg(key order by key) from w)::text")
EMPTY = EMPTY_IF + EMPTY_THEN
# IMAGE-SWAP-FAILOVER: a stopping standby's handback, one statement: its beat withdrawn (the landing swaps only onto fresh
# beats, port.LANDED_SWAP) ahead of EMPTY's own compare-and-swap of its pointer and event
LEAVE = ("with gone as (delete from work.standby_beat where role = %(role)s and digest = %(digest)s and task = %(task)s), "
         + EMPTY[len('with '):])
# IMAGE-SWAP-RELOAD: the handover of a reloaded ECS task: EMPTY's compare-and-swap, not while another ECS task of the role
# still stands by (a beat within ALONE_S) on the digest this one ran before its reload (%(was)s): with the pointer emptied
# that task would work on the old code, and with no pointer it would never reload
ALONE_S = 5
ALONE = (EMPTY_IF + " and not exists (select 1 from work.standby_beat b where b.role = %(role)s and b.digest = %(was)s "
         f"and b.task <> %(task)s and b.beat_at > clock_timestamp() - interval '{ALONE_S} seconds')" + EMPTY_THEN)
RELOAD = 'platform.deploy.image_reload'  # IMAGE-SWAP-RELOAD: {role, digest, task, state: started|reloaded|failed, ...}
RELOAD_ASK_S = 1  # a task's first second after it sees a swap is the swap's: no statement of the reload; then a look this often
DRAIN_S = 120  # the longest a service's reload waits for its DBOS workflows: past every adapter's own timeout (the forge's 60 s)
RELOAD_LIMIT_S = 120  # a started reload whose task recorded no work on the bundle by then failed: the task died on it
RELOAD_TASKS = 3  # the ECS tasks of one role that reload one bundle, one at a time: more is a task that keeps dying on it
# The trigger's one read, by the log's indexes (type and occurred_at; image_live by its event_id): the key of the bundle in
# the swap's record (no row: the pointer names no swapped bundle), whether the promoted standby recorded image_live for
# this pointer version, the reloads of the digest in this role, and the database clock
RELOAD_OF = ("select (select payload->>'key' from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
             "and occurred_at > now() - interval '7 days' and payload->>'digest' = %(digest)s and payload->>'swapped' = 'true' "
             "order by occurred_at desc limit 1), "
             "exists (select 1 from log.event where event_id = %(live)s and type = 'platform.deploy.image_live' "
             "and occurred_at > now() - interval '2 days'), "
             f"(select jsonb_agg(payload) from log.event where type = '{RELOAD}' and tenant_id is null "
             "and occurred_at > now() - interval '7 days' and payload->>'role' = %(role)s and payload->>'digest' = %(digest)s)::text, "
             "extract(epoch from clock_timestamp())::float8, "
             # DEPLOY-CANARY: the state of that swap's canary job (keyed by the service pointer's version the swap recorded)
             "(select j.state from (select payload from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
             "and occurred_at > now() - interval '7 days' and payload->>'digest' = %(digest)s and payload->>'swapped' = 'true' "
             "order by occurred_at desc limit 1) s join work.tenant t on t.name = %(tenant)s join work.job j on j.tenant_id = t.id "
             f"and j.idempotency_key = '{canary.PREFIX}swap:' || %(digest)s || ':' || (s.payload->'versions'->>'deploy.live_image_service'))")
# The claim, right before the exec: {state: started} only while the pointer still names the digest at the version this task
# read (the comparison of every other writer of the pointer: one that emptied it first cancels the reload), and one task
# per turn: occurred_at is the pointer's write, so the log's primary key (occurred_at, event_id) lets one insert through
RELOAD_START = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                f"select %(id)s, null, '{RELOAD}', v.updated_at, %(producer)s, 'deploy/image/' || %(role)s, %(payload)s::jsonb || "
                "jsonb_build_object('version', v.version, 'wrote_at', round(extract(epoch from v.updated_at)::numeric, 3), "
                "'at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
                "from work.config_value v join work.tenant t on t.id = v.tenant_id where t.name = %(tenant)s and v.key = %(key)s "
                "and v.value = to_jsonb(%(digest)s::text) and v.version = %(version)s::int "
                "on conflict do nothing returning payload::text")
# {state: reloaded} with reload_s (the pointer's write to this task's first work on the bundle) and boot_s (the claim to
# it), on the database clock; {state: failed} with neither (their parameters null). Once per id
RELOAD_SAY = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
              f"select %(id)s, null, '{RELOAD}', clock_timestamp(), %(producer)s, 'deploy/image/' || %(role)s, %(payload)s::jsonb || "
              "jsonb_strip_nulls(jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3), "
              "'reload_s', round((extract(epoch from clock_timestamp()) - %(wrote_at)s::float8)::numeric, 3), "
              "'boot_s', round((extract(epoch from clock_timestamp()) - %(started_at)s::float8)::numeric, 3))) "
              f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{RELOAD}' "
              "and occurred_at > now() - interval '2 days')")

# RELOAD-WITHOUT-STANDBY (the module's docstring): the order to load a landed bundle in place, with no standby
ROLES = ('runner', 'service')  # the order they reload in
ORDER_LIMIT_S = 300  # how long an order is followed: past it no task starts a reload, and the slow path deploys the head
ORDER_SETTLE_S = 600  # a newer order waits this long at most for one not settled: every reload it started was judged by then
ORDER_ASK_S = 0.5  # the looks of a task while an order is open
# every statement that says something of an order wakes who waits on it: the gates' listeners (they read the pointer again,
# and a look at the order is owed: Gate.reads), the autodeploy's look, the service's tick and the runner's slots
WOKEN = ("select pg_notify('tower_config', type), pg_notify('tower_deploy', type), pg_notify('tower_work', type), "
         "pg_notify('tower_runs', type) from said")
# One read, by the log's index (type, occurred_at): the newest order of the last hour (or, to a task whose own reload is
# not judged yet, the order that started it: %(head)s, '' for the newest), its age, what was said of it since
# (started, reloaded, proven, failed, back, done: the events that carry its head as `order`), whether a reload onto its
# digest ever failed (7 days: the guard), each role's canary job {state, age_s} (order:<head>:<role>, null: none yet),
# deploy.canary_limit_s as stored and the database clock. No row: no order
ORDER_OF = ("with o as (select payload, occurred_at from log.event "
            f"where type = '{RELOAD}' and tenant_id is null and occurred_at > now() - interval '1 hour' "
            "and payload->>'state' = 'ordered' and %(head)s::text in ('', payload->>'head') order by occurred_at desc limit 1) "
            "select o.payload::text, extract(epoch from clock_timestamp() - o.occurred_at)::float8, "
            "(select jsonb_agg(e.payload order by (e.payload->>'at')::float8) from log.event e "
            f"where e.type = '{RELOAD}' and e.tenant_id is null and e.occurred_at >= o.occurred_at "
            "and e.payload->>'order' = o.payload->>'head')::text, "
            f"exists (select 1 from log.event f where f.type = '{RELOAD}' and f.tenant_id is null "
            "and f.occurred_at > now() - interval '7 days' and f.payload->>'state' = 'failed' "
            "and f.payload->>'digest' = o.payload->>'digest'), "
            "(select jsonb_object_agg(r.role, (select jsonb_build_object('state', j.state, 'age_s', "
            "extract(epoch from clock_timestamp() - uuid_extract_timestamp(j.id))) from work.job j "
            "join work.tenant t on t.id = j.tenant_id where t.name = %(tenant)s "
            f"and j.idempotency_key = '{canary.PREFIX}order:' || (o.payload->>'head') || ':' || r.role)) "
            "from unnest(array['runner', 'service']) r(role))::text, "
            "(select s.value::text from work.config_value s join work.tenant t on t.id = s.tenant_id "
            f"where t.name = %(tenant)s and s.key = '{canary.LIMIT}'), "
            "extract(epoch from clock_timestamp())::float8 from o")
# The claim, right before the exec: {state: started} only while the order is there, the role's pointer is empty (a swap that
# landed meanwhile is in charge) and no reload onto the digest failed; one task per turn: occurred_at is the order's, so
# the log's primary key (occurred_at, event_id) lets one insert through. wrote_at is the order's time: the reloaded
# task's reload_s (RELOAD_SAY) is the order to its first work on the bundle
ORDER_START = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
               f"select %(id)s, null, '{RELOAD}', o.occurred_at, %(producer)s, 'deploy/image/' || %(role)s, %(payload)s::jsonb || "
               "jsonb_build_object('wrote_at', round(extract(epoch from o.occurred_at)::numeric, 3), "
               "'at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
               f"from log.event o where o.event_id = %(order)s and o.type = '{RELOAD}' and o.occurred_at > now() - interval '1 hour' "
               "and not exists (select 1 from work.config_value v join work.tenant t on t.id = v.tenant_id "
               "where t.name = %(tenant)s and v.key = %(key)s and v.value <> '\"\"'::jsonb) "
               f"and not exists (select 1 from log.event f where f.type = '{RELOAD}' and f.tenant_id is null "
               "and f.occurred_at > now() - interval '7 days' and f.payload->>'state' = 'failed' "
               "and f.payload->>'digest' = %(digest)s) on conflict do nothing returning payload::text")
# What a task says of an order (proven, failed, back), once per id, and the wake
ORDER_SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
             f"select %(id)s, null, '{RELOAD}', clock_timestamp(), %(producer)s, 'deploy/image/' || %(role)s, %(payload)s::jsonb || "
             "jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
             f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{RELOAD}' "
             f"and occurred_at > now() - interval '2 days') returning type) {WOKEN}")
# IN-TASK-STANDBY: one read where a task looks at the order: deploy.intask_standbys as stored (null: the default, on: DEFAULTS-AS-LIVE) and
# the bundles wanted now, newest first: the newest platform.deploy.successor of each digest in a day is `wanted`, and no
# reload onto it failed (a canary red: Gate.refuse)
WANTS = ("select (select s.value::text from work.config_value s join work.tenant t on t.id = s.tenant_id "
         f"where t.name = %(tenant)s and s.key = '{SUCCESSORS}'), "
         # PROMOTED-SUCCESSOR-STAYS: and the bundle a role's pointer names, wanted or withdrawn, first: its successor has
         # the role, or is taking it, whatever the prewarm says of the branch it came from (read with the wants, in one
         # statement: the look may come before this process's listener read the pointer)
         "(select jsonb_agg(jsonb_build_object('digest', w.digest, 'key', w.key) order by w.pointed desc, w.at desc) from ("
         "select distinct on (payload->>'digest') payload->>'digest' as digest, payload->>'key' as key, "
         "payload->>'state' as state, occurred_at as at, payload->>'digest' in (select p.value #>> '{}' "
         "from work.config_value p join work.tenant t on t.id = p.tenant_id where t.name = %(tenant)s "
         f"and p.key in ('{KEYS['service']}', '{KEYS['runner']}')) as pointed "
         f"from log.event where type = '{SUCCESSOR}' and tenant_id is null "
         "and occurred_at > now() - interval '1 day' and payload->>'state' in ('wanted', 'withdrawn') "
         "order by payload->>'digest', occurred_at desc) w where (w.state = 'wanted' or w.pointed) and not exists ("
         f"select 1 from log.event f where f.type = '{RELOAD}' and f.tenant_id is null "
         "and f.occurred_at > now() - interval '7 days' and f.payload->>'state' = 'failed' "
         "and f.payload->>'digest' = w.digest))::text")
# a successor's first beat: platform.deploy.successor {role, digest, task, state: up}, once, and the looks are woken (the
# autodeploy's, which swaps a landing that waited for it; the prewarm's)
UP = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
      f"select %(id)s, null, '{SUCCESSOR}', clock_timestamp(), %(producer)s, 'deploy/successor/' || %(role)s, %(payload)s::jsonb || "
      "jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
      f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{SUCCESSOR}' "
      "and occurred_at > now() - interval '2 days') returning type) select pg_notify('tower_deploy', type) from said")
# SUCCESSOR-HOLDS-SAID: what a task's process told its supervisor to hold, each time it changes: platform.deploy.successor
# {role, task, state: holds, digest (the first, null: none), digests, order}. It was a line of the task's own log: on 12/11 two landings found no standby
# because the tasks held the successor of an old order's bundle in their one slot, and only inference from the other
# events said so. No wake: nobody acts on it
HOLDS = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
         f"select %(id)s, null, '{SUCCESSOR}', clock_timestamp(), %(producer)s, 'deploy/successor/' || %(role)s, %(payload)s::jsonb || "
         "jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3))")
# whether this task's successor of the swapped bundle works: its live beat (LIVE_BEAT: after a good tick, at a TAKE)
HEIR = ("select 1 from work.standby_beat where role = %(role)s and digest = %(digest)s and task = %(task)s "
        f"and live_at > clock_timestamp() - interval '{ALONE_S} seconds'")
# what the process that gave this successor the role recorded ({state: yielded, from, heir}), the newest in the hour
YIELDED = (f"select payload::text from log.event where type = '{RELOAD}' and tenant_id is null "
           "and occurred_at > now() - interval '1 hour' and payload->>'state' = 'yielded' and payload->>'role' = %(role)s "
           "and payload->>'digest' = %(digest)s and payload->>'heir' = %(task)s order by occurred_at desc limit 1")


class Gate:
    """Whether this process's image is the live one of its role. scope() gives a database (rows(sql, params))."""

    def __init__(self, scope, role, digest, tenant=config_data.TENANT, task=None, strict=False, clock=time.monotonic,
                 reloaded=None, intask=False):
        self.scope, self.role, self.digest, self.tenant, self.strict = scope, role, digest, tenant, strict
        # IN-TASK-STANDBY: a successor inside the ECS task (and whether its first beat was said, whether the supervisor
        # told it to adopt); gone: this process gave its role to its successor and never takes work again
        self.intask, self.up, self.told_adopt, self.gone = intask, False, lambda: bool(TOLD), False
        self.key, self.task = KEYS[role], task or socket.gethostname()
        self.pointer, self.version, self.live, self.retired = '', None, None, False  # live None: not read yet
        self.turned, self.lock = threading.Event(), threading.Lock()  # turned is set while live
        self.clock, self.swapped = clock, None  # IMAGE-SWAP-TIGHTEN: (version, notify_s, turned at) until working()
        self.worked = threading.Event()  # IMAGE-SWAP-SERVICE-READY: clear from a swap until its first work is recorded
        self.worked.set()
        self.armed, self.exit = False, os._exit  # SWAP-DRILL: a successor a drill names ends as it turns live (arm())
        # SUCCESSOR-LOST: the bundle this process covers the role of (lost(), cover()), since when, and what it has heard
        self.covering, self.covered_at, self.lost_seen, self.covers = None, None, {}, threading.Lock()
        self.named, self.cover_gap = None, None  # COVER-GAP: ((pointer, version), when it was written, on this clock)
        self.boot = {}  # BOOT-PARTS: {boot_s, boot_code_s, boot_entry_s} of a process started under its pointer
        self.samples = []  # SWAP-SECOND: what the database did while this process covered
        self.spare_said = None  # RESERVE-NO-DB: how its task's reserve stood when this successor last said it
        self.beaten = None  # IMAGE-SWAP-FAILOVER: when (clock) the last live beat was sent
        self.beat_at, self.beat_by, self.beat_found = None, None, []  # SWAP-TAIL-CUT: the process's last beat, and whose
        self.warm = None  # SWAP-TAIL-CUT: the standby's warm-up (Warm), for the swap's record
        self.leaving = False  # IMAGE-SWAP-FAILOVER: set by handback(): a standby that is stopping beats no more
        # IMAGE-SWAP-RELOAD: what the reload that started this process said (code_bundle.reloaded; None: any other start),
        # whether its first work is recorded and when its handover was last tried (back()); the work in flight by name
        # (engaged()) and whether a reload holds the gate while it execs
        self.reloaded, self.told, self.tried, self.backing = reloaded, False, None, threading.Lock()
        self.flying, self.reloading = {}, False
        self.reads = 0  # RELOAD-WITHOUT-STANDBY: the reads of the pointer (each tower_config notification is one): Order's wake

    def active(self):
        """True while this image may take work. Not read yet (a failed first read) reads again: until one read
        succeeds the process stands by, so an image never works on a guess."""
        if self.live is None:
            self.refresh()
        return (self.live is True or self.covering is not None) and not self.gone  # SUCCESSOR-LOST: or it covers

    def wait(self, timeout_s):
        """A standby's idle wait: until this image turns live (at once) or the timeout."""
        return self.turned.wait(timeout_s)

    def after_work(self, check):
        """IMAGE-SWAP-SERVICE-READY: check (active or sole) for a thread woken with the swap: until the swap's first work is
        recorded it waits for it (FIRST_WORK_S at most), so the role's first work runs before its housekeeping.
        COVER-NO-HOUSEKEEPING: and False while this process covers the role of a lost successor (SUCCESSOR-LOST): it
        keeps the role's own work until the bundle's new process is live, a few seconds, and its looks (the autodeploy's,
        the prewarm's) wait for that: the drill of #618 (13/11 01:11 UTC) found the database on its CPU with six simple
        statements of about 250 ms each while the new service process made its first dispatch (1.29 s, 0.09 s before),
        one of them the prewarm's read of the pushes, which only the covering process could run then (the new one's
        looks wait for its first work)."""
        def checked():
            self.worked.wait(FIRST_WORK_S)
            return check() and self.covering is None
        return checked

    def sharing(self):
        """IMAGE-PREWARM-C: an ECS task (not strict) the pointer names: the reconciliation's, live beside the promoted
        standby of the same digest until handover()."""
        return not self.strict and bool(self.pointer) and self.pointer == self.digest

    def sole(self):
        """IMAGE-PREWARM-C: active() and not sharing the role: the duties only one live service may run (the prewarm).
        IN-TASK-STANDBY: nor a promoted successor before it adopted the role: a Spot standby of the bundle may be live too.
        PREWARM-ONE-PAIR: a promoted standby (strict: live only while the pointer names it) reads the pointer here, not
        when its listener gets to it: the handover that empties the pointer notifies the looks too, and a look that ran
        before the listener was a second sole service (live 11/11: two pairs started for one bundle). An ECS task
        reads nothing more: without a pointer it is the one that stays."""
        if self.strict and self.live is True:
            self.refresh()
        return self.active() and not self.sharing() and not (self.intask and self.strict)

    def release(self, digest, by, ident, why, scope=None, sql=EMPTY, keys=None, **more):
        """The role's pointer (DEPLOY-CANARY: or `keys`, both roles') emptied only if it still names digest (EMPTY's
        compare-and-swap; sql LEAVE: the handback's; ALONE: a reloaded task's handover, IMAGE-SWAP-RELOAD)
        and platform.deploy.image_retired {role, digest, task, by, ...}, one statement, on scope or the gate's; answers
        the keys emptied, or nothing when the pointer had moved. IMAGE-SWAP-FAILOVER: of those that may try at once (the
        handover, the handback, the failover of each ECS task, the autodeploy's revert) one wins and its event says who."""
        params = empty(self.tenant, keys or [self.key], digest, f'tower-{self.role}', {
            'role': self.role, 'digest': digest, 'task': self.task, 'by': by, **more},
            f'platform.deploy.image_retired:{self.role}:{digest}:{ident}', why)
        with (scope or self.scope)() as db:
            return db.rows(sql, {**params, 'role': self.role, 'task': self.task, 'was': (self.reloaded or {}).get('from')})

    def handback(self, scope=None):
        """IMAGE-SWAP-FAILOVER: a promoted standby (strict) that is being stopped (SIGTERM: Spot's warning, a StopTask)
        gives its role back before it stops taking work: from now it beats no more, and one statement (LEAVE) withdraws
        its beat and empties the pointer if it still names this digest (by: handback), so the ECS task standing by works
        at once and not after deploy.live_stale_s. scope: a connection of its own with short timeouts (on_term). Answers
        whether the pointer was handed back; never raises. An ECS task (not strict) has nothing to hand back."""
        if not self.strict:
            return None
        self.leaving = True
        try:
            done = self.release(self.digest, 'handback', f'handback:{self.task}',
                                f'IMAGE-SWAP-FAILOVER: the promoted standby {self.task} of {self.digest} is stopping',
                                scope=scope, sql=LEAVE)
        except Exception:  # noqa: BLE001 - the stop goes on; the ECS task takes the role after deploy.live_stale_s
            LOG.exception('live image: the handback of %s %s failed; the watchdog takes it', self.role, self.digest)
            return False
        LOG.info('live image: %s %s is stopping: %s', self.role, self.digest,
                 'its pointer is handed back, the ECS task takes the role' if done else 'the pointer does not name it')
        return bool(done)

    def dismissed(self, scope=None):
        """STANDBY-GRACE: whether the engine itself stopped this standby (DISMISSED). True too when it cannot be read: a
        standby that cannot reach the database cannot beat either, and leaves as before."""
        try:
            with (scope or self.scope)() as db:
                found = db.rows(DISMISSED, {'role': self.role, 'digest': self.digest})
            return bool(found) and found[0][0] == 'stopped'
        except Exception:  # noqa: BLE001
            LOG.exception('live image: could not read whether %s %s was dismissed; it leaves', self.role, self.digest)
            return True

    def handover(self):
        """IMAGE-PREWARM-C: the reconciled ECS task takes the role from the promoted standby: the pointer is emptied if it
        still names this digest; the strict standby then stands by (no pointer is not live for it) and this task, not
        strict, goes on. Answers False only when the write failed (the caller tries again on its next beat).
        IMAGE-SWAP-RELOAD: a reloaded task's is ALONE (payload reloaded: true): it also answers False, to be tried again,
        while another ECS task of the role still stands by on the code this one left."""
        if not self.sharing():
            return True
        alone = self.reloaded is not None
        try:
            done = self.release(self.digest, 'handover', self.version,
                                f'IMAGE-PREWARM-C: the ECS task {self.task} of {self.digest} took the role over',
                                **({'sql': ALONE, 'reloaded': True} if alone else {}))
        except Exception:  # noqa: BLE001 - the standby keeps working meanwhile; the next beat tries again
            LOG.exception('live image: the handover of %s %s failed', self.role, self.digest)
            return False
        LOG.info('live image: %s %s handed over from the promoted standby (%s)', self.role, self.digest,
                 'pointer emptied' if done else 'the pointer had moved already' if not alone else
                 f"not yet: the pointer moved, or another ECS task still stands by on {self.reloaded.get('from')}")
        return bool(done) or not alone

    def back(self, db=None):
        """IMAGE-SWAP-RELOAD: after each good pass of a reloaded ECS task (the service's tick, a runner slot's TAKE), a
        no-op for any other process. Once, at its first: platform.deploy.image_reload {state: reloaded, reload_s: the
        pointer's write to now, boot_s: the claim to now} (tried again if the write fails). Then, while the pointer still
        names this digest, the handover, LIVE_BEAT_S apart at most: the role is the ECS task's again and the promoted
        standby stands by. One caller at a time (the runner's slots); never raises."""
        said = self.reloaded
        if said is None and not (self.intask and self.strict and self.told_adopt()):
            return
        if (said is not None and self.told and not self.sharing()) or not self.backing.acquire(blocking=False):
            return
        try:
            if said is None:  # IN-TASK-STANDBY: a successor told to adopt is from here on a reloaded ECS task
                if not self.adopt(db):
                    return
                said = self.reloaded
            if not self.told:
                self.sent(RELOAD_SAY, {
                    'id': f"{RELOAD}:{self.role}:{self.digest}:{said.get('turn')}:reloaded", 'producer': f'tower-{self.role}',
                    'role': self.role, 'wrote_at': said.get('wrote_at'), 'started_at': said.get('at'),
                    'payload': json.dumps({**{name: value for name, value in said.items() if name not in ('at', 'key')},
                                           'role': self.role, 'digest': self.digest, 'task': self.task,
                                           'state': 'reloaded'})}, db)
                self.told = True
                LOG.info('live image: %s %s was reloaded in place from %s and works', self.role, self.digest, said.get('from'))
            if self.sharing() and (self.tried is None or self.clock() - self.tried >= LIVE_BEAT_S):
                self.tried = self.clock()
                self.handover()
        except Exception:  # noqa: BLE001 - the next pass says it again
            LOG.exception('live image: could not record the reload of %s %s', self.role, self.digest)
        finally:
            self.backing.release()

    def adopt(self, db=None):
        """IN-TASK-STANDBY: a successor the supervisor told to adopt (the process that had the role gave it away: its
        {state: yielded} names this one) becomes what a reloaded ECS task is: not strict (no pointer is live for it), and
        `reloaded` {from: the code the yielder ran, turn: intask}, so back() records {state: reloaded} and hands the
        pointer over by ALONE's compare-and-swap. A no-op for any other process and once adopted; a read that fails or
        finds no yield yet is tried again on the next pass (the caller's guard), and meanwhile the pointer still names it."""
        if not (self.intask and self.strict and self.told_adopt()):
            return False
        found = self.sent(YIELDED, {'role': self.role, 'digest': self.digest, 'task': self.task}, db)
        if not found:
            return False
        said = json.loads(found[0][0])
        self.reloaded, self.strict = {'from': said.get('from'), 'turn': INTASK, 'intask': True, 'by': said.get('task')}, False
        LOG.info('live image: %s %s adopts the role of its task: %s gave it away', self.role, self.digest, said.get('task'))
        return True

    def give(self, digest, name, db=None, tell=None):
        """IN-TASK-STANDBY: this process, standing by under a swap whose canary is green, gives the role for good to its
        task's successor `name` of that bundle: {state: yielded, from: this code, heir} is recorded (the successor adopts
        on it), this process never takes work again (gone: it neither beats nor watches) and the supervisor is told. What
        it has in flight ends by itself (finish(); the runner's slots end after their runs)."""
        self.sent(RELOAD_SAY, {'id': f'{RELOAD}:{self.role}:{digest}:yielded:{self.task}', 'producer': f'tower-{self.role}',
                               'role': self.role, 'wrote_at': None, 'started_at': None, 'payload': json.dumps(
                                   {'role': self.role, 'digest': digest, 'task': self.task, 'state': 'yielded',
                                    'from': self.digest, 'heir': name})}, db)
        with self.lock:
            self.gone, self.live = True, False
        self.turned.clear()
        self.worked.set()
        (tell or supervisor.give)(digest)
        LOG.info('live image: %s %s gave its role to its successor %s and ends after what it has in flight', self.role,
                 self.digest, name)

    @contextlib.contextmanager
    def engaged(self, name):
        """IMAGE-SWAP-RELOAD: work this process finishes before it may reload itself (a runner slot's pass, its run
        included; a look of the autodeploy or the prewarm); yields whether the work may start. It is counted before the
        answer is read, and a reload holds the gate (reloading) before it counts (busy()): of a thread taking work and a
        reload about to exec, one always backs off."""
        with self.lock:
            self.flying[name] = self.flying.get(name, 0) + 1
        try:
            yield not self.reloading
        finally:
            with self.lock:
                self.flying[name] -= 1

    def busy(self):
        """IMAGE-SWAP-RELOAD: the names of the work in flight (engaged())."""
        with self.lock:
            return sorted(name for name, count in self.flying.items() if count)

    def refresh(self, scope=None):
        """Read the pointer (on the tower_config event); answers whether this image is live. A failed read or an
        invalid value keeps what was there. scope: another scope for this read (SWAP-CPU: the first one)."""
        self.reads += 1
        try:
            with (scope or self.scope)() as db:
                found = db.rows(READ, {'tenant': self.tenant, 'key': self.key})
            value = config_data.validate(self.key, json.loads(found[0][0])) if found else ''
        except ValueError as error:
            LOG.warning('live image: config.invalid: %s; keeping the previous pointer', error)
            return self.live is True
        except Exception:  # noqa: BLE001 - a lost read keeps the last state; the next event reads again
            LOG.exception('live image: could not read %s', self.key)
            return self.live is True
        pointer, version = value.strip(), int(found[0][1]) if found else None
        seen_s = float(found[0][2]) if found and len(found[0]) > 2 and found[0][2] is not None else None
        live = pointer == self.digest if self.strict else (not pointer or pointer == self.digest)  # B2: strict
        live = live and not self.gone  # IN-TASK-STANDBY: a process that gave its role away never turns live again
        with self.lock:
            was, self.pointer, self.version, self.live = self.live, pointer, version, live
            if pointer and pointer != self.digest and (self.named or (None,))[0] != (pointer, version):
                # COVER-GAP: when, on this process's clock, the pointer was given to another bundle (this read's time
                # less the seconds since its write): what a cover's gap is counted from (lost())
                self.named = ((pointer, version), self.clock() - (seen_s or 0.0))
        if was is False and live and pointer and self.armed:
            # SWAP-DRILL: an armed successor ends here, as it turns live, with no handback and no word: the standby
            # lost at the instant of the swap, induced (POST /v1/deploy/drill names its bundle and its role)
            LOG.warning('live image: SWAP-DRILL: %s %s ends as it turns live', self.role, self.digest)
            self.exit(DRILL_EXIT)
        # SUCCESSOR-LOST: a successor that starts under a pointer that already names it (the one the supervisor started
        # after the swap's own ended) is that swap's process, late: its first work is recorded as any swap's, with the
        # seconds since the pointer's write (LIVE's own id keeps it one per role, bundle and version)
        late = was is None and live and pointer and self.strict and self.intask
        if late:  # BOOT-PARTS: where this process's boot went, for that swap's record
            age, went = code_bundle.age_s(), number(os.environ.get(code_bundle.WENT))
            if went is not None and age is not None:
                # RESERVE-NO-DB: a reserve told to go: its boot is what came after the word (held_s: how long it had
                # waited, loaded, when the word came); the interpreter and the bundle were paid before anyone waited
                self.boot = {'boot_s': round(max(0.0, age - went), 3), 'held_s': went, 'reserve': True}
            else:
                self.boot = {name: value for name, value in (
                    ('boot_s', age), ('boot_code_s', number(os.environ.get(code_bundle.BOOT_CODE))),
                    ('boot_entry_s', number(os.environ.get(code_bundle.BOOT_ENTRY)))) if value is not None}
        if (was is False or late) and live and pointer:  # IMAGE-SWAP-TIGHTEN: timed now, recorded when the role takes work
            self.swapped = (version, seen_s, self.clock())
            self.worked.clear()
        if live:
            self.turned.set()
        else:
            self.turned.clear()
            self.worked.set()  # IMAGE-SWAP-SERVICE-READY: no work to wait for while not live
        if was is False and live and pointer:
            LOG.info('live image: %s %s is live (pointer version %s, %s s after its write)', self.role, self.digest,
                     version, seen_s)
        elif was is True and not live:
            self.retired = True
            LOG.info('live image: %s %s is no longer live (pointer %s): no new work', self.role, self.digest, pointer)
        elif was is None:
            LOG.info('live image: %s %s starts %s (pointer %r)', self.role, self.digest, 'live' if live else 'standing by',
                     pointer)
        return live

    def sent(self, sql, params, db=None):
        """One statement on db, or on the gate's scope."""
        if db is not None:
            return db.rows(sql, params)
        with self.scope() as found:
            return found.rows(sql, params)

    def beat(self, db=None):
        """IMAGE-SWAP-TIGHTEN: this standby's beat in work.standby_beat (migration 0014), on db or the gate's scope; it is
        the standby pass's database round trip, so a failure raises to the caller like the `select 1` it replaces.
        IMAGE-SWAP-FAILOVER: an ECS task's (not strict) is, in the same statement, its watch over the image the pointer
        names (WATCH, watched()); a prewarm standby (strict) only beats: no pointer would not make it live; one that
        is stopping (handback()) beats no more."""
        if self.leaving or self.gone:  # IN-TASK-STANDBY: nor does a process that gave its role away (it watches nothing)
            return []
        with self.lock:  # SWAP-TAIL-CUT: one beat a pass for the process; the same connection always beats (the loop's)
            now = self.clock()
            if db is not None and self.beat_by is not None and db is not self.beat_by and now - self.beat_at < BEAT_MIN_S:
                return self.beat_found
            self.beat_at, self.beat_by = now, db
        params = {'role': self.role, 'digest': self.digest, 'task': self.task}
        if self.strict:
            found = self.sent(BEAT, params, db)
            if self.intask and not self.up:  # IN-TASK-STANDBY: its first beat is said once, and wakes the looks
                self.sent(UP, {'id': f'{SUCCESSOR}:{self.role}:{self.digest}:{self.task}:up:{BORN}', 'producer': f'tower-{self.role}',
                               'role': self.role, 'payload': json.dumps({**params, 'state': 'up'})}, db)
                self.up = True
            if self.intask:
                self.spared(db)  # RESERVE-NO-DB: how its task's reserve stands, said when it changes
        else:
            found = self.sent(WATCH, {**params, 'tenant': self.tenant, 'key': self.key}, db)
            self.watched(found)
        self.beat_found = found
        return found

    def spared(self, db=None, stands=supervisor.reserved, measure=supervisor.memory):
        """RESERVE-NO-DB: a successor says in the log how its task's reserve stands, once each time that changes
        (platform.deploy.successor {state: reserve, reserve: held | no room | off | not its code}), with the task's
        memory and the reserve's own measured then (supervisor.memory: task_mb, task_peak_mb, task_limit_mb, reserve_mb,
        reserve_rss_mb): the reserve itself has no connection to say it with. `held` is said when the reserve said it
        is ready (its memory is then what it holds while it waits); `waiting` is not said. Never raises: a measure."""
        try:
            word, ready = stands()
            if word in (None, 'waiting') or (word == 'held' and ready != self.digest) or word == self.spare_said:
                return None
            said = {'role': self.role, 'digest': self.digest, 'task': self.task, 'state': 'reserve', **measure(),
                    'reserve': word}
            self.sent(UP, {'id': f'{SUCCESSOR}:{self.role}:{self.digest}:{self.task}:reserve:{BORN}:{word}',
                           'producer': f'tower-{self.role}', 'role': self.role, 'payload': json.dumps(said)}, db)
            self.spare_said = word
            return said
        except Exception:  # noqa: BLE001
            LOG.exception('live image: the %s successor did not say how its reserve stands', self.role)
            return None

    def watched(self, found):
        """IMAGE-SWAP-FAILOVER: what WATCH answered: (the role's pointer, the seconds since the pointed digest's newest
        live beat or the pointer's write, deploy.live_stale_s as stored). A pointer this gate has not read (a lost
        notification) is read now; one whose image has had no live beat for longer than deploy.live_stale_s is failed over."""
        pointer, stale_s, stored = (str(found[0][0] or '').strip(), found[0][1], found[0][2]) if found else ('', None, None)
        seen = found[0][3] if found and len(found[0]) > 3 else None  # DEPLOY-CANARY: the swap's canary job, as WATCH read it
        if pointer != self.pointer:
            self.refresh()
        elif pointer and pointer != self.digest and stale_s is not None and float(stale_s) > stale_limit(stored):
            self.failover(pointer, float(stale_s), **({'lost': True} if self.covering == pointer else {}))
        elif pointer and pointer != self.digest and seen:
            self.canaried(pointer, json.loads(seen))

    def canaried(self, digest, seen):
        """DEPLOY-CANARY: the image the pointer names beats, and the canary job of its swap says whether it works. One
        that ended and not succeeded, or is still open past deploy.canary_limit_s (canary.failed), empties both roles'
        pointers if they still name that digest (by: canary) and this ECS task, not strict, works at once on the code it
        has. A failed write raises to the standby pass, which tries again."""
        limit_s = canary.limit_of(None if seen.get('limit') is None else json.dumps(seen['limit']))
        state, age_s = seen.get('state'), float(seen.get('age_s') or 0)
        if not canary.failed(state, age_s, limit_s):
            return
        done = self.release(digest, 'canary', f'canary:{self.version}',
                            f'DEPLOY-CANARY: the canary of {digest} is {state} after {age_s:.1f} s: the ECS task {self.task} '
                            'takes the role', keys=list(KEYS.values()), canary=seen.get('id'), state=state, age_s=round(age_s, 3))
        LOG.warning('live image: the canary of %s %s is %s after %.1f s (limit %g s): %s takes the role (%s)', self.role,
                    digest, state, age_s, limit_s, self.task, 'pointers emptied' if done else 'the pointers had moved already')
        self.refresh()
        self.refuse(digest, f'the canary of its swap is {state} after {age_s:.1f} s')

    def refuse(self, digest, why, db=None):
        """DEPLOY-CANARY: a bundle whose canary is red is not loaded again: platform.deploy.image_reload {state: failed,
        why}, the record a reload that failed leaves (Reload.fail), once per role and digest. Every reload's look reads it
        (Reload.plan: never reloaded in that role) and so does the boot of a task ECS starts (code_bundle.newer:
        deploy.live_code names a bundle a reload failed on, so the task keeps its task definition's code). Never raises:
        the role is already back."""
        try:
            self.sent(RELOAD_SAY, {'id': f'{RELOAD}:{self.role}:{digest}:failed:canary', 'producer': f'tower-{self.role}',
                                   'role': self.role, 'wrote_at': None, 'started_at': None, 'payload': json.dumps(
                                       {'role': self.role, 'digest': digest, 'task': self.task, 'state': 'failed', 'why': why})}, db)
        except Exception:  # noqa: BLE001
            LOG.exception('live image: could not record that %s is not to be loaded', digest)

    def lost(self, ended=supervisor.lost):
        """SUCCESSOR-LOST: the supervisor says a successor of this task ended unasked (SIGUSR2; orphaned()). When the
        pointer names a bundle that is not this process's and one more successor of that bundle ended, the process the
        swap promoted is gone: this one, the role's process standing by on the code it has, COVERS the role from now
        (active() is true; the pointer is not touched) and does not leave the role with no process until the supervisor's
        new successor is up (5 to 8 s of boot) or deploy.live_stale_s passes (10 s). cover() ends it, and says the gap
        (COVER-GAP: gap_s, from the pointer's write to this instant: how long the role had no process). Not a successor
        standing by (strict), not a process that gave its role away, not one that is live. Answers whether it covers."""
        counts, seen = ended(), self.lost_seen
        self.lost_seen = {**seen, **counts}
        # LOST-BEAT-WITHDRAWN: the beat of a successor that ended goes with it, now: the landing swaps onto fresh beats
        # (deploy.standby_fresh_s, 3 s), and one that came inside that window swapped onto a process already gone. Its
        # supervisor's new one beats when it is up. Not a successor's own doing (strict), and never raises
        if not self.strict and not self.gone:
            for sha in [each for each, count in counts.items() if count > seen.get(each, 0)]:
                try:
                    self.sent(WITHDRAW, {'role': self.role, 'digest': sha, 'task': heir_of(self.task, sha)})
                except Exception:  # noqa: BLE001 - the beat then ages out, as before
                    LOG.exception('live image: the beat of the successor on %s that ended was not withdrawn', sha)
        pointer = self.pointer
        if self.strict or self.gone or self.live is not False or not pointer or pointer == self.digest:
            return False
        if counts.get(pointer, 0) <= seen.get(pointer, 0) or self.covering is not None:
            return False
        with self.lock:
            self.covering, self.covered_at, self.samples = pointer, self.clock(), []
            # COVER-GAP: how long the role had no process: from the pointer's write to this instant
            named = self.named if self.named and self.named[0][0] == pointer else None
            self.cover_gap = None if named is None else round(self.covered_at - named[1], 3)
        self.turned.set()  # the standby's wait ends now: its next pass is a live one
        LOG.warning('live image: %s %s covers the role: the successor on %s that the pointer names ended', self.role,
                    self.digest, pointer)
        return True

    def cover(self, db=None):
        """SUCCESSOR-LOST: the look of a process that covers, once a live pass (the standby's own beat and watch, WATCH):
        the cover ends when the pointed bundle beats live again (`live`: the supervisor's new successor of it is up, and
        this process stands by as before), when the pointer moved (`moved`), or when the bundle stayed with no live beat
        past deploy.live_stale_s and the watch failed it over (`failover`, lost: true: this process keeps the role, as
        before the cover existed). The end is said once: platform.deploy.successor {state: covered, covered_s, end}.
        None while it covers or when it does not."""
        covering = self.covering
        if covering is None or not self.covers.acquire(blocking=False):
            return None
        try:
            found = self.beat(db)
            covered_s = self.clock() - self.covered_at
            stale_s = found[0][1] if found else None
            if self.pointer != covering:
                end = 'failover' if self.live is True and not self.pointer else 'moved'
            elif stale_s is not None and float(stale_s) < covered_s - COVER_MARGIN_S:
                end = 'live'
            else:
                self.sample(db, covered_s)  # SWAP-SECOND: what the database does while the role's new code is not at work
                return None
            with self.lock:
                self.covering = None
            if self.live is not True:
                self.turned.clear()
            said = {'role': self.role, 'digest': covering, 'task': self.task, 'state': 'covered', 'by': self.digest,
                    'covered_s': round(covered_s, 3), 'end': end,
                    **({} if self.cover_gap is None else {'gap_s': self.cover_gap}),  # COVER-GAP
                    **({'samples': self.samples} if self.samples else {})}  # SWAP-SECOND
            LOG.warning('live image: %s %s covered the role of %s for %.1f s: %s', self.role, self.digest, covering,
                        covered_s, end)
            try:
                self.sent(HOLDS, {'id': f'{SUCCESSOR}:{self.role}:{covering}:{self.task}:covered:{time.time_ns()}',
                                  'producer': f'tower-{self.role}', 'role': self.role, 'payload': json.dumps(said)}, db)
            except Exception:  # noqa: BLE001 - the cover is over whatever the log says
                LOG.exception('live image: the cover of %s was not recorded', covering)
            return said
        finally:
            self.covers.release()

    def sample(self, db, covered_s):
        """SWAP-SECOND: while it covers, the process that covers (connected already) says what the database does: one
        reading of pg_stat_activity (BUSY: the statements of the last second, their waits, the sessions active) a pass,
        SAMPLES at most, said with the cover's end. The covered swap's own record reads it once, at its end; this is the
        second between the word and the new code's first work. Never raises."""
        if len(self.samples) >= SAMPLES:
            return None
        try:
            if db is not None and hasattr(db, 'rows'):
                found = busy(db, 1.0)
            else:
                with self.scope() as own:
                    found = busy(own, 1.0)
        except Exception:  # noqa: BLE001 - a measure
            found = {}
        if found:
            self.samples.append({'at_s': round(covered_s, 3), **found})
        return found

    def failover(self, digest, stale_s, **more):
        """IMAGE-SWAP-FAILOVER: the image the pointer names has no live beat (its process died with no handback, or its
        loop hangs): the pointer is emptied if it still names that digest, and this ECS task, not strict, works at once:
        the pointer is read here, not on the notification. A failed write raises to the standby pass, which tries again."""
        done = self.release(digest, 'failover', f'failover:{self.version}',
                            f'IMAGE-SWAP-FAILOVER: no live beat of {digest} for {stale_s:.1f} s: the ECS task {self.task} '
                            'takes the role', stale_s=round(stale_s, 3), **more)
        LOG.warning('live image: %s %s had no live beat for %.1f s: %s takes the role (%s)', self.role, digest, stale_s,
                    self.task, 'pointer emptied' if done else 'the pointer had moved already')
        self.refresh()

    def arm(self, db):
        """SWAP-DRILL: whether a drill asked, since this process was born, for the successor of this bundle and role to end
        as it turns live (platform.deploy.drill; POST /v1/deploy/drill). Read when the swap's record is rehearsed (the
        first warm-up, each readiness notification), never on the swap's own clock; a successor only (strict, in its
        task). A process started again after the drill is not armed: the drill is older than it. Never raises."""
        if not (self.strict and self.intask):
            return False
        try:
            self.armed = bool(self.sent(DRILL, {'role': self.role, 'digest': self.digest, 'born': BORN}, db))
        except Exception:  # noqa: BLE001 - a drill that cannot be read is no drill
            LOG.exception('live image: the drill of %s %s was not read', self.role, self.digest)
        return self.armed

    def pointed(self):
        """IMAGE-SWAP-FAILOVER: live because the pointer names this digest (the promoted standby; the reconciled ECS task
        while sharing): the processes that owe the role a live beat. Live with no pointer is today's path: no beat."""
        return self.live is True and bool(self.pointer) and self.pointer == self.digest

    def pace(self, every_s):
        """IMAGE-SWAP-FAILOVER: how often the keeper of a run wakes: every_s (its lease renewal), or LIVE_BEAT_S if sooner
        while pointed(), so the task keeps its live beat when every slot is busy with a long run."""
        return min(every_s, LIVE_BEAT_S) if self.pointed() else every_s

    def live_beat(self, db=None):
        """IMAGE-SWAP-FAILOVER: this process's live beat (LIVE_BEAT) while pointed(), LIVE_BEAT_S apart at most whoever
        calls (the service's loop after a good tick; each runner slot's TAKE and keeper); answers whether it was sent.
        Never raises: a beat that fails is a beat that is missing, which is what the watchdog reads."""
        if self.leaving or not self.pointed():
            return False
        now = self.clock()
        with self.lock:
            if self.beaten is not None and now - self.beaten < LIVE_BEAT_S:
                return False
            self.beaten = now
        try:
            self.sent(LIVE_BEAT, {'role': self.role, 'digest': self.digest, 'task': self.task}, db)
        except Exception:  # noqa: BLE001 - no beat: past deploy.live_stale_s the ECS task takes the role
            LOG.exception('live image: the live beat of %s %s failed', self.role, self.digest)
            return False
        return True

    def first_work(self):
        """IMAGE-SWAP-TICK: the instant of the role's first work after a swap, when it comes before the record: the
        service's first committed claim of a pass that goes on claiming. work_s ends here; working() records it once the
        pass is done. No statement; a no-op otherwise."""
        with self.lock:
            if self.swapped is not None and len(self.swapped) == 3:
                self.swapped = (*self.swapped, self.clock())

    def working(self, began=None, db=None, **parts):
        """IMAGE-SWAP-TIGHTEN: the role has really taken work: platform.deploy.image_live once per swap, swap_s = notify_s
        (the pointer's write to the read, database clock) + work_s (that read to the first work, this process's clock).
        IMAGE-SWAP-TICK, what the first work is: the runner's first TAKE answered (a run taken, or none to take); the
        service's first claim committed (first_work: a run.started in the log, a container run takeable), or, when its
        first pass had nothing to claim, the end of that pass (reap and dispatch committed). work_s in parts, which add up
        to it: wake_s (the read to the start of the pass, at `began` on this clock: the wait's wake, and launch_s when the
        launch was still to do), connect_s (a usable connection) and the runner's take_s, or the service's reap_s and
        dispatch_s (workflows.tick); pass_s and jobs say what the service's whole first pass was. A no-op otherwise.
        SWAP-RECORD-WARM: db is the connection the first work ran on (the service's loop's, the runner's slot's): the
        record is written on it, the one its standby rehearsed the record on (Warm.step), and not on the gate's scope
        (the service's is the pool: a backend that never wrote to log.event; live 12/11, 365 ms of a pass)."""
        with self.lock:
            swapped, self.swapped = self.swapped, None
        if swapped is None:
            return None
        version, notify_s, turned, *first = swapped
        work_s = (first[0] if first else self.clock()) - turned
        if began is not None:
            parts = {'wake_s': began - turned, **parts}
        self.worked.set()  # IMAGE-SWAP-SERVICE-READY: the looks woken with the swap go on now
        timed = {'notify_s': None if notify_s is None else round(notify_s, 3), 'work_s': round(work_s, 3),
                 'swap_s': None if notify_s is None else round(notify_s + work_s, 3),
                 **{name: round(value, 3) for name, value in parts.items() if value is not None}}
        if self.warm is not None:
            timed.update(self.warm.said())  # SWAP-TAIL-CUT: what the standby's warm-up of this first work cost, cold and warm
        timed.update(self.boot)  # BOOT-PARTS: of a successor started after the pointer named it
        if self.boot:  # SWAP-CPU: and what the task's CPU quota held back from the word to this first work
            timed.update(cpu_since(os.environ.get(code_bundle.CPU_AT)))
        if self.boot:  # TASK-POOLER: and how that process's connections came (reused: no login on the role's clock)
            timed.update(database.pool_said())
        took = work_s if timed['swap_s'] is None else timed['swap_s']
        try:
            with (self.scope() if db is None else contextlib.nullcontext(db)) as db:
                if took >= EVIDENCE_S:  # SWAP-EVIDENCE-WHEN-SLOW: a swap inside its second is not asked what delayed it
                    timed.update(busy(db, took + 1.0))  # SWAP-TAIL-EVIDENCE: after the measure, before the record
                db.rows(LIVE, {'id': f'platform.deploy.image_live:{self.role}:{self.digest}:{version}',
                               'producer': f'tower-{self.role}', 'role': self.role, 'digest': self.digest,
                               'task': self.task, 'tenant': self.tenant, 'key': self.key, 'version': version,
                               'parts': json.dumps(timed)})
        except Exception:  # noqa: BLE001 - the measure is a courtesy; the swap already happened
            LOG.exception('live image: could not record platform.deploy.image_live')
        return timed


def sweep(db):
    """SWAP-TAIL-CUT: the beats older than a day go; the live service's hourly pass. Never raises."""
    try:
        db.rows(SWEEP_OLD)
    except Exception:  # noqa: BLE001
        LOG.exception('live image: the old standby beats were not swept')


WARM_S = 60.0


class Warm:
    """SWAP-TAIL-CUT: a prewarm standby (strict) runs the statements of its role's first work after a swap on the
    connection that first work will use, in a transaction that is rolled back, when it starts and WARM_S apart. The first
    call of a function on a backend compiles and plans it and loads what it reads into the backend's caches: locally 2 ms
    against 0.2 ms; on the db.t4g.micro the promoted service's first reap took 0.32 to 1.0 s and its first roll_limits
    0.28 s (the evidence of #518's swap), which is most of the swap's tail. Rolled back, nothing is reaped, rolled or
    taken by a standby: only its backend is warm. step(db): db is the pass's kept connection (container.Reconnecting);
    one that has no psycopg connection behind it (a test's stand-in) is left alone. Never raises.
    READY-REHEARSAL: also on the pass after the gate's listener read the pointer again (Gate.reads): the port notifies
    when the delivery at the front finds its successors ready (port.READY_ROLES), a second or so before the landing, so
    the backends the swap wakes are not cold. said(): for the swap's
    record, warm_first_s (the cold call) and warm_last_s (the newest), the largest of the process's connections.
    READY-BEFORE-LANDING: an in-task successor says platform.deploy.successor {state: warm, warm_s} after its first
    warm-up, once: its first beat (`up`) comes while it still starts, and a landing 6 to 10 s after it found the
    database busy with that start (live 11/11, #539: swap 1.25 s, warm_first_s 2.3 s, the pointer's read 0.3 to 0.6 s
    late). The delivery at the front of the train waits for both roles' `warm` before it lands (merge_train.ready)."""

    def __init__(self, gate, statements, clock=time.monotonic, primed=None, job=None):
        self.gate, self.statements, self.clock, self.seen, self.lock = gate, statements, clock, {}, threading.Lock()
        # FIRST-JOB-REHEARSED: job(cursor) runs a job of no one through the role's whole path on this connection, inside
        # the warm-up's transaction (rehearsal.job: its own tenant, queue, executor and slot, nothing committed), when the
        # record is rehearsed: the first job after a swap paid every statement of its path for the first time on its
        # backend (live 12/11, nine swaps: the canary dispatched in 0.40 to 1.54 s and taken in 0.11 to 1.02 s, against
        # 0.03 to 0.10 s and 0.02 s on a warm engine). Its parts go to the swap's record (said: job_first_s, job_last_s)
        self.job = job
        # POOL-READY: what else the role must have ready before a swap (the service: its pool's connections opened, its
        # look's 7 days read), called once a process, after its first warm-up. READY-ONCE: not at a readiness signal:
        # that is a second or so before the landing, and what it did then (every pooled connection taken at once to be
        # pinged) was in the way of the pointer's read (live 12/11 10:57 UTC: the service read it 0.34 s after its
        # write, the runner 0.025 s). The signal's own read of the pointer already left the pool's newest connection warm
        self.primed, self.readied = primed, False
        self.told = False  # READY-BEFORE-LANDING: an in-task successor's {state: warm}, said once
        self.said_heard = self  # SWAP-MEASURE: the reading whose rehearsal was said last (self: none yet)
        gate.warm = self

    def step(self, db):
        if not self.gate.strict:
            return None
        mine = self.seen.setdefault(id(db), {})
        # READY-REHEARSAL: and again when the gate's listener read the pointer since this connection's last warm-up (a
        # notification: the delivery at the front asked whether its successors are ready, or a pointer was written)
        heard = getattr(self.gate, 'reads', None)
        if mine.get('at') is not None and self.clock() - mine['at'] < WARM_S and mine.get('heard') == heard:
            return None
        mine['at'], mine['heard'] = self.clock(), heard
        began, took, rehearsed = mine['at'], None, self  # rehearsed: the reading this pass rehearsed on (self: none)
        try:
            connection = getattr(getattr(db, 'ready', lambda: db)(), 'connection', None)
            if connection is None or not hasattr(connection, 'transaction'):
                return None
            with connection.transaction(force_rollback=True), connection.cursor() as cursor:
                for sql, params in self.statements:
                    cursor.execute(sql, params)
                    if cursor.description:
                        cursor.fetchall()
                took = self.clock() - began  # the role's statements; the record's rehearsal below is not in warm_first_s
                # SWAP-RECORD-WARM: the swap's record (LIVE) rehearsed in the same rolled-back transaction, on this
                # connection, which is the one that writes it (Gate.working(db=): the loop's, the slot's): when the
                # connection first warms and each time the gate's listener read the pointer since (READY-REHEARSAL:
                # the delivery at the front asked whether its successors are ready, a second or so before the landing),
                # never on the minute's cadence: an insert rolled back leaves a dead row. The record is written inside
                # the role's first pass after the swap and that pass, not the swap, paid a backend's first insert into
                # log.event: 0.4 to 0.6 s in nearly every landing of 12/11
                rehearse = mine.get('record', self) != heard
                if rehearse:
                    rehearsed = heard
                    mine['record'] = heard
                    gate = self.gate
                    arm = getattr(gate, 'arm', None)  # SWAP-DRILL: is this successor to end as it turns live
                    if arm is not None:
                        arm(Rows(cursor))
                    cursor.execute(REHEARSE, {
                        'id': f'platform.deploy.image_live:{gate.role}:{gate.digest}:rehearsal',
                        'producer': f'tower-{gate.role}', 'role': gate.role, 'digest': gate.digest, 'task': gate.task,
                        'tenant': gate.tenant, 'key': gate.key})
                    if self.job is not None:
                        at = self.clock()
                        try:
                            with connection.transaction():  # a savepoint: a step that fails undoes the job's, not the rest
                                self.job(cursor)
                        except Exception as error:  # noqa: BLE001 - a courtesy: the role's first job is then as cold as before
                            LOG.exception('live image: the %s standby did not rehearse a job', gate.role)
                            with self.lock:  # and the swap's record says why (job_error), where the log is not read
                                mine['job_error'] = f'{type(error).__name__}: {error}'[:200]
                        else:
                            with self.lock:
                                mine.setdefault('job_first', self.clock() - at)
                                mine['job_last'] = self.clock() - at
                                mine.pop('job_error', None)
        except Exception:  # noqa: BLE001 - a warm-up is a courtesy; the beat is the standby's health
            LOG.exception('live image: the warm-up of the %s standby failed', self.gate.role)
            if took is None:
                return None
        else:
            with self.lock:
                due, self.readied = self.primed is not None and not self.readied, True
            if due:
                try:
                    self.primed()
                except Exception:  # noqa: BLE001 - a courtesy too
                    LOG.exception('live image: what the %s standby readies besides its warm-up failed', self.gate.role)
        with self.lock:
            mine.setdefault('first', took)
            mine['last'] = took
            tell, self.told = not self.told and getattr(self.gate, 'intask', False) is True, True
            job = ({'job_s': round(mine['job_first'], 3)} if 'job_first' in mine else
                   {'job_error': mine['job_error']} if 'job_error' in mine else {})
        if rehearsed is not self and not tell:  # SWAP-MEASURE: a rehearsal after the first warm-up (that one says `warm`)
            self.say_rehearsed(rehearsed, db)
        if tell:  # READY-BEFORE-LANDING: said once a process, after its first warm-up
            try:
                gate = self.gate
                gate.sent(UP, {'id': f'{SUCCESSOR}:{gate.role}:{gate.digest}:{gate.task}:warm:{BORN}', 'producer': f'tower-{gate.role}',
                               'role': gate.role, 'payload': json.dumps({
                                   'role': gate.role, 'digest': gate.digest, 'task': gate.task, 'state': 'warm',
                                   # FIRST-JOB-REHEARSED: and what its job's rehearsal took, or why it did not run: read
                                   # in the status while the delivery is still at its checks, before any swap
                                   # SUCCESSOR-MEMORY: and the most memory this process has held, by the kernel: what
                                   # a successor of this role costs its task (the measure a reserve process is sized by)
                                   # TASK-POOLER: and how its connections came: reused from the task's pool, or by
                                   # a login, with the milliseconds of the login's parts (what a login here costs)
                                   'warm_s': round(took, 3), **job, **rss(), **database.pool_said()})},
                          db if hasattr(db, 'rows') else None)
            except Exception:  # noqa: BLE001 - the delivery then lands after its bounded wait
                LOG.exception('live image: the %s successor did not say it is warm', self.gate.role)
        return took

    def say_rehearsed(self, heard, db):
        """SWAP-MEASURE: an in-task successor says, once a reading of the pointer, that the swap's record was rehearsed on
        it and whether a drill armed it: platform.deploy.successor {state: rehearsed, armed}. The rehearsal's own
        transaction is rolled back, so this is written after it, on the loop's connection. A measured round
        (POST /v1/deploy/measure) swaps once both roles said it after its readiness notification: what the delivery's
        merge gives a landing (the seconds between its readiness question and its swap) is then by the event."""
        gate = self.gate
        if not (getattr(gate, 'intask', False) is True and gate.strict):
            return
        with self.lock:
            if self.said_heard == heard:
                return
            self.said_heard = heard
        try:
            gate.sent(UP, {'id': f'{SUCCESSOR}:{gate.role}:{gate.digest}:{gate.task}:rehearsed:{BORN}:{heard}',
                           'producer': f'tower-{gate.role}', 'role': gate.role, 'payload': json.dumps({
                               'role': gate.role, 'digest': gate.digest, 'task': gate.task, 'state': 'rehearsed',
                               'armed': bool(getattr(gate, 'armed', False)), 'reads': heard})},
                      db if hasattr(db, 'rows') else None)
        except Exception:  # noqa: BLE001 - a measured round that hears nothing fails by its bound; a landing needs none
            LOG.exception('live image: the %s successor did not say its rehearsal', gate.role)

    def said(self):
        with self.lock:
            done = [each for each in self.seen.values() if 'first' in each]
        jobs = [each for each in done if 'job_first' in each]  # FIRST-JOB-REHEARSED: the same, of the job's rehearsal
        failed = sorted({each['job_error'] for each in done if 'job_error' in each})  # the newest did not run: why
        return {'warm_first_s': round(max(each['first'] for each in done), 3),
                'warm_last_s': round(max(each['last'] for each in done), 3),
                **({'job_first_s': round(max(each['job_first'] for each in jobs), 3),
                    'job_last_s': round(max(each['job_last'] for each in jobs), 3)} if jobs else {}),
                **({'job_error': failed[0]} if failed else {})} if done else {}


# SWAP-EVIDENCE-WHEN-SLOW: the swap's seconds from which its record asks the database what it was doing (BUSY). The
# reading ran after every swap, in both roles, in the second after the pointer moved, and it was itself what the database
# was doing then: live 12/11, in ten records of five landings it saw its own statement active for 88 to 423 ms with no
# wait event, on the 2 vCPU of a host that pages; the service's first pass after a swap (0.24 s, #574) ran beside the
# runner's reading. A swap half way to the goal of 1 s is the one whose delay needs a cause; a fast one records its parts.
EVIDENCE_S = 0.5


def busy(db, window_s):
    """SWAP-TAIL-EVIDENCE: {busy: [{q, n, ms, active}], backends} of the last window_s seconds (BUSY); {} when it cannot
    be read: the evidence is a courtesy, the record of the swap is not."""
    try:
        rows = db.rows(BUSY, {'window': round(float(window_s), 3)})
        if not rows:
            return {}
        found, backends, *more = rows[0]
        logins = more[0] if more else None  # DB-STALL-EVIDENCE: {application name: connections born in the window}
        logins = json.loads(logins) if isinstance(logins, str) else logins
        return {'busy': json.loads(found) if isinstance(found, str) else found, 'backends': int(backends),
                **({'logins': logins} if logins else {})}
    except Exception:  # noqa: BLE001
        LOG.exception('live image: could not read what the database was doing at the swap')
        return {}


def empty(tenant, keys, digest, actor, payload, ident, reason):
    """IMAGE-PREWARM-C: the parameters of EMPTY: the pointers of keys emptied where they still name digest, recorded as
    platform.deploy.image_retired (payload plus the keys emptied); the statement answers those keys, or no row."""
    return {'tenant': tenant, 'keys': ','.join(keys), 'digest': digest, 'actor': actor, 'reason': reason, 'id': ident,
            'payload': json.dumps(payload)}


def stale_limit(stored):
    """IMAGE-SWAP-FAILOVER: deploy.live_stale_s from its row's text as WATCH read it; the registry default with no row or
    an invalid one, as the service reads any key."""
    try:
        return config_data.validate(STALE, json.loads(stored)) if stored else config_data.SPEC[STALE][1]
    except ValueError:
        return config_data.SPEC[STALE][1]


def on_term(gate, scope, then, clock=time.monotonic):
    """IMAGE-SWAP-FAILOVER: the SIGTERM handler of a process whose stop is then(). A promoted standby (strict) first hands
    its role back (Gate.handback on scope), HANDBACK_S at most so a slow database never holds the exit, and only then
    stops; any other process (no gate, an ECS task) stops at once: then itself, as before. The handler only sets an
    event (nothing that takes a lock the interrupted thread may hold); a thread started here, before any signal, does
    the rest. STANDBY-GRACE: a standby that is not promoted and that the engine did not dismiss (Spot's warning) stays
    GRACE_S before that: its loop goes on beating, a landing may promote it, and it leaves as soon as a promotion ended
    (the ECS tasks took the role over) or the grace ran out (then the handback, if the pointer still names it)."""
    if gate is None or not gate.strict:
        return then
    term = threading.Event()

    def leave():
        term.wait()
        # IN-TASK-STANDBY: a successor inside the task stays through no grace: its SIGTERM is its dismissal or the task's stop
        if not gate.active() and not gate.intask and not gate.dismissed(scope):
            LOG.info('live image: %s standby %s is warned of its stop: it stands by %d s more', gate.role, gate.digest, GRACE_S)
            until, promoted, tick = clock() + GRACE_S, False, threading.Event()
            while clock() < until and not (promoted and not gate.active()):
                promoted = promoted or gate.active()
                tick.wait(GRACE_TICK_S)  # the gate's state is in memory (its listener keeps it): no statement
        giving = threading.Thread(target=gate.handback, args=(scope,), name='handback', daemon=True)
        giving.start()
        giving.join(HANDBACK_S)
        then()
    threading.Thread(target=leave, name='term', daemon=True).start()
    return lambda *_: term.set()


def engaged(gate, name):
    """IMAGE-SWAP-RELOAD: Gate.engaged for a caller that may have no gate (no TOWER_IMAGE_DIGEST: the work always starts)."""
    return contextlib.nullcontext(True) if gate is None else gate.engaged(name)


def cpu(root=supervisor.CGROUP):
    """SWAP-CPU: the container's CPU as its cgroup counts it (v2 cpu.stat; v1 cpu.stat and cpuacct.usage):
    {usage_us, nr_throttled, throttled_us}: the CPU used, and how many of the quota's periods ended with the container
    held back and for how long (Fargate gives the task its CPU as a quota: 256 units are 25 ms in every 100 ms). {}
    where it cannot be read. Never raises."""
    found = {}
    for name in ('cpu.stat', 'cpu/cpu.stat', 'cpu,cpuacct/cpu.stat'):
        try:
            for line in (pathlib.Path(root) / name).read_text().splitlines():
                key, _, value = line.partition(' ')
                if value.strip().isdigit():
                    found[key] = int(value)
            break
        except OSError:
            continue
    said = {}
    if 'usage_usec' in found:
        said['usage_us'] = found['usage_usec']
    else:
        try:
            said['usage_us'] = int((pathlib.Path(root) / 'cpuacct/cpuacct.usage').read_text().strip()) // 1000
        except (OSError, ValueError):
            pass
    if 'nr_throttled' in found:
        said['nr_throttled'] = found['nr_throttled']
    if 'throttled_usec' in found:
        said['throttled_us'] = found['throttled_usec']
    elif 'throttled_time' in found:  # v1: nanoseconds
        said['throttled_us'] = found['throttled_time'] // 1000
    return said


def cpu_since(said, now=None, clock=time.monotonic):
    """SWAP-CPU: {cpu: {wall_ms, usage_ms, throttled_ms, nr_throttled}} from the cpu.stat said at the word (CPU_AT) to
    now: the wall time, the CPU the whole task used in it (every process: the one that covers, the pool, this one) and
    how long the quota held the task back. {} when the word said none. Never raises."""
    try:
        before = json.loads(said) if said else None
        if not before:
            return {}
        now = cpu() if now is None else now
        found = {'wall_ms': round((clock() - before['at']) * 1000, 1)}
        for name, key, scale in (('usage_ms', 'usage_us', 1000), ('throttled_ms', 'throttled_us', 1000),
                                 ('nr_throttled', 'nr_throttled', 1)):
            if key in now and key in before:
                found[name] = round((now[key] - before[key]) / scale, 1) if scale != 1 else now[key] - before[key]
        return {'cpu': found}
    except Exception:  # noqa: BLE001 - a measure
        return {}


def lowly(thread, nice=10, set_=None):
    """SWAP-CPU: a thread that does no work of the role (the autodeploy's look, the prewarm's) runs at a lower CPU
    priority for good: in the second of a swap the task's quota (a quarter of a vCPU) goes to the role's own threads
    first. Raising a thread's nice needs no privilege (lowering it back would). Answers whether it was set."""
    set_ = set_ or os.setpriority
    try:
        if thread is None or thread.native_id is None:
            return False
        set_(os.PRIO_PROCESS, thread.native_id, nice)
        return True
    except (OSError, AttributeError):
        return False


def gate(role, digest, scope, tenant=config_data.TENANT, task=None, strict=False, reloaded=None, intask=False,
         clock=time.monotonic, first=None):
    """The role's gate, read once; None with no TOWER_IMAGE_DIGEST (digest empty): the caller's path is the old one,
    with no read and no listener. strict (TOWER_STANDBY, IMAGE-PREWARM-B2): live only when the pointer names this digest.
    reloaded (IMAGE-SWAP-RELOAD): what the reload that started this process said, None for any other start."""
    digest = (digest or '').strip()
    if not digest:
        return None
    found = Gate(scope, role, digest, tenant, task, strict, reloaded=reloaded, intask=intask, clock=clock)
    began = found.clock()
    # SWAP-CPU: `first` is the scope of the first read (the service's loop's own connection: one statement on a kept
    # psycopg connection, not the engine's first connection with its dialect's setup and its ping)
    found.refresh(first)
    found.read_at = found.clock()
    if found.boot:  # BOOT-PARTS: of boot_s, the gate's first read: its login and the statement (the rest came before it)
        found.boot['read_s'] = round(found.read_at - began, 3)
    return found


def waited_for(gate):
    """LOOKS-AFTER-WORK: whether the role waits for this process (Gate.boot is said: it started, or a reserve was told to
    go, under a pointer that already names it): what it sets up before its first pass is in the swap's seconds."""
    return gate is not None and bool(getattr(gate, 'boot', None))


def mark(gate, name):
    """LATE-SETUP-SAID: for a process the role waits for (Gate.boot is said: started, or a reserve told to go, under a
    pointer that already names it), the seconds from its gate's first read to `name`, in that swap's record
    (after_read: {dbos, launched, settings, loop}): where the seconds between the read and the first pass go. The
    service's wake_s was 0.94 s at the drill of 12/11 21:32 UTC with only its launch (0.31 s) said apart. A clock read;
    nothing for any other process."""
    if gate is None or not gate.boot or getattr(gate, 'read_at', None) is None:
        return None
    found = round(gate.clock() - gate.read_at, 3)
    gate.boot.setdefault('after_read', {})[name] = found
    return found


class Rows:
    """rows(sql, params) over a cursor of the warm-up's transaction (no commit of its own)."""

    def __init__(self, cursor):
        self.cursor = cursor

    def rows(self, sql, params=None):
        self.cursor.execute(sql, params)
        return self.cursor.fetchall() if self.cursor.description else []


def orphaned(gate, start=None, environ=None):
    """SUCCESSOR-LOST: the role's process of a supervised task hears its supervisor's SIGUSR2 (a successor of the task
    ended unasked) and asks its gate at once whether the role is its to cover (Gate.lost). The handler only sets an
    event; a thread of its own does the asking, so no statement runs inside a signal. The supervisor is told this
    process takes the signal (supervisor.heeds). A no-op with no gate or no supervisor. Answers the thread."""
    if gate is None or not supervisor.supervised(environ):
        return None
    heard = threading.Event()

    def watch():
        while True:
            heard.wait()
            heard.clear()
            try:
                gate.lost()
            except Exception:  # noqa: BLE001 - the standby pass's watchdog still judges by the beat
                LOG.exception('live image: %s could not cover for a successor that ended', gate.role)
    signal.signal(signal.SIGUSR2, lambda *_: heard.set())
    thread = (start or (lambda target: threading.Thread(target=target, name='successor-lost', daemon=True)))(watch)
    thread.start()
    supervisor.heeds(environ)
    return thread


def rss(usage=None):
    """SUCCESSOR-MEMORY: {rss_mb}: the peak resident memory of this process (the kernel's ru_maxrss, kilobytes on Linux);
    {} where it cannot be read."""
    try:
        import resource
        found = (usage or resource.getrusage)(resource.RUSAGE_SELF).ru_maxrss
        return {'rss_mb': round(found / 1024, 1)}
    except Exception:  # noqa: BLE001
        return {}


def number(text):
    try:
        return round(float(text), 3)
    except (TypeError, ValueError):
        return None


def heed(environ=None):
    """IN-TASK-STANDBY: whether this process is a successor inside its task; one that is listens for its supervisor's
    SIGUSR1 (adopt the role) from its start: the handler only appends (no lock), Gate.adopt reads it."""
    intask = (os.environ if environ is None else environ).get(STANDBY) == INTASK
    if intask:
        signal.signal(signal.SIGUSR1, lambda *_: TOLD.append(True))
    return intask


def named(base, environ=None):
    """IN-TASK-STANDBY: the name a process beats and works under: the task's, and for a successor `<the task>:<bundle, 12>`
    (its parent's, the other successors' and the Spot standbys' are all apart)."""
    environ = os.environ if environ is None else environ
    return f"{base}:{environ.get('TOWER_IMAGE_DIGEST', '')[:12]}" if environ.get(STANDBY) == INTASK else base


def heir_of(task, digest):
    """IN-TASK-STANDBY: the name of the successor of `digest` in the task of the process named `task`."""
    return f"{task.split(':')[0]}:{digest[:12]}"


def finish(gate, pending=None, stopping=lambda: False, wait=time.sleep):
    """IN-TASK-STANDBY: a process that gave its role away (Gate.gone) waits here for what it has in flight: the gate's
    engaged work (a look, a session) and `pending` (the service's DBOS workflows), DRAIN_S at most as a reload did; then
    it ends, and its supervisor reaps it. Answers what was still pending."""
    began = gate.clock()
    while not stopping() and gate.clock() - began < DRAIN_S and (gate.busy() or (pending is not None and pending())):
        wait(0.5)
    return list(pending()) if pending is not None else []


class OnceLive:
    """IMAGE-PREWARM-B2: start() once, the first time this image may work (no gate: at once); answers whether it ran. A
    start that raises is tried again on the next call."""

    def __init__(self, start, gate, clock=time.monotonic):
        self.start, self.gate, self.done, self.clock = start, gate, False, clock
        self.seconds = None  # IMAGE-SWAP-TIGHTEN: how long the start took (the service's launch_s), once it ran

    def __call__(self):
        if not self.done and (self.gate is None or self.gate.active()):
            began = self.clock()
            self.start()
            self.done, self.seconds = True, self.clock() - began
        return self.done


def launched(gate, seconds):
    """LATE-LAUNCH-SAID: the launch of a process started under its pointer (Gate.boot is said: the role waits for it)
    goes in that swap's record as launch_s; any other process's launch is no part of a swap (a standby launches while
    it stands by) or is said by its first pass (an ECS task that turned live)."""
    if gate is not None and gate.boot and seconds is not None:
        gate.boot['launch_s'] = round(seconds, 3)
    return gate is not None and 'launch_s' in gate.boot


def kept(db):
    """A scope over one kept database (the runner's container.Reconnecting), so a swap never waits for a new login."""
    return lambda: contextlib.nullcontext(db)


class Reload:
    """IMAGE-SWAP-RELOAD: the look of an ECS task standing by under a swapped bundle (the module's docstring): step() on
    each standby pass, after the beat. gate: the task's (a strict one never reloads). command: what the exec runs again
    (serve, run-container). pending(): the ids of what the reload waits for besides the gate's engaged work (the service's
    DBOS workflows), DRAIN_S at most. stopping(): the task is being stopped: no reload. stage and execute: code_bundle's."""

    def __init__(self, gate, command, pending=None, stopping=None, stage=code_bundle.stage, execute=code_bundle.reload):
        self.gate, self.command, self.pending, self.stopping = gate, command, pending, stopping or (lambda: False)
        self.stage, self.execute, self.lock = stage, execute, threading.Lock()
        self.swap, self.asked, self.never = None, 0.0, None  # the swap looked at, its last look, the swap given up
        self.turn, self.bundle = None, None  # this task's turn to reload; the staged bundle (key, directory, staged at)
        self.since = 0.0  # DEPLOY-CANARY: when this task saw the swap it looks at

    def step(self, db=None):
        """One look, on db or the gate's scope; never raises. When it reloads, the exec replaces the process: no return."""
        gate = self.gate
        swap = (gate.pointer, gate.version)
        if (gate.strict or gate.live is not False or not gate.pointer or swap == self.never or self.stopping()
                or not self.lock.acquire(blocking=False)):  # one look at a time (the runner's slots share it)
            return
        try:
            if swap != self.swap:  # a swap this task just saw: its first RELOAD_ASK_S is the swap's own
                self.swap, self.asked, self.turn, self.bundle, self.since = swap, gate.clock(), None, None, gate.clock()
            elif self.ready(swap, db):
                self.go(swap, db)
        except Exception:  # noqa: BLE001 - the standby pass goes on; the next one looks again
            LOG.exception('live image: the reload look of %s %s failed', gate.role, gate.digest)
        finally:
            self.lock.release()

    def ready(self, swap, db):
        """Whether this task has its turn and the bundle staged: the trigger's read, RELOAD_ASK_S apart, then the staging."""
        gate = self.gate
        if self.turn is None:
            if gate.clock() - self.asked < RELOAD_ASK_S:
                return False
            self.asked = gate.clock()
            key, turn = self.plan(swap, db)
            if turn is not None and self.heir(swap, db):  # IN-TASK-STANDBY: the successor keeps the role: no reload
                turn, self.never = None, swap
            self.turn = turn
            if self.turn is not None and self.bundle is None:
                try:
                    self.bundle = (key, str(self.stage(key, swap[0])), gate.clock())
                except Exception as error:  # noqa: BLE001 - not in the store, another sha256, other requirements
                    self.turn = None
                    self.fail(swap, db, f'the bundle cannot be loaded: {error}')
        return self.turn is not None

    def plan(self, swap, db):
        """(the bundle's key, this task's turn) when it may reload now; (None, None) to look again, or never (stay)."""
        gate, (digest, version) = self.gate, swap
        key, live, reloads, now, proven = gate.sent(RELOAD_OF, {
            'role': gate.role, 'digest': digest, 'tenant': gate.tenant,
            'live': f'platform.deploy.image_live:{gate.role}:{digest}:{version}'}, db)[0]
        reloads = json.loads(reloads or '[]')
        started = [each for each in reloads if each.get('state') == 'started']
        done = {each.get('task') for each in reloads if each.get('state') == 'reloaded'}
        failed = [each.get('why') for each in reloads if each.get('state') == 'failed']
        dead = [each for each in started if each.get('task') not in done]  # claimed, and no work on the bundle recorded
        if not key:
            return self.stay(swap, 'no platform.deploy.image_swap names it: not a swapped bundle')
        if failed:
            return self.stay(swap, f'a reload of it failed ({failed[0]}): it is not tried again')
        if dead and float(now) - float(dead[0].get('at') or 0) < RELOAD_LIMIT_S:
            return None, None  # another task of the role is reloading: one at a time
        if dead:
            return self.fail(swap, db, f"{dead[0].get('task')} did not come up on it within {RELOAD_LIMIT_S} s of its reload")
        if len(done) >= RELOAD_TASKS:
            return self.stay(swap, f'{len(done)} tasks of the role reloaded it already')
        if live not in (True, 't'):
            return None, None  # the promoted standby has not worked yet: the swap may still be undone
        if proven != 'succeeded':  # DEPLOY-CANARY: the bundle has not proven dispatch, take and run on the promoted pair
            limit_s = config_data.SPEC[canary.LIMIT][1]
            if proven is None and gate.clock() - self.since > limit_s:
                return self.stay(swap, f'no canary of this swap in {limit_s:g} s: the promoted pair keeps the role')
            return None, None  # red, the watch (Gate.canaried) empties the pointer: nothing to reload onto
        return key, len(started)

    def heir(self, swap, db):
        """IN-TASK-STANDBY: at this task's turn to reload onto a proven swap (plan()): when its own successor of that
        bundle works (HEIR: a live beat of `<the task>:<bundle>`), the role is given to it for good (Gate.give) and this
        process reloads nothing; answers whether it was. With no supervisor or no such successor (a Spot pair was
        promoted): False, and the reload in place goes on as before."""
        gate = self.gate
        name = heir_of(gate.task, swap[0])
        if not supervisor.supervised() or not gate.sent(HEIR, {'role': gate.role, 'digest': swap[0], 'task': name}, db):
            return False
        gate.give(swap[0], name, db)
        return True

    def stay(self, swap, why):
        """This task does not reload onto this swap: no more looks at it. Answers plan()'s (None, None)."""
        self.never = swap
        LOG.info('live image: %s %s is not reloaded onto %s: %s', self.gate.role, self.gate.digest, swap[0], why)
        return None, None

    def fail(self, swap, db, why):
        """The guard: platform.deploy.image_reload {state: failed, why}, which every look of the role reads (plan): the
        digest is not reloaded again, and the promoted pair keeps the role until the slow path."""
        gate = self.gate
        gate.sent(RELOAD_SAY, {'id': f'{RELOAD}:{gate.role}:{swap[0]}:failed:{gate.task}', 'producer': f'tower-{gate.role}',
                               'role': gate.role, 'wrote_at': None, 'started_at': None, 'payload': json.dumps(
                                   {'role': gate.role, 'digest': swap[0], 'task': gate.task, 'state': 'failed', 'why': why})}, db)
        return self.stay(swap, why)

    def go(self, swap, db):
        """The drain, the claim and the exec. Nothing in flight is exec'd over: a run or a look (Gate.busy) is waited
        for, whatever it takes; the pending workflows DRAIN_S at most, then they are named in the event (stragglers) and
        their runs go back to their queues when their leases expire (work.reap), as when a task is replaced."""
        gate, (key, directory, staged) = self.gate, self.bundle
        gate.reloading = True  # from here no slot takes a run and no look starts (Gate.engaged) until the exec or the return
        try:
            if gate.busy() or self.stopping():
                return
            left, drain_s = list(self.pending()) if self.pending else [], gate.clock() - staged
            if left and drain_s < DRAIN_S:
                return
            said = {'role': gate.role, 'digest': swap[0], 'task': gate.task, 'state': 'started', 'from': gate.digest,
                    'turn': self.turn, 'key': key, 'drain_s': round(drain_s, 3), **({'stragglers': left[:20]} if left else {})}
            claimed = gate.sent(RELOAD_START, {
                'id': f'{RELOAD}:{gate.role}:{swap[0]}:{self.turn}', 'producer': f'tower-{gate.role}', 'role': gate.role,
                'payload': json.dumps(said), 'tenant': gate.tenant, 'key': gate.key, 'digest': swap[0], 'version': swap[1]}, db)
            if not claimed:  # the pointer moved (a failover, a handback, the revert) or another task has this turn
                self.turn = None
                gate.refresh()  # read here, not on the notification: emptied, this task (not strict) works at once
                return
            (LOG.warning if left else LOG.info)(
                'live image: %s %s reloads in place onto %s (turn %s, drained in %.1f s%s)', gate.role, gate.digest, swap[0],
                self.turn, drain_s, f'; still pending, left to their leases: {left}' if left else '')
            try:
                self.execute(self.command, key, swap[0], directory, json.loads(claimed[0][0]))
            except Exception as error:  # noqa: BLE001 - the exec itself failed: this process goes on standing by
                self.fail(swap, db, f'the exec failed: {error}')
        finally:
            gate.reloading = False


def ordered(found):
    """RELOAD-WITHOUT-STANDBY: what ORDER_OF answered: the order {digest, key, head, ...} with age_s, events (what was
    said of it, oldest first), refused (a reload onto its digest failed), jobs ({role: its canary job or None}),
    limit_s (deploy.canary_limit_s) and now (the database clock); None with no order in the last hour."""
    if not found:
        return None
    order, age_s, events, refused, jobs, limit, now = found[0]
    return {**json.loads(order), 'age_s': float(age_s), 'events': json.loads(events or '[]'),
            'refused': refused in (True, 't'), 'jobs': json.loads(jobs or '{}'), 'limit_s': canary.limit_of(limit),
            'now': float(now)}


def said(order, role, state):
    """RELOAD-WITHOUT-STANDBY: what was said of an order with this state (by this role; None: by anyone), oldest first."""
    return [each for each in order['events'] if each.get('state') == state and role in (None, each.get('role'))]


class Order:
    """RELOAD-WITHOUT-STANDBY: the look of a live ECS task at the order to load a landed bundle in place (the module's
    docstring): step() on each good pass (a runner slot's, after its TAKE; the service's, before its tick), which sends
    nothing unless a look is owed. gate: the task's (a strict one follows no order). command, pending, stopping, stage and
    execute: as Reload's. hold: no work starts while this task drains (the runner's slots take no run); without it the
    task goes on working and only the pass that finds nothing in flight execs (the service, between two ticks).
    afresh: code_bundle's way back. fire: canary.settle, for the service that judges the runner's reload."""

    def __init__(self, gate, command, pending=None, stopping=None, hold=False, stage=code_bundle.stage,
                 execute=code_bundle.reload, afresh=code_bundle.afresh, fire=canary.settle):
        self.gate, self.command, self.pending, self.stopping = gate, command, pending, stopping or (lambda: False)
        self.hold, self.stage, self.execute, self.afresh, self.fire = hold, stage, execute, afresh, fire
        self.lock = threading.Lock()
        self.due, self.asked, self.head = True, 0.0, None  # a look is owed; when the last was; the order being followed
        self.heard = gate.reads  # the gate's reads at the last look: its listener read again (a notification) and a look is owed
        self.bundle, self.draining = None, False  # the staged bundle (digest, directory, staged at); this look holds the gate
        self.by = (gate.reloaded or {}).get('order')  # the order whose reload started this process (None: any other start)
        # IN-TASK-STANDBY: the successors this task last told its supervisor to hold (None: never told), and WANTS as read
        self.wanted, self.read = None, None
        self.proven, self.refused = False, False  # of this process's own reload: its judge's green; its bundle failed
        self.gave_up = set()  # SUCCESSOR-GAVE-UP: the bundles whose successor was said failed

    def trusted(self):
        """Whether this process may keep its health file fresh: not from its reload by an order until its judge says
        proven, and not on a bundle that failed. What neither proves itself nor goes back, ECS replaces."""
        return not self.refused and (self.by is None or self.proven)

    def drop(self):
        """Nothing of an order holds this task's work (the runner's drain is over, or was never started)."""
        if self.draining:
            self.draining = self.gate.reloading = False

    def step(self, db=None):
        """One look, on db or the gate's scope; never raises. When it reloads or goes back the exec replaces the process:
        no return."""
        gate = self.gate
        if gate.strict or gate.live is not True or gate.pointer:  # under a pointer the swap is in charge (Reload)
            return self.drop()
        now, heard = gate.clock(), gate.reads
        if (not (self.due or heard != self.heard or (self.head is not None and now - self.asked >= ORDER_ASK_S))
                or self.stopping() or not self.lock.acquire(blocking=False)):  # one look at a time (the slots share it)
            return None
        try:
            told = self.due or heard != self.heard  # IN-TASK-STANDBY: a look a notification owes reads the wants too
            self.due, self.heard, self.asked = False, heard, now
            mine = self.by if self.by and not self.proven else ''  # its own order until it is judged: a newer one never hides it
            order = ordered(gate.sent(ORDER_OF, {'tenant': gate.tenant, 'head': mine}, db))
            try:
                intask = self.wants(order, db, told)
            except Exception:  # noqa: BLE001 - the order is followed all the same, the old way; the next look asks again
                LOG.exception('live image: the %s task could not tell its supervisor its successors', gate.role)
                intask, self.read, self.wanted = False, None, None
            self.follow(order, db, intask)
        except Exception:  # noqa: BLE001 - the pass goes on; the next one looks again
            self.due = True
            LOG.exception('live image: the look of %s %s at the order failed', gate.role, gate.digest)
        finally:
            self.lock.release()
        return None

    def wants(self, order, db, told=True):
        """IN-TASK-STANDBY: the successors this task should hold now, told to its supervisor when they changed: the
        bundle of an order that is open (a landing with no standby: the successor loads it, not an exec) and the bundles
        the prewarm wants (WANTS: read on the looks a notification owes, never on the ones that only follow an open
        order), newest first, deploy.intask_standbys at most and never the code this process runs. Answers whether
        successors are on for this task: False with no supervisor (nothing is read) or with the datum 0 (the supervisor
        is told to hold none)."""
        gate = self.gate
        if not supervisor.supervised():
            return False
        if told or self.read is None:
            self.read = gate.sent(WANTS, {'tenant': gate.tenant}, db)[0]
        limit, found = self.read
        try:
            limit = config_data.validate(SUCCESSORS, json.loads(limit)) if limit else config_data.SPEC[SUCCESSORS][1]
        except ValueError:
            limit = config_data.SPEC[SUCCESSORS][1]
        want = [(order['key'], order['digest'])] if order is not None and self.held(order) else []
        want += [(each['key'], each['digest']) for each in json.loads(found or '[]')]
        want = [each for each in dict.fromkeys(want) if each[1] != gate.digest][:limit]
        if want != self.wanted:
            supervisor.want(want)
            self.wanted = want
            LOG.info('live image: the %s task holds %s', gate.role, ', '.join(
                f'a successor on {digest[:12]}' for _, digest in want) or 'no successor')
            try:  # SUCCESSOR-HOLDS-SAID: in the engine's log too; a write that fails changes nothing of what is held
                gate.sent(HOLDS, {'id': f'{SUCCESSOR}:{gate.role}:{gate.task}:holds:{uuid.uuid4()}', 'role': gate.role,
                                  'producer': f'tower-{gate.role}', 'payload': json.dumps({
                                      'role': gate.role, 'task': gate.task, 'state': 'holds',
                                      'digest': want[0][1] if want else None, 'digests': [digest for _, digest in want],
                                      'order': order['digest'] if order is not None and self.held(order) else None})}, db)
            except Exception:  # noqa: BLE001
                LOG.exception('live image: the %s task could not say the successors it holds', gate.role)
        # SUCCESSOR-GAVE-UP: a successor its supervisor gave up on is said once, in the log the status reads: it was a
        # line of the task's own log, and a landing that then found no successor beating had nothing to say why
        for digest in [each for each in supervisor.failed() if each not in self.gave_up]:
            gate.sent(UP, {'id': f'{SUCCESSOR}:{gate.role}:{digest}:{gate.task}:failed', 'producer': f'tower-{gate.role}',
                           'role': gate.role, 'payload': json.dumps({
                               'role': gate.role, 'digest': digest, 'task': gate.task, 'state': 'failed',
                               'why': f'its process ended more than {supervisor.RESTARTS} times in this task'})}, db)
            self.gave_up.add(digest)
            LOG.error('live image: the %s task gave up on its successor on %s', gate.role, digest[:12])
        return limit > 0

    @staticmethod
    def open(order):
        """IN-TASK-STANDBY: an order successors may still obey: young, not ended, its bundle not refused, and no task
        reloading by exec for it (a task with no supervisor obeyed it the old way: then every task does)."""
        return not (order['age_s'] > ORDER_LIMIT_S or order['refused'] or said(order, None, 'done')
                    or said(order, None, 'started'))

    @classmethod
    def held(cls, order):
        """IN-TASK-STANDBY: an order whose bundle this task's successor holds: one that is open, and one the look
        swapped onto the successors (done, by: successors) until this process runs that bundle or its canary refuses
        it. The look that follows the swap may come before this task's listener read the pointer: dropping the bundle
        then would stop the successor that has just taken the role."""
        # STALE-ORDER-FREES-SLOT: while the order is young. It had no end: a task that started later (a rollout) read the
        # hour's newest order, done by successors on a bundle it never ran, and held a successor of that old bundle in
        # its one slot, so the bundle of the delivery in the train had none (live 12/11 00:03 to 00:12 UTC: #547 landed
        # with no standby, 16.8 s). The seconds this covers are the swap's to the adoption; ORDER_LIMIT_S is far past them
        return cls.open(order) or (order['age_s'] <= ORDER_LIMIT_S and not order['refused'] and any(
            each.get('by') == 'successors' for each in said(order, None, 'done')))

    def follow(self, order, db, intask=False):
        """What this task does about the newest order: its own reload judged, the way back, the other role judged, its
        own bundle staged and, at its turn, loaded. IN-TASK-STANDBY (intask: wants()): an open order is obeyed by this
        task's successor, which the supervisor starts: this process stages nothing and execs nothing."""
        gate = self.gate
        mine = order is not None and self.by == order['head'] and gate.digest == order['digest']  # this process runs it
        self.proven = self.proven or (mine and bool(said(order, gate.role, 'proven')))
        if order is None or order['age_s'] > ORDER_SETTLE_S or said(order, None, 'done') or (order['refused'] and not mine):
            self.head = None  # settled, or nothing of this task's: no more looks until a notification
            return self.drop()
        self.head, digest = order['head'], order['digest']
        if order['refused']:
            self.refused = True
            return self.back(order, db)
        proven = {role for role in ROLES if said(order, role, 'proven')}
        other = ROLES[gate.role == 'runner']
        if other not in proven:
            verdict = self.judge(order, other, db)
            if verdict is False:
                return self.drop()  # the bundle failed: nothing loads it
            proven |= {other} if verdict else set()
        if gate.digest == digest or order['age_s'] > ORDER_LIMIT_S:  # this task runs it already, or it is the slow path's now
            if order['age_s'] > ORDER_LIMIT_S and all(role in proven or not said(order, role, 'started') for role in ROLES):
                self.head = None  # and no reload is left to judge: no more looks
            return self.drop()
        if intask and self.open(order):
            return self.drop()
        if self.bundle is None or self.bundle[0] != digest:
            try:
                self.bundle = (digest, str(self.stage(order['key'], digest)), gate.clock())
            except Exception as error:  # noqa: BLE001 - not in the store, another sha256, other requirements
                self.say(db, gate.role, 'failed', order, task=gate.task, why=f'the bundle cannot be loaded: {error}')
                return self.drop()
        turn = self.turn(order, proven)
        return self.drop() if turn is None else self.go(order, turn, db)

    def turn(self, order, proven):
        """This task's turn ('<head, 12>.<n>': the order's own, the swaps' turns are numbers) when it may load the bundle
        now, else None: one task of a role at a time (its judge fails one that never came up), RELOAD_TASKS at most, and
        the service only once the runner is proven."""
        role = self.gate.role
        started, up = said(order, role, 'started'), {each.get('task') for each in said(order, role, 'reloaded')}
        if any(each.get('task') not in up for each in started) or len(up) >= RELOAD_TASKS:
            return None
        if role == 'service' and 'runner' not in proven:
            return None
        return f"{order['head'][:12]}.{len(started)}"

    def judge(self, order, other, db):
        """The other role's reload, judged here and never by the process under test: True (proven), False (failed) or
        None (nothing to say yet). By its canary job: ended succeeded is proven; ended any other way, or open past
        deploy.canary_limit_s, failed (canary.failed). The runner's is fired here, by the service on the code it has; the
        service fires its own after its first tick, and none within the limit is failed too. A task that claimed and
        recorded no work on the bundle within RELOAD_LIMIT_S died on it: failed."""
        gate, started, up = self.gate, said(order, other, 'started'), said(order, other, 'reloaded')
        if not started:
            return None
        task, job, limit_s = started[-1].get('task'), order['jobs'].get(other), order['limit_s']
        if not up:
            ok = False if order['now'] - float(started[-1].get('at') or 0) >= RELOAD_LIMIT_S else None
            why = f'{task} did not come up on it within {RELOAD_LIMIT_S} s of its reload'
        elif job is None and gate.role == 'service':
            with gate.scope() as found:
                self.fire(found, gate.tenant, canary.order_key(order['head'], other),
                          {'digest': order['digest'], 'head': order['head'], 'by': 'order'}, fire=True)
            return None
        elif job is None:
            ok = False if order['now'] - float(up[-1].get('at') or 0) > limit_s else None
            why = f'no canary of its reload in {limit_s:g} s'
        else:
            state, age_s = job.get('state'), float(job.get('age_s') or 0)
            ok = True if state == 'succeeded' else False if canary.failed(state, age_s, limit_s) else None
            why = f'the canary of its reload is {state} after {age_s:.1f} s'
        if ok is None:
            return None
        self.say(db, other, 'proven' if ok else 'failed', order, task=task, **({} if ok else {'why': why}))
        (LOG.info if ok else LOG.warning)('live image: the reload of %s onto %s by order is %s', other, order['digest'],
                                          'proven: its canary is green' if ok else f'failed: {why}')
        return ok

    def say(self, db, role, state, order, **more):
        """platform.deploy.image_reload {role, digest, state, order, by: this task, order_s: the order to now, ...}, once."""
        gate = self.gate
        gate.sent(ORDER_SAY, {
            'id': f"{RELOAD}:{role}:{order['digest']}:{state}:{order['head']}:{more.get('task')}",
            'producer': f'tower-{gate.role}', 'role': role, 'payload': json.dumps({
                'role': role, 'digest': order['digest'], 'state': state, 'order': order['head'], 'by': gate.task,
                'order_s': round(order['age_s'], 3), **more})}, db)

    def go(self, order, turn, db):
        """The drain, the claim and the exec. Nothing in flight is exec'd over (Gate.busy: a slot's run, a look, a
        session), whatever it takes; the service's workflows DRAIN_S at most, as Reload.go."""
        gate, (digest, directory, staged) = self.gate, self.bundle
        self.draining = gate.reloading = True  # from here no slot takes a run and no look starts (Gate.engaged)
        left, drain_s = list(self.pending()) if self.pending else [], gate.clock() - staged
        if gate.busy() or self.stopping() or (left and drain_s < DRAIN_S):
            return None if self.hold else self.drop()  # the runner stays drained; the service works until its next pass
        claim = {'role': gate.role, 'digest': digest, 'task': gate.task, 'state': 'started', 'from': gate.digest,
                 'turn': turn, 'key': order['key'], 'order': order['head'], 'drain_s': round(drain_s, 3),
                 **({'stragglers': left[:20]} if left else {})}
        claimed = gate.sent(ORDER_START, {
            'id': f'{RELOAD}:{gate.role}:{digest}:{turn}', 'producer': f'tower-{gate.role}',
            'role': gate.role, 'payload': json.dumps(claim), 'order': f'{RELOAD}:order:{order["head"]}',
            'tenant': gate.tenant, 'key': gate.key, 'digest': digest}, db)
        if claimed:
            LOG.info('live image: %s %s reloads in place onto %s by order (turn %s, drained in %.1f s)', gate.role,
                     gate.digest, digest, turn, drain_s)
            try:
                self.execute(self.command, order['key'], digest, directory, json.loads(claimed[0][0]))
            except Exception as error:  # noqa: BLE001 - the exec itself failed: this process goes on working
                self.say(db, gate.role, 'failed', order, task=gate.task, why=f'the exec failed: {error}')
        self.due = True  # a swap wrote the pointer, the bundle failed or another task has the turn: look again
        return self.drop()

    def back(self, order, db):
        """The way back of a process that runs a bundle that failed: drained as go() (a run in flight is never killed;
        the workflows are left to their leases: this code is not trusted to end them), {state: back} and the exec
        afresh. One that cannot go back stays not trusted: its health file goes stale and ECS replaces the task."""
        gate = self.gate
        self.draining = gate.reloading = True
        if gate.busy() or self.stopping():
            return None if self.hold else self.drop()
        LOG.warning('live image: %s %s failed (order %s): back to the code a task ECS starts would boot', gate.role,
                    gate.digest, order['head'])
        try:
            self.say(db, gate.role, 'back', order, task=gate.task)
            self.afresh(self.command, {'back': True, 'digest': gate.digest, 'order': order['head'], 'task': gate.task})
        except Exception:  # noqa: BLE001
            LOG.exception('live image: %s %s could not go back: not healthy until ECS replaces the task', gate.role, gate.digest)
        self.head = None
        return self.drop()
