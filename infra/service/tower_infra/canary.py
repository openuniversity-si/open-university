"""DEPLOY-CANARY (docs/operations/aws.md 22.3): the proof that the engine works end to end, not only that the port answers.

The engine gates and deploys itself. Its smoke read two routes of the port's Lambda, so a merged change that broke the
service's dispatch or the runner's take passed it green, and then no gate was left to land the fix. A canary is one job
through the whole path a check of the gate takes: created here (the port), dispatched by the service (run.started), taken
by the runner (run.running) and ended (run.ended).

What it runs: a job of the container executor in the configuration tenant's queue of checks (gate-infra.check_queue), a
checkout of the base's head with the command `true`. It is a real run, with nothing of its own in the runner: the
dispatcher's claim, the runner's TAKE, its fetch (the commit, from the checkout the task keeps or from the forge), its
prepare (the toolchain's link and the setup, which a warm task has already run for the same inputs: no toolchain is
installed), the command in the checkout, the usage it relays, the log it uploads and the end of the run. Its rank is above
every check's, so it takes the next slot that frees. Its job.created says `canary`, so scripts/medir leaves its runs out
of the checks' measures.

The verdict is the same whoever asks, on the database's clock: green when the job ended succeeded within
deploy.canary_limit_s of its creation; red past it, or when it ended any other way, with the stage that never happened:
dispatch (no run.started: the service), take (no run.running: the runner) or run (taken, and failed or not ended). It is
recorded once as platform.deploy.canary (tenant_id null: the installation's), which GET /v1/deploy/status shows; a job
left open by a red verdict is cancelled, so it is not dispatched again later. Standard library only.

  POST /v1/deploy/canary        {key[, commit]}  the installation or the configuration tenant; idempotent by the key
  GET  /v1/deploy/canary/<id>   [?wait_s=N]      its state and seconds; a long poll woken by tower_work (a run's end)

After an image swap and after a reload in place (docs/operations/aws.md 22.9) the same canary runs with no build and no
smoke. A swap's canary is keyed by the service's pointer, swap:<digest>:<its version>, so every process finds it from the
pointer it reads. Who fires it: the service that took the role, after its first good dispatch tick (Live.step), and its
autodeploy when it sees the swap (autodeploy.settle_image); a reloaded ECS service fires one of its own, reload:<digest>:
<turn>:<task>. Who judges it is never the process under test: the ECS task standing by on the previous code reads the
canary's job in the statement of its standby pass (live_image.WATCH) and, red, empties both pointers by their
compare-and-swap (platform.deploy.image_retired, by: canary) and works; and it loads the swapped bundle in place only once
that canary ended succeeded (live_image.RELOAD_OF). The verdict is recorded, and a red one published to the platform's
topic (alert), by the service that fired it and by the autodeploy of whichever service is live.

RELOAD-WITHOUT-STANDBY (live_image.Order): a landing with no standby pair is loaded in place by the ECS tasks, the runner
first, and each reload has its canary, order:<merge sha>:<role>. The runner's is fired by the service, still on the code
it had, which judges it; the reloaded service fires its own after its first tick (Live) and the runner judges it, by the
job's state alone. The verdicts are recorded and a red one published by the service's Live and by the autodeploy.
"""
import base64
import hashlib
import json
import logging
import os
import re
import time

from . import config_data, port
from . import engine  # ENGINE-REPO

LOG = logging.getLogger('tower_infra.canary')
EVENT = 'platform.deploy.canary'
# CANARY-WAITS-FOR-CAPACITY: the event that keeps "a read found no free slot before the dispatch", and how long a dispatch
# may wait for one: a check's own limit (gate-infra.check_timeout_s, 900 s), after which some run has ended or is lost
WAITED, FULL_MAX_S = 'platform.deploy.canary_waited', 900.0
LIMIT = 'deploy.canary_limit_s'
# CANARY-OWN-SLOT: with deploy.canary_slot at 1 a canary names the reserved account of the capacity (mechanisms.RESERVED),
# one slot of each container executor that no other job takes, made here when missing: a canary created while every slot
# is in a check is dispatched at once, and the runner keeps one loop more than its slots to take it
SLOT = 'deploy.canary_slot'
RESERVED = 'canary'  # mechanisms.RESERVED (a test pins it): the dispatcher is not in the port's Lambda package
OWN = ("insert into work.capacity (executor, account, slots) select e.name, %(account)s, 1 from work.executor e "
       "where e.adapter = 'container' and e.state = 'active' and (e.tenant_id is null or e.tenant_id = %(tenant)s::uuid) "
       "and exists (select 1 from work.capacity c where c.executor = e.name) on conflict (executor, account) do nothing")
KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}$')
PREFIX = 'canary:'  # of the job's idempotency key
REPO = engine.DEFAULT  # ENGINE-REPO: the default; engine.repo() is what runs; prewarm.REPO (a test pins it): the checkout the gate's checks use
QUEUE, RANK, TIMEOUT_S = 'checks', 1000000, 60  # gate-infra.check_queue; above gate_infra's ranks, which end at 999999
COMMAND = ['true']
WAIT_MAX_S, WAKES = 20, 50  # the long poll stays under the API's 30 s; a burst of other jobs' events ends it too
ENDED = ('succeeded', 'failed', 'stopped', 'cancelled')
TENANT = 'select id::text from work.tenant where name = %(tenant)s'
# One read: the job, its creation (its id is a UUIDv7) and age on the database clock, the seconds from the creation to its
# first run.started, first run.running and last run.ended (the log's index by type and time, within the hour), its last
# run's error, what its job.created said, deploy.canary_limit_s as stored (null: the default) and the verdict already recorded
READ = ("select j.id::text, j.tenant_id::text, j.idempotency_key, j.state, extract(epoch from c.at)::float8, "
        "extract(epoch from clock_timestamp() - c.at)::float8, extract(epoch from r.started - c.at)::float8, "
        "extract(epoch from r.running - c.at)::float8, extract(epoch from r.ended - c.at)::float8, "
        "(select w.error_type from work.run w where w.job_id = j.id order by w.n desc limit 1), "
        "(select e.payload::text from log.event e where e.event_id = 'job.created:' || j.id and e.type = 'job.created' "
        "and e.occurred_at >= c.at - interval '1 second' and e.occurred_at < c.at + interval '1 minute' limit 1), "
        f"(select s.value::text from work.config_value s where s.tenant_id = j.tenant_id and s.key = '{LIMIT}'), "
        f"(select e.payload::text from log.event e where e.event_id = '{EVENT}:' || j.id and e.type = '{EVENT}' "
        "and e.occurred_at >= c.at order by e.occurred_at limit 1), "
        # CANARY-WAITS-FOR-CAPACITY: whether no executor the job may go to has a free slot for it now (those of its
        # selector's adapter: another adapter's free slot, the forge's or a session's, is none of the canary's; and the
        # reserved account only when the job names it, mechanisms.ACCOUNT), and the evidence kept that one read found so
        "not exists (select 1 from work.capacity k join work.executor x on x.name = k.executor "
        "where x.state = 'active' and x.adapter = j.selector->>'adapter' and k.in_use < k.slots "
        f"and (k.account <> '{RESERVED}' or j.selector->>'account' = '{RESERVED}')), "
        f"(select 1 from log.event e where e.event_id = '{WAITED}:' || j.id and e.type = '{WAITED}' "
        "and e.occurred_at >= c.at limit 1) "
        "from work.job j join work.tenant t on t.id = j.tenant_id "
        "cross join lateral (select uuid_extract_timestamp(j.id) as at) c "
        "cross join lateral (select min(e.occurred_at) filter (where e.type = 'run.started') as started, "
        "min(e.occurred_at) filter (where e.type = 'run.running') as running, "
        "max(e.occurred_at) filter (where e.type = 'run.ended') as ended from log.event e "
        "where e.type in ('run.started', 'run.running', 'run.ended') and e.occurred_at >= c.at "
        "and e.occurred_at < c.at + interval '1 hour' and e.subject = 'job/' || j.id) r "
        f"where t.name = %(tenant)s and j.id = %(id)s::uuid and starts_with(j.idempotency_key, '{PREFIX}')")
JOB = ("select j.id::text from work.job j join work.tenant t on t.id = j.tenant_id "
       "where t.name = %(tenant)s and j.idempotency_key = %(key)s")
# the head a swap landed (the newest platform.deploy.image_swap that names the digest), for the canary's verdict
HEAD = ("select payload->>'head' from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
        "and occurred_at > now() - interval '7 days' and payload->>'digest' = %(digest)s and payload->>'swapped' = 'true' "
        "order by occurred_at desc limit 1")
# CANARY-WAITS-FOR-CAPACITY: a read that finds the canary not dispatched and no free slot anywhere says so once in the log
# (the job's own event, tenant_id null): the dispatch that comes late was the full runner's, not the service's
FULL = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        f"select %(id)s, null, '{WAITED}', clock_timestamp(), %(producer)s, 'deploy/canary', %(payload)s::jsonb "
        f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{WAITED}' "
        "and occurred_at > now() - interval '2 days') returning 1")
TOPIC = 'tower-platform-events'  # the platform's topic (aws.md 14): the service's task role may publish to tower-*
SETTLE = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          f"select %(id)s, null, '{EVENT}', clock_timestamp(), %(producer)s, 'deploy/canary', %(payload)s::jsonb "
          f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{EVENT}' "
          "and occurred_at > now() - interval '2 days') returning 1")


def configured(db, who):
    """(name, id) of the configuration tenant (TOWER_CONFIG_TENANT), in whose queue a canary runs. The installation may
    ask (the deployer's smoke token is its token), and that tenant itself; any other tenant is refused."""
    name = os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)
    found = db.rows(TENANT, {'tenant': name})
    if not found:
        raise port.PortError(409, f'no tenant {name}')
    if who[0] == 'tenant' and who[1] != found[0][0]:
        raise port.PortError(403, 'only the installation or the configuration tenant may do this')
    return name, found[0][0]


def limit_of(stored):
    """deploy.canary_limit_s from its row's text; the registry default with no row or an invalid one."""
    try:
        return config_data.validate(LIMIT, json.loads(stored)) if stored else config_data.SPEC[LIMIT][1]
    except ValueError:
        return config_data.SPEC[LIMIT][1]


def start(db, who, body, said=None):
    """POST /v1/deploy/canary {key[, commit]}: the canary job of the key (a build's id), created once: the same key
    answers the job it made first. The commit is the base's head as the log knows it (the newest push or landing of
    deploy.base_branch), unless the caller names one. said: what its job.created and its verdict carry besides."""
    tenant, tenant_id = configured(db, who)
    body = body or {}
    key = str(body.get('key') or '')
    if not KEY.match(key):
        raise port.PortError(400, 'a canary needs a key (the id of the build): letters, digits and : . _ / -')
    cfg = port.stored(db, tenant, (LIMIT, 'deploy.base_branch', SLOT))
    ref, commit = f"refs/heads/{cfg['deploy.base_branch']}", str(body.get('commit') or '')
    if not commit:
        found = db.rows(port.BASE_HEAD, {'ref': ref, 'refs': json.dumps([{'ref': ref}]), 'merge': ''})
        commit = str(found[0][0] or '') if found else ''
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise port.PortError(409, f'the log has no head of {ref} in 7 days: name a commit')
    spec = {'repo': engine.repo(), 'ref': ref, 'commit': commit, 'command': COMMAND, 'timeout_s': TIMEOUT_S}
    selector = {'adapter': 'container'}
    if cfg[SLOT]:  # CANARY-OWN-SLOT: its own slot, which exists from the first canary that asks for it
        db.rows(OWN, {'account': RESERVED, 'tenant': tenant_id})
        selector['account'] = RESERVED
    made = port.create_job(db, ('tenant', tenant_id), {
        'queue': QUEUE, 'rank': RANK, 'selector': selector, 'memoize': False,  # a run each time, never a cached answer
        'input_uri': 'data:application/json;base64,' + base64.b64encode(json.dumps(spec, sort_keys=True).encode()).decode(),
        'input_digest': 'sha256:' + hashlib.sha256(f'canary\0{key}'.encode()).hexdigest(),
        'idempotency_key': PREFIX + key}, said={**(said or {}), 'canary': key})
    return {'id': made['id'], 'key': key, 'created': made['created'], 'limit_s': cfg[LIMIT]}


DRILL = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
         "values (%(id)s, null, 'platform.deploy.drill', clock_timestamp(), %(producer)s, 'deploy/drill', %(payload)s::jsonb "
         "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3))) returning payload::text")
DIGEST = re.compile(r'^[0-9a-f]{64}$')


def drill(db, who, body):
    """POST /v1/deploy/drill {digest, role}: SWAP-DRILL, the standby lost at the instant of the swap, induced. The
    successor of that bundle and role that was born before this call ends as its gate turns live (live_image.Gate.arm:
    read when it rehearses, so the drill is asked before the delivery reaches the front); the swap, the role's process
    taking the role back and the head's way to that role are then what the engine does by itself, and are measured.
    One event, platform.deploy.drill (tenant_id null); a drill of a bundle no landing swaps to does nothing. The
    installation or the configuration tenant, as a canary."""
    configured(db, who)
    body = body or {}
    digest, role = str(body.get('digest') or ''), str(body.get('role') or '')
    if not DIGEST.match(digest) or role not in ('runner', 'service'):
        raise port.PortError(400, 'a drill names a bundle (digest: its sha256) and a role (runner or service)')
    found = db.rows(DRILL, {'id': f'platform.deploy.drill:{role}:{digest}:{time.time_ns()}', 'producer': port.PRODUCER,
                            'payload': json.dumps({'digest': digest, 'role': role, 'kind': 'lost-at-swap'})})
    return json.loads(found[0][0])


MEASURE_EVENT = 'platform.deploy.measure'
# SWAP-MEASURE: a round asked, unless one asked in the last MEASURE_BUSY_S has not ended (swapped or failed): one at a time
MEASURE = ("with busy as (select 1 from log.event a where a.type = 'platform.deploy.measure' and a.tenant_id is null "
           "and a.payload->>'state' = 'asked' and a.occurred_at > clock_timestamp() - make_interval(secs => %(busy_s)s::float8) "
           "and not exists (select 1 from log.event e where e.type = 'platform.deploy.measure' and e.tenant_id is null "
           "and e.payload->>'round' = a.payload->>'round' and e.payload->>'state' in ('done', 'failed'))), "
           "said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
           "select %(id)s, null, 'platform.deploy.measure', clock_timestamp(), %(producer)s, 'deploy/measure', %(payload)s::jsonb "
           "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
           "where not exists (select 1 from busy) returning payload::text) "
           "select payload, pg_notify('tower_deploy', 'platform.deploy.measure') from said")
MEASURE_BUSY_S = 600


def measure(db, who, body, clock=time.time_ns):
    """POST /v1/deploy/measure {drill: true|false}: SWAP-MEASURE, one round of the image swap measured by command, no
    PR, no timer (Daniel's rule: a measure with no change of code is asked by an event or a command). The live service's
    prewarm builds the published head's bundle with the round's mark (the same code, another digest: the bundle job of a
    push, on the runner), wants its successors in the ECS tasks, with drill asks the loss of both at the swap, and swaps
    onto them by the autodeploy's own statement when both beat warm: the pointers, the canary, the role adopted and
    deploy.live_code as after any swap, at the same published head. One event, platform.deploy.measure {round, drill,
    state: asked}; 409 while another round is not done. The installation or the configuration tenant."""
    configured(db, who)
    body = body or {}
    drill_ = body.get('drill', True)
    if not isinstance(drill_, bool):
        raise port.PortError(400, 'drill is true (the loss of both successors at the swap) or false')
    round_ = str(clock())
    found = db.rows(MEASURE, {'id': f'{MEASURE_EVENT}:{round_}:asked', 'producer': port.PRODUCER, 'busy_s': MEASURE_BUSY_S,
                              'payload': json.dumps({'round': round_, 'drill': drill_, 'state': 'asked'})})
    if not found:
        raise port.PortError(409, 'a measured round is in flight: one at a time')
    return json.loads(found[0][0]) if isinstance(found[0][0], str) else found[0][0]


def verdict(state, age_s, limit_s, started_s, running_s, ended_s, error=None, full=False):
    """(ok, stage, line) of a canary from its job's state and the seconds from its creation to each event (None: not
    yet). ok is None while it may still end well in time. The stage is where it is, or, red, what never happened in
    time: dispatch (the service), take (the runner), run (the run). CANARY-WAITS-FOR-CAPACITY: with `full` (the log
    keeps that a read found no free slot before the dispatch) the dispatch may come FULL_MAX_S after the creation, and
    the runner and the run have the limit from the dispatch on: a runner whose slots are all in long runs is no fault
    of the swapped code (live 11/11, #537), and a canary red for it sent the head the slow way."""
    ended_s = ended_s if state in ENDED else None
    since = (started_s or 0.0) if full else 0.0
    late = [started_s is None or started_s > (FULL_MAX_S if full else limit_s),
            running_s is None or running_s - since > limit_s, ended_s is None or ended_s - since > limit_s]
    stage = 'dispatch' if late[0] else 'take' if late[1] else 'run'
    if state == 'succeeded' and not any(late):
        return True, 'ended', (f'canary job dispatched in {started_s:.1f} s, taken in {running_s - started_s:.1f} s, '
                               f'ended in {ended_s - running_s:.1f} s')
    if state not in ENDED and full and started_s is None and age_s <= FULL_MAX_S:
        return None, 'dispatch', (f'canary job waiting for a free slot of a full runner ({age_s:.1f} s of '
                                  f'{FULL_MAX_S:g} s)')
    if state not in ENDED and age_s <= limit_s + since:
        stage = 'dispatch' if started_s is None else 'take' if running_s is None else 'run'
        return None, stage, f'canary job waiting for its {stage} ({age_s:.1f} s of {limit_s + since:g} s)'
    how = f'ended {state}' + (f' ({error})' if error else '') if state in ENDED and state != 'succeeded' else None
    if stage == 'dispatch':
        return False, stage, f"canary job {how or f'not dispatched in {limit_s:g} s'}: the service (no run.started)"
    if stage == 'take':
        return False, stage, (f"canary job dispatched in {started_s:.1f} s and {how or f'not taken in {limit_s:g} s'}: "
                              'the runner (no run.running)')
    return False, stage, (f"canary job taken in {running_s - started_s:.1f} s and {how or f'not ended in {limit_s:g} s'}: "
                          'the run')


def look(db, tenant, ident, producer=port.PRODUCER):
    """One reading of a canary: (what it says, whether this reading recorded its verdict). A verdict is recorded once
    (platform.deploy.canary, tenant_id null) and answered as recorded from then on; a red one cancels a job still open."""
    found = db.rows(READ, {'tenant': tenant, 'id': ident})
    if not found:
        raise port.PortError(404, f'no canary {ident}')
    job, tenant_id, key, state, at, age_s, started_s, running_s, ended_s, error, created, stored, recorded, *more = found[0]
    if recorded:
        return json.loads(recorded), False
    seconds = [None if each is None else float(each) for each in (started_s, running_s, ended_s)]
    limit_s = limit_of(stored)
    full_now, waited = (*more, False, None)[:2]  # (a row of before CANARY-WAITS-FOR-CAPACITY has neither)
    if full_now in (True, 't') and not waited and seconds[0] is None and state not in ENDED:
        db.rows(FULL, {'id': f'{WAITED}:{job}', 'producer': producer, 'payload': json.dumps({
            'id': job, 'key': key[len(PREFIX):], 'age_s': round(float(age_s), 3)})})
        waited = True
    ok, stage, line = verdict(state, float(age_s), limit_s, *seconds, error, full=bool(waited))
    started_s, running_s, ended_s = seconds if state in ENDED else (*seconds[:2], None)
    said = {**{name: value for name, value in json.loads(created or '{}').items() if name not in ('job_id', 'canary')},
            'id': job, 'key': key[len(PREFIX):], 'ok': ok, 'stage': stage, 'state': state, 'line': line,
            'limit_s': limit_s, 'at': round(float(at), 3),
            'dispatched_s': None if started_s is None else round(started_s, 3),
            'taken_s': None if None in (started_s, running_s) else round(running_s - started_s, 3),
            'ran_s': None if None in (running_s, ended_s) else round(ended_s - running_s, 3),
            'seconds': None if ended_s is None else round(ended_s, 3)}
    if ok is None:
        return {**said, 'age_s': round(float(age_s), 3)}, False
    fresh = bool(db.rows(SETTLE, {'id': f'{EVENT}:{job}', 'producer': producer, 'payload': json.dumps(said)}))
    if not ok and state not in ENDED:
        try:
            port.cancel_job(db, ('tenant', tenant_id), job)
        except port.PortError:  # it ended meanwhile: nothing to cancel
            pass
    return said, fresh


def read(db, who, ident, wait_s=None, wake=None, clock=time.monotonic):
    """GET /v1/deploy/canary/<id>[?wait_s=N]: the canary's state, seconds and verdict (look). With wait_s the answer
    waits, WAIT_MAX_S at most, until the verdict exists: the wait is the LISTEN of `wake` (tower_work: a run's end, a
    cancelled job), started before the first read so no end falls between the read and the wait, and it ends by itself
    when the canary's limit passes; without a wake there is nothing to wait on and the state is answered now."""
    tenant, _ = configured(db, who)
    try:
        until = clock() + min(max(float(wait_s or 0), 0.0), WAIT_MAX_S)
    except (TypeError, ValueError):
        raise port.PortError(400, 'wait_s is a number of seconds') from None
    waits = wake is not None and until > clock()
    if waits:
        wake.listening()
    try:
        for _ in range(WAKES):
            said, _fresh = look(db, tenant, ident)
            left = until - clock()
            if said['ok'] is not None or not waits or left <= 0:
                break
            wake.wait(min(left, max(said['limit_s'] - said['age_s'], 0.0) + 0.05))  # its limit passing is an end too
        return said
    finally:
        if wake is not None:
            wake.close()


def swap_key(digest, version):
    """The key of an image swap's canary: the digest and the version of the service's pointer that names it."""
    return f'swap:{digest}:{version}'


def order_key(head, role):
    """RELOAD-WITHOUT-STANDBY: the key of the canary of a role's reload in place by the order of a landing (its merge sha)."""
    return f'order:{head}:{role}'


def failed(state, age_s, limit_s):
    """Whether a canary is red by its job alone, as a standby's watch reads it with no read of the log: it ended and
    not succeeded, or it is still open past the limit."""
    return state != 'succeeded' if state in ENDED else float(age_s) > limit_s


def topic_arn(identity, region):
    """The platform's topic in the caller's own partition and account (STS GetCallerIdentity: its Arn and Account)."""
    parts = str(identity.get('Arn') or '').split(':')
    partition = parts[1] if len(parts) > 1 and parts[1] else 'aws'
    return f"arn:{partition}:sns:{region}:{identity['Account']}:{TOPIC}"


def alert(said, environ=None, subject='tower deploy canary RED'):
    """A red canary published to the platform's topic: TOWER_ALERTS_TOPIC_ARN, else the account's tower-platform-events
    (the service's task role may publish to tower-*). Never raises: the verdict is in the log either way.
    DB-VITALS: the database's thresholds are published the same way, under their own subject."""
    environ = os.environ if environ is None else environ
    try:
        import boto3
        region = environ.get('AWS_REGION')
        topic = environ.get('TOWER_ALERTS_TOPIC_ARN') or (
            topic_arn(boto3.client('sts', region_name=region).get_caller_identity(), region))
        boto3.client('sns', region_name=region).publish(TopicArn=topic, Subject=subject,
                                                        Message=json.dumps(said, sort_keys=True))
    except Exception:  # noqa: BLE001
        LOG.exception('canary: %s (%s) was not published', subject, said.get('key'))


def settle(db, tenant, key, said=None, fire=False, publish=alert, producer='tower-service'):
    """The service's reading of the canary of a key: what it says (look), or None when there is none. fire: it is made
    when missing (start, with said). A red verdict this reading recorded is published, once."""
    found = db.rows(JOB, {'tenant': tenant, 'key': PREFIX + key})
    if not found and not fire:
        return None
    ident = found[0][0] if found else start(db, ('installation', None), {'key': key}, said)['id']
    verdict, fresh = look(db, tenant, ident, producer)
    if fresh and verdict['ok'] is False:
        LOG.warning('canary: %s is red: %s', key, verdict['line'])
        publish(verdict)
    return verdict


class Live:
    """The live service's canaries: step() after each good dispatch tick. A service that took its role by a pointer (a
    promoted standby: strict, and the pointer names its digest) fires the swap's canary, once per pointer version; an ECS
    service that reloaded itself in place fires one of its own, once. What it fired it reads on its later ticks (a run's
    end wakes the tick) until the verdict is recorded. A read or a start that fails is tried again on the next tick; a
    canary the port refuses to make (no head of the base in the log) is said once and left. Never raises."""

    def __init__(self, gate, scope, publish=alert):
        self.gate, self.scope, self.publish = gate, scope, publish
        self.fired, self.pending = set(), {}  # the keys asked for; key -> what its job.created says, until its verdict

    def due(self):
        gate = self.gate
        if gate.reloaded is not None and gate.reloaded.get('order'):  # RELOAD-WITHOUT-STANDBY: its judge reads it by this key
            if 'runner' not in (gate.reloaded.get('roles') or ['runner']):
                return None, None  # FAST-PATH-RELOAD: no runner takes it; the order of the service alone proves itself
            return order_key(gate.reloaded['order'], gate.role), 'order'
        if gate.reloaded is not None:
            return f"reload:{gate.digest}:{gate.reloaded.get('turn')}:{gate.task}", 'reload'
        if gate.strict and gate.pointed():
            return swap_key(gate.digest, gate.version), 'swap'
        return None, None

    def step(self):
        """FIRST-JOB-AT-ONCE: answers True when this step made (or found) the canary of a key it had not asked for yet:
        the loop then dispatches it in the same pass, not on its next one."""
        key, by = self.due()
        fresh = key is not None and key not in self.fired
        if not fresh and not self.pending:
            return False
        gate = self.gate
        try:
            with self.scope() as db:
                if fresh:
                    head = db.rows(HEAD, {'digest': gate.digest})
                    self.pending[key] = {'digest': gate.digest, 'by': by,
                                         'head': (gate.reloaded or {}).get('order') or (head[0][0] if head else None)}
                    self.fired.add(key)
                for each, said in list(self.pending.items()):
                    if settle(db, gate.tenant, each, said, fire=True, publish=self.publish)['ok'] is not None:
                        del self.pending[each]
        except port.PortError as error:
            LOG.warning('canary: no canary of %s %s: %s', gate.role, gate.digest, error)
            self.pending.clear()
            return False
        except Exception:  # noqa: BLE001 - the next tick tries again
            LOG.exception('canary: the canary of %s %s was not made or read', gate.role, gate.digest)
            return False
        return fresh
