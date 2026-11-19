"""The port over HTTP (P3 F2): API Gateway's HTTP API calls this Lambda (payload 2.0), which answers from the database.

handle(event, db, installation_sha256) is the whole port and takes its database, so the gate's test runs it on a
throwaway database; handler(event, context) is the Lambda's entry, with one IAM-token connection kept between calls.

Routes (the bearer token names the caller; a tenant sees only its own):
  POST /v1/tenants                       {name, token_sha256}               the installation
  POST /v1/executors                     {name, adapter, config, capabilities}
  PUT  /v1/executors/{name}/config       {config}                           whoever registered it
  PUT  /v1/executors/{name}/capacity/{account}  {slots, resets_at}
  GET  /v1/config/{key}                                             the value the service reads (the table's or the default)
  PUT  /v1/config/{key}                  {value, reason}                    a tenant's behaviour key as data (DEP9); no deploy
  PUT  /v1/queues/{name}                 {policy, config}
  POST /v1/limits                        {scope, scope_id, meter, maximum, action: stop|refuse|wait, resets_at}
  PUT  /v1/limits/{id}                   {maximum, resets_at, action, reset_used, lift}   the tenant's own
  GET  /v1/limits                        the tenant's own: {limits: [{id, scope, scope_id, meter, maximum, used, action, resets_at}]}
  GET  /v1/limits/{id}                   one of them; another tenant's id is 404
  PUT  /v1/meter-rates                   {meter, derived_meter, rate}
  POST /v1/jobs                          the job's fields
  POST /v1/jobs/{id}/cancel
  POST /v1/jobs/{id}/resume              {content}
  GET  /v1/jobs/{id}                     ?wait_s=N[&seen=D]                 PORT-LONG-POLL: a long poll until it is not the answer D
  GET  /v1/health                                                           no token: the database answers (the deploy smoke)
                                         ?wait_s=N                          PORT-HEALTH-WAIT: held until the database answers (N s at most)
  POST /v1/deploy/landed                 {merge_sha, base_before, pr, pr_head, functions, manifest_key, paths, code}  platform.deploy.landed (+ the image swap, IMAGE-SWAP-TIGHTEN)
  GET  /v1/deploy/status                                                    last-sha and last-build, as the service observed them (DEP3)
                                         ?landings=N                        STATUS-LANDINGS: with the swaps of its newest N landings (10 with none)
                                         ?wait_s=N[&seen=D]                 PORT-LONG-POLL: a long poll until it is not the answer D
  GET  /v1/deploy/ready/{sha256}                                            READY-BY-BEATS: the roles whose standby of the bundle beats now
  POST /v1/deploy/drill                  {digest, role}                     SWAP-DRILL: that bundle's successor of the role ends as it turns live
  POST /v1/check-run                     {repo, headSha, checkSuite, checkRun}  CHECK-RUN-AWS: tower/gate, posted by the service
  GET  /v1/check-run/<id>                                                   CHECK-RUN-AWS: its newest state
  POST /v1/deploy/drills                 {kind[, function]}                 DRILLS: a drill of the live service (lambda-rollback)
  GET  /v1/deploy/drills/<id>                                                DRILLS: its newest state
  POST /v1/deploy/canary                 {key[, commit]}                    DEPLOY-CANARY: one job through dispatch, take and run; the installation
  GET  /v1/deploy/canary/{id}            ?wait_s=N                          its state, seconds and verdict; a long poll until it has one
  POST /v1/log/query                     {filters, payload, since, group_by, limit}
  POST /v1/train/join                    {base, pr, head, files}            the delivery takes its place in the base's merge train
  POST /v1/train/renew                   {base, pr, lease_s}                the delivery renews its entry's lease (a dead one expires)
  POST /v1/train/end                     {base, pr, ended: landed|left, reason}
  POST /v1/train/wait                    {base, pr, timeout_s}              long poll: returns when the pr is the front, gone, or at the safety timeout
  GET  /v1/train                         every base's queue in order
  POST /v1/subscriptions                 {sink, types}
  GET  /v1/subscriptions                 the tenant's subscriptions: id, sink, types, state, read_until (WEBHOOK-DEAD-ALERT)
  POST /v1/subscriptions/{id}/cancel     stops it (idempotent); another tenant's id is 404

  POST /v1/forge/origin/webhooks         Origin's deliveries: no token, the Ed25519 signature (forge_webhooks)
"""
import base64
import json
import os
import re
import time

_LOADING = time.monotonic()  # PORT-COLD-START: the module's load starts here (its imports are the Lambda's init)

from . import branches, canary, checks, drills, forge_webhooks, observations, port, wake

# SQLSTATE classes of the database's refusals: the caller's input (400), a conflict with the state (409).
BAD_INPUT = {'22P02', '22007', '22008', '23514', '23502'}
CONFLICT = {'23505', '23503', 'P0001'}


ROUTES = [
    ('POST', r'/v1/tenants', lambda db, who, body: {'id': port.register_tenant(db, who, body.get('name'),
                                                                                body.get('token_sha256'))}),
    ('POST', r'/v1/executors', lambda db, who, body: {'name': port.register_executor(
        db, who, body.get('name'), body.get('adapter'), body.get('config'), body.get('capabilities'))}),
    ('PUT', r'/v1/executors/(?P<name>[a-z0-9-]+)/config',
     lambda db, who, body, name: port.configure_executor(db, who, name, body.get('config'))),
    ('PUT', r'/v1/executors/(?P<name>[a-z0-9-]+)/capacity/(?P<account>[A-Za-z0-9._-]+)',
     lambda db, who, body, name, account: port.set_capacity(db, who, name, account, body.get('slots'),
                                                            body.get('resets_at'))),
    ('GET', r'/v1/config/(?P<key>[a-z0-9_.-]+)', lambda db, who, body, key: port.get_config(db, who, key)),
    ('PUT', r'/v1/config/(?P<key>[a-z0-9_.-]+)',
     lambda db, who, body, key: port.set_config(db, who, key, body.get('value'), body.get('reason'))),
    ('PUT', r'/v1/queues/(?P<name>[a-z0-9-]+)',
     lambda db, who, body, name: port.configure_queue(db, who, name, body.get('policy', 'fifo'), body.get('config'))),
    ('POST', r'/v1/limits', lambda db, who, body: {'id': port.define_limit(
        db, who, body.get('scope'), body.get('scope_id'), body.get('meter'), body.get('maximum'),
        body.get('action'), body.get('resets_at'))}),
    ('PUT', r'/v1/limits/(?P<limit>[0-9a-f-]{36})', lambda db, who, body, limit: port.change_limit(db, who, limit, body)),
    ('GET', r'/v1/limits', lambda db, who, body: port.list_limits(db, who)),
    ('GET', r'/v1/limits/(?P<limit>[0-9a-f-]{36})', lambda db, who, body, limit: port.get_limit(db, who, limit)),
    ('PUT', r'/v1/meter-rates', lambda db, who, body: port.define_meter_rate(
        db, who, body.get('meter'), body.get('derived_meter'), body.get('rate'))),
    ('POST', r'/v1/jobs', lambda db, who, body: port.create_job(db, who, body)),
    ('POST', r'/v1/jobs/batch', lambda db, who, body: port.create_jobs(db, who, body)),  # JOBS-BATCH
    ('POST', r'/v1/jobs/(?P<job>[0-9a-f-]{36})/cancel', lambda db, who, body, job: port.cancel_job(db, who, job)),
    ('POST', r'/v1/jobs/(?P<job>[0-9a-f-]{36})/resume',
     lambda db, who, body, job: port.resume_job(db, who, job, body.get('content'))),
    ('GET', r'/v1/jobs/(?P<job>[0-9a-f-]{36})', lambda db, who, body, job: port.long_poll(  # PORT-LONG-POLL
        lambda: port.get_job(db, who, job), body, wake_of(db, (wake.JOBS, wake.WORK, wake.RUNS)))),
    ('POST', r'/v1/deploy/landed', lambda db, who, body: port.deploy_landed(db, who, body)),
    # PORT-LONG-POLL; STATUS-HOLD (D-331): and tower_config, since deploy.live_code (the status's live_code, which deploy.sh's
    # reload waits for) is a config value, written after the image_reload event that woke the poll before it
    ('GET', r'/v1/deploy/status', lambda db, who, body: port.long_poll(
        lambda: port.deploy_status(db, who, (body or {}).get('landings')), body,
        wake_of(db, (wake.STATUS, wake.DEPLOY, wake.CONFIG)))),
    ('GET', r'/v1/deploy/ready/(?P<digest>[0-9a-f]{64})',  # READY-BY-BEATS: would a landing of this bundle swap now
     lambda db, who, body, digest: port.deploy_ready(db, who, digest)),
    ('POST', r'/v1/deploy/canary', lambda db, who, body: canary.start(db, who, body)),  # DEPLOY-CANARY
    ('POST', r'/v1/deploy/drill', lambda db, who, body: canary.drill(db, who, body)),  # SWAP-DRILL
    ('POST', r'/v1/check-run', lambda db, who, body: checks.ask(db, who, body)),  # CHECK-RUN-AWS
    ('GET', r'/v1/check-run/(?P<ident>[0-9]{1,24})', lambda db, who, body, ident: checks.state(db, who, ident)),
    ('POST', r'/v1/pr-observation', lambda db, who, body: observations.ask(db, who, body)),  # PR-OBSERVATION
    ('POST', r'/v1/branch-merge', lambda db, who, body: branches.ask(db, who, body)),  # BRANCH-MERGE
    ('POST', r'/v1/deploy/drills', lambda db, who, body: drills.ask(db, who, body)),  # DRILLS
    ('GET', r'/v1/deploy/drills/(?P<ident>[0-9]{1,24})', lambda db, who, body, ident: drills.state(db, who, ident)),
    ('GET', r'/v1/branch-merge/(?P<ident>[0-9]{1,24})', lambda db, who, body, ident: branches.state(db, who, ident)),
    ('GET', r'/v1/pr-observation/(?P<ident>[0-9]{1,24})', lambda db, who, body, ident: observations.state(db, who, ident)),
    ('GET', r'/v1/deploy/canary/(?P<job>[0-9a-f-]{36})',
     lambda db, who, body, job: canary.read(db, who, job, body.get('wait_s'), wake_of(db, wake.WORK))),
    ('POST', r'/v1/log/query', lambda db, who, body: {'events': port.query_log(
        db, who, body.get('filters'), body.get('payload'), body.get('since'), body.get('group_by'),
        body.get('limit'))}),
    ('POST', r'/v1/train/join', lambda db, who, body: port.train_join(
        db, who, body.get('base'), body.get('pr'), body.get('head'), body.get('files'), body.get('lease_s'))),
    ('POST', r'/v1/train/renew', lambda db, who, body: port.train_renew(
        db, who, body.get('base'), body.get('pr'), body.get('lease_s'))),
    ('POST', r'/v1/train/end', lambda db, who, body: port.train_end(
        db, who, body.get('base'), body.get('pr'), body.get('ended'), body.get('reason'))),
    ('POST', r'/v1/train/wait', lambda db, who, body: port.train_wait(db, who, body, wake_of(db))),
    ('GET', r'/v1/train', lambda db, who, body: port.train_state(db, who)),
    ('POST', r'/v1/subscriptions/(?P<subscription>[0-9a-f-]{36})/rewind',
     lambda db, who, body, subscription: port.rewind_subscription(db, who, subscription, body.get('since'))),
    ('POST', r'/v1/subscriptions/(?P<subscription>[0-9a-f-]{36})/cancel',
     lambda db, who, body, subscription: port.cancel_subscription(db, who, subscription)),
    ('GET', r'/v1/subscriptions', lambda db, who, body: {'subscriptions': port.list_subscriptions(db, who)}),
    ('POST', r'/v1/subscriptions', lambda db, who, body: {'id': port.subscribe(db, who, body.get('sink'),
                                                                                body.get('types'))}),
]


def wake_of(db, channel=wake.TRAIN):
    """The LISTEN of tower_train (DEPLOY-CANARY: or of `channel`) on a connection of its own, when the database can open
    one (the Lambda's Lazy can). DB-LISTEN-ONE: one per long poll, for its invocation, named `wait`. None only for a
    database with no connect (the tests' stand-ins): on the port's Lambda (answered: lazy_database) it never is, and a
    listener that cannot open still holds the read (port.long_poll, LONG-POLL-HOLDS)."""
    connect = getattr(db, 'connect', None)
    return wake.Wake(lambda: connect(purpose='wait'), channel) if connect else None


def answer(status, body):
    return {'statusCode': status, 'headers': {'content-type': 'application/json'}, 'body': json.dumps(body)}


def status_of(error):
    """The HTTP status of a refusal: the port's own, or the class of the database's SQLSTATE."""
    if isinstance(error, port.PortError):
        return error.status
    state = getattr(error, 'sqlstate', None)
    if state in BAD_INPUT:
        return 400
    if state in CONFLICT:
        return 409
    return None


# DEP-EVENTS: the end of a deploy build pushed by EventBridge (rule tower-infra-deploy-state of the bootstrap, to the alias
# tower-port-api:live), so the autodeploy wakes by event (NOTIFY tower_deploy, migrations 0009/0013) instead of its SSM read.
BUILD_PROJECT = 'tower-infra-deploy'
BUILD_TERMINAL = ('SUCCEEDED', 'FAILED', 'FAULT', 'STOPPED', 'TIMED_OUT')
BUILD_ENDED = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
               "select %(id)s, null, 'platform.deploy.ended', clock_timestamp(), 'codebuild', 'deploy/build', %(payload)s::jsonb "
               "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.ended' "
               "and occurred_at > now() - interval '2 days')")


# SLOW-PATH-NO-ROLLOUT-WAIT: the newest migration the database has applied (GET /v1/health?migration): the deploy build's
# evidence that the live service applied the head's migrations before it starts the service and runner stacks side by side
MIGRATION = "select max(payload->>'migration') from log.event where type = 'platform.migration.applied'"


# FAST-PATH-RELOAD: a build's start (IN_PROGRESS) becomes platform.deploy.started {build}, once per build, and wakes the
# autodeploy look on tower_deploy (no trigger names this type): the look then watches that build's record while it may still
# name the reload of a code-only merge (autodeploy.build_reload). Nothing else reads it.
BUILD_STARTED = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                 "select %(id)s, null, 'platform.deploy.started', clock_timestamp(), 'codebuild', 'deploy/build', %(payload)s::jsonb "
                 "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.started' "
                 "and occurred_at > now() - interval '2 days') returning type) select pg_notify('tower_deploy', type) from said")


# QUEUE-RELOAD (tower_infra.queue_deploy): the merge queue's words, passed on by the doorbell Lambda in a direct invocation
# (IAM's: only a principal granted lambda:InvokeFunction on this alias gets here, so it carries no token): `prepare` when
# the queue built a merge's commit, `landed` when main moved to it. One event each, platform.deploy.queue {event, sha}, and
# a wake of the autodeploy look on tower_deploy. The sha is a claim the look checks against the repository; never trusted.
QUEUE_SAID = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
              "select %(id)s, null, 'platform.deploy.queue', clock_timestamp(), 'doorbell', 'deploy/queue', %(payload)s::jsonb "
              "where not exists (select 1 from log.event where event_id = %(id)s and type = 'platform.deploy.queue' "
              "and occurred_at > now() - interval '2 days') returning type) select pg_notify('tower_deploy', type) from said")


def queue_state(event, db):
    """A doorbell's queue word {event: prepare|landed, sha} becomes platform.deploy.queue (QUEUE_SAID); anything else is
    ignored."""
    detail = event.get('detail') if isinstance(event.get('detail'), dict) else {}
    word, sha = str(detail.get('event') or ''), str(detail.get('sha') or '')
    if word not in ('prepare', 'landed') or not re.fullmatch(r'[0-9a-f]{40}', sha):
        return {'ignored': True}
    ident = f'platform.deploy.queue:{word}:{sha}'
    said = {'event': word, 'sha': sha, 'port_at': round(time.time(), 3)}  # PUSH-STEPS: when the port got the word
    heard = detail.get('heard')  # and when the doorbell heard it (absent from an older doorbell)
    if isinstance(heard, (int, float)) and not isinstance(heard, bool):
        said['heard'] = round(float(heard), 3)
    db.rows(QUEUE_SAID, {'id': ident, 'payload': json.dumps(said)})
    return {'event_id': ident}


def build_state(event, db):
    """A CodeBuild Build State Change of the deployer: a terminal status becomes platform.deploy.ended, once per build
    (EventBridge delivers at least once). Its id is not the autodeploy's own (platform.deploy.ended:<build>, written when it
    settles the build with the sha and the dirty stacks), so both stand; this one only wakes the look sooner. The build is
    named as last-build names it (<project>:<uuid>, the part of the ARN after build/). FAST-PATH-RELOAD: its start is
    platform.deploy.started (BUILD_STARTED). Anything else is ignored."""
    detail = event.get('detail') if isinstance(event.get('detail'), dict) else {}
    status, build = str(detail.get('build-status') or ''), str(detail.get('build-id') or '').rpartition('build/')[2]
    if detail.get('project-name') == BUILD_PROJECT and status == 'IN_PROGRESS' and build:  # FAST-PATH-RELOAD
        ident = f'platform.deploy.started:{build}'
        db.rows(BUILD_STARTED, {'id': ident, 'payload': json.dumps({'build': build, 'source': 'codebuild'})})
        return {'event_id': ident}
    if detail.get('project-name') != BUILD_PROJECT or status not in BUILD_TERMINAL or not build:
        return {'ignored': True}
    ident = f'platform.deploy.ended:{build}:codebuild'
    db.rows(BUILD_ENDED, {'id': ident, 'payload': json.dumps({'build': build, 'status': status.lower(), 'source': 'codebuild'})})
    return {'event_id': ident}


# SLOW-PATH-NO-ROLLOUT-WAIT: the end of a stack's operation pushed by EventBridge (a rule for the CloudFormation Stack Status
# Change of the tower-app-* stacks to the alias tower-port-api:live; docs/operations/aws.md 22.10 has it as a request for the
# Torre: the bootstrap is not the deployer's to change). deploy.sh starts an ECS rollout and does not wait for it; this event
# wakes the autodeploy (the same NOTIFY as a build's end), which rings the build that verifies the rollout.
STACK_PREFIX = 'tower-app-'
STACK_ENDED = BUILD_ENDED.replace("'codebuild', 'deploy/build'", "'cloudformation', 'deploy/stack'")


def stack_state(event, db):
    """A CloudFormation Stack Status Change of an app stack: a status that ends an operation (anything but *_IN_PROGRESS)
    becomes platform.deploy.ended {stack, status, source: cloudformation}, once per EventBridge event (delivered at least
    once). Anything else is ignored."""
    detail = event.get('detail') if isinstance(event.get('detail'), dict) else {}
    stack = str(detail.get('stack-id') or '').partition(':stack/')[2].partition('/')[0]
    said = detail.get('status-details') if isinstance(detail.get('status-details'), dict) else {}
    status = str(said.get('status') or '')
    if not stack.startswith(STACK_PREFIX) or not status or status.endswith('_IN_PROGRESS'):
        return {'ignored': True}
    ident = f"platform.deploy.ended:{stack}:{status.lower()}:{event.get('id') or event.get('time')}"
    db.rows(STACK_ENDED, {'id': ident, 'payload': json.dumps({'stack': stack, 'status': status.lower(),
                                                              'source': 'cloudformation'})})
    return {'event_id': ident}


# ECS-STOPS-IN-LOG: why a task of the engine stopped, kept. ECS forgets a stopped task's stopCode and stoppedReason within
# the hour, CloudTrail has no StopTask of a Spot interruption and nothing kept the ECS Task State Change (live 12/11
# 13:57 UTC: a runner task stopped 47 s after it started; an hour later only the runner's own log could say `interrupted`).
# A rule of the bootstrap sends the cluster's stopped tasks and its services' actions to the alias tower-port-api:live
ECS_CLUSTER = 'tower'
ECS_SAID = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            "select %(id)s, null, %(type)s, clock_timestamp(), 'ecs', %(subject)s, %(payload)s::jsonb "
            "where not exists (select 1 from log.event where event_id = %(id)s and type = %(type)s "
            "and occurred_at > now() - interval '2 days')")
TEXT = 500  # the most of a reason an event carries


def ecs_state(event, db):
    """An ECS Task State Change of a task of the engine's cluster that STOPPED becomes platform.ecs.task_stopped {task,
    group, definition, capacity, stop_code, reason, containers: [{name, exit, reason}], started_at, stopping_at,
    stopped_at}, once per task; an ECS Service Action (a placement failure, a start impaired, a steady state) becomes
    platform.ecs.service_action {name, level, reason, services}, once per EventBridge event. Anything else is ignored."""
    detail = event.get('detail') if isinstance(event.get('detail'), dict) else {}
    kind = event.get('detail-type')
    if kind == 'ECS Task State Change':
        task = str(detail.get('taskArn') or '').rpartition('/')[2]
        if (str(detail.get('clusterArn') or '').rpartition('/')[2] != ECS_CLUSTER or detail.get('lastStatus') != 'STOPPED'
                or not task):
            return {'ignored': True}
        containers = [{'name': each.get('name'), 'exit': each.get('exitCode'),
                       **({'reason': str(each['reason'])[:TEXT]} if each.get('reason') else {})}
                      for each in detail.get('containers') or [] if isinstance(each, dict)]
        said = {'task': task, 'group': detail.get('group'),
                'definition': str(detail.get('taskDefinitionArn') or '').rpartition('/')[2] or None,
                'capacity': detail.get('capacityProviderName') or detail.get('launchType'),
                'stop_code': detail.get('stopCode'), 'reason': str(detail.get('stoppedReason') or '')[:TEXT] or None,
                'containers': containers, 'started_at': detail.get('startedAt'), 'stopping_at': detail.get('stoppingAt'),
                'stopped_at': detail.get('stoppedAt'),
                # ROLLOUT-PARTS: and the rest of the task's life, which a rollout's seconds are made of: made, its image
                # pulled, its network up, its containers ended (the rest of stopping to stopped is Fargate's)
                'created_at': detail.get('createdAt'), 'pull_started_at': detail.get('pullStartedAt'),
                'pull_stopped_at': detail.get('pullStoppedAt'), 'connectivity_at': detail.get('connectivityAt'),
                'execution_stopped_at': detail.get('executionStoppedAt')}
        ident, name, subject = f'platform.ecs.task_stopped:{task}', 'platform.ecs.task_stopped', 'ecs/task'
    elif kind == 'ECS Service Action':
        services = [str(each).rpartition('/')[2] for each in event.get('resources') or []]
        if not detail.get('eventName') or not any(f':service/{ECS_CLUSTER}/' in str(each) for each in event.get('resources') or []):
            return {'ignored': True}
        said = {'name': detail.get('eventName'), 'level': detail.get('eventType'),
                'reason': str(detail.get('reason') or '')[:TEXT] or None, 'services': services}
        ident = f"platform.ecs.service_action:{event.get('id') or event.get('time')}"
        name, subject = 'platform.ecs.service_action', 'ecs/service'
    else:
        return {'ignored': True}
    db.rows(ECS_SAID, {'id': ident, 'type': name, 'subject': subject,
                       'payload': json.dumps({key: value for key, value in said.items() if value is not None})})
    return {'event_id': ident}


# PORT-HEALTH-WAIT: GET /v1/health?wait_s=N, the deploy smoke's readiness wait (scripts/deploy-smoke::check) held by the
# port: the port is ready when its database answers (the Lazy's connection opened: the init's warm or the call's own
# login, which the call already waits for). With wait_s (canary.WAIT_MAX_S at most, the long poll's bound, under the
# API's 30 s) a login the database refused (Unreachable: at its connections' limit, or away) is tried again within the
# wait, each pause doubling from HEALTH_RETRY_S[0] to HEALTH_RETRY_S[1] (a backoff on a failed login, never a read of a
# state), and the answer carries LONG_POLL {waited_s, ready}: 200 ok:true once it answers, 503 when the wait ran out.
# Without wait_s the answer is today's (one read, 503 after answered()'s second attempt), unmarked.
HEALTH_RETRY_S = (0.25, 4.0)
LONG_POLL = port.LONG_POLL


def health_span(event):
    """The wait GET /v1/health asked for, bounded (canary.WAIT_MAX_S), or None: PortError(400) for one that is no number."""
    asked = (event.get('queryStringParameters') or {}).get('wait_s')
    if asked is None:
        return None
    try:
        return min(max(float(asked), 0.0), canary.WAIT_MAX_S)
    except (TypeError, ValueError):
        raise port.PortError(400, 'wait_s is a number of seconds') from None


def ready(db, span, clock=None, sleep=None):
    """PORT-HEALTH-WAIT: db.rows('select 1') once the database answers, within span seconds; Unreachable when it ran out."""
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    until, pause = clock() + span, HEALTH_RETRY_S[0]
    while True:
        try:
            return db.rows('select 1')
        except Unreachable:
            left = until - clock()
            if left <= 0:
                raise
            sleep(min(pause, left))
            pause = min(pause * 2, HEALTH_RETRY_S[1])


def handle(event, db, installation_sha256, now=None):
    if 'requestContext' not in event and event.get('source') == 'tower.doorbell':  # QUEUE-RELOAD
        return queue_state(event, db)
    if 'requestContext' not in event and event.get('source') == 'aws.ecs':  # ECS-STOPS-IN-LOG
        return ecs_state(event, db)
    if 'requestContext' not in event and event.get('source') == 'aws.codebuild' \
            and event.get('detail-type') == 'CodeBuild Build State Change':  # an HTTP call always carries requestContext
        return build_state(event, db)
    if 'requestContext' not in event and event.get('source') == 'aws.cloudformation' \
            and event.get('detail-type') == 'CloudFormation Stack Status Change':  # SLOW-PATH-NO-ROLLOUT-WAIT
        return stack_state(event, db)
    method = event.get('requestContext', {}).get('http', {}).get('method', '')
    path = event.get('rawPath', '')
    headers = {key.lower(): value for key, value in (event.get('headers') or {}).items()}
    if method == 'POST' and path == forge_webhooks.PATH:  # P4 F2b: the signature authenticates it, not a token
        raw = (base64.b64decode(event.get('body') or '') if event.get('isBase64Encoded')
               else (event.get('body') or '').encode('utf-8'))
        status, said = forge_webhooks.accept(db, headers, raw, now)
        return answer(status, said)
    if method == 'GET' and path == '/v1/health':  # DEP7: the deploy smoke's door; no token, one read of the database
        try:
            span = health_span(event)
        except port.PortError as error:
            return answer(error.status, {'error': str(error)})
        began = time.monotonic()
        try:
            ok = bool(ready(db, span) if span is not None else db.rows('select 1'))
        except Unreachable as error:
            if span is None:
                raise  # answered(): tried again once, then 503 (PORT-503-NO-DATABASE), as before PORT-HEALTH-WAIT
            return answer(503, {'error': 'unavailable', 'detail': f'the database could not be reached: {error}',
                                LONG_POLL: {'waited_s': round(time.monotonic() - began, 3), 'ready': False}})
        # FAST-SWAP-PROBE: the Lambda version serving the call, so a pointer swap (DEP8b) is visible from outside.
        said = {'ok': ok, 'service': 'tower-port',
                'version': os.environ.get('AWS_LAMBDA_FUNCTION_VERSION', 'local'), 'probe': 18}
        if 'migration' in (event.get('rawQueryString') or ''):  # SLOW-PATH-NO-ROLLOUT-WAIT: only when asked (deploy.sh)
            said['migration'] = db.rows(MIGRATION)[0][0]
        if span is not None:
            said[LONG_POLL] = {'waited_s': round(time.monotonic() - began, 3), 'ready': ok}
        return answer(200, said)
    token = headers.get('authorization', '').removeprefix('Bearer ').strip()
    try:
        body = json.loads(event.get('body') or '{}')
    except ValueError:
        return answer(400, {'error': 'the body is not JSON'})
    if method == 'GET' and isinstance(body, dict) and event.get('queryStringParameters'):
        body = {**event['queryStringParameters'], **body}  # DEPLOY-CANARY: a GET's query is its body (wait_s, seen)
    for verb, pattern, act in ROUTES:
        found = re.fullmatch(pattern, path)
        if found and verb == method:
            try:
                who = port.caller(db, token, installation_sha256)
                result = act(db, who, body, **found.groupdict())
            except Exception as error:  # noqa: BLE001 - every refusal answers with its status, the rest with 500
                status = status_of(error)
                if status is None:
                    raise
                return answer(status, {'error': str(error).splitlines()[0][:500]})
            made = verb == 'POST' and path.count('/') <= 2 and not (isinstance(result, dict) and
                                                                     result.get('created') is False)
            return answer(201 if made else 200, result if result is not None else {'ok': True})
    return answer(404, {'error': f'no route {method} {path}'})


_connection = None
# PORT-COLD-START: what the environment's connection cost to open and when ({'ms', 'at': 'init' | 'call'}), the calls it
# has answered, and the handler the Lambda of the port is configured with (40-port.json)
_opened = None
_calls = 0
_init = {}  # PORT-COLD-SPLIT: what the init's attempt cost apart: {'driver_ms'} and, when it opened nothing, {'failed', 'ms'}
HANDLER = 'tower_infra.http_port.handler'
LOGIN_PHASES = ('tcp', 'tls', 'auth', 'start')  # PORT-LOGIN-PHASES: database.PHASES, said here without importing it
WARM_TIMEOUT_S = 3  # of the init's 10 s: a database that does not answer by then leaves the connection to the first call


def forget_connection():
    global _connection
    _connection = None


class Unreachable(RuntimeError):
    """PORT-503-NO-DATABASE: the Lambda could not open its connection (the database at its connections' limit, or away)."""


class Lazy:
    """rows(sql, params) on the Lambda's one connection, opened by the first call that needs the database and kept
    between calls: a call with no route or no token answers without it, so a cold start never pays the connection for
    a refusal (the Torre's reading of 04/11 17:2x BRT: a first call answered 503)."""

    def __init__(self, connect, wrap, phases=None):
        self.connect, self.wrap, self.phases = connect, wrap, {} if phases is None else phases

    def open(self, at='call', **options):
        """PORT-COLD-START: the connection, opened and timed; options are the connect's (the init's timeout).
        PORT-LOGIN-PHASES: and where the login's time went (self.phases, which the connect fills: seconds by part)."""
        global _connection, _opened
        began = time.monotonic()
        self.phases.clear()
        _connection = self.connect(**options)
        _opened = {'ms': round((time.monotonic() - began) * 1000, 1), 'at': at,
                   'phases': {name: round(seconds * 1000, 1) for name, seconds in self.phases.items()}}

    def rows(self, sql, params=None):
        if _connection is None or _connection.closed:
            try:
                self.open()
            except Exception as error:  # noqa: BLE001 - said as what it is: the handler answers 503, not a bare 500
                said = str(error).strip().splitlines()[-1:] or ['']
                raise Unreachable(f"{type(error).__name__}: {said[0].rpartition('FATAL:')[2].strip()[:200]}") from error
        return self.wrap(_connection).rows(sql, params)

    @staticmethod
    def broken():
        return _connection is not None and _connection.closed


def lazy_database(user='tower_service', role='port'):
    """The Lambda's one database, opened by IAM token on the first statement and kept between invocations.
    DB-LISTEN-ONE: named tower-<role>:call (a long poll's listener: wait)."""
    from . import database
    # PORT-LOGIN-PHASES: of the port's calls' connection only (a long poll's listener is not the one a call waits for,
    # and the consumer answers nobody with a Server-Timing: its login stays the driver's own)
    phases = {}
    return Lazy(lambda purpose='call', **options: database.iam_connection(
        database.settings(role=role), user, purpose=purpose,
        phases=phases if (role, purpose) == ('port', 'call') else None, **options), database.Database, phases)


def warm(environ=None):
    """PORT-COLD-START: the Lambda of the port opens its connection while its environment initializes (this module's
    load), not in its first call. The first call of an environment paid the driver's import, the IAM token, the TLS and
    the login to the database with the share of a CPU its 256 MB give a call; the init has the whole init phase for it
    and a call that arrives finds the connection kept, as a warm one does. Only under the port's own handler (the other
    Lambdas import this module for its routes and keep no connection here; a test, a process of the service: nothing).
    A database that does not answer in WARM_TIMEOUT_S, or refuses, leaves it to the first call, which says 503 if it
    cannot either. Answers whether it opened one. Never raises."""
    environ = os.environ if environ is None else environ
    if environ.get('_HANDLER') != HANDLER or _connection is not None:
        return False
    began = time.monotonic()
    try:
        # PORT-COLD-SPLIT: the driver's import apart from the login (live 11/11: 1.0 s of an init was `connect`, and
        # nothing said how much of it was the import), and an attempt that opened nothing said with its time and error
        driver(environ)
        _init['driver_ms'] = round((time.monotonic() - began) * 1000, 1)
        lazy_database(environ.get('TOWER_DB_USER', 'tower_service')).open('init', connect_timeout=WARM_TIMEOUT_S)
    except Exception as error:  # noqa: BLE001
        _init.update(failed=type(error).__name__, ms=round((time.monotonic() - began) * 1000, 1))
        print(f'port: the init could not open the connection ({type(error).__name__}); the first call opens it')
        return False
    return True


def driver(environ=None):
    """The database driver, imported (the connection imports it too: here its time is its own)."""
    from . import database
    database.driver()


def timed(said, began, first, clock=time.monotonic):
    """PORT-COLD-START: what the call cost, in the answer's Server-Timing: handler (this call's milliseconds in the
    Lambda); on an environment's first call, cold (the module's load, the init's connection included), driver (the
    driver's import, of that load) and init-failed (an init that opened nothing: its seconds and the error's type); and
    connect, on the call that first answers after the connection opened (desc: init or call), followed by the login's
    parts (PORT-LOGIN-PHASES: tcp, tls, auth, start; what is left of connect is the token and the driver's own work).
    The rest of a call's wall time is outside the handler: the Lambda's own start, the API and the network."""
    if not isinstance(said, dict) or 'statusCode' not in said:
        return said
    parts = [f'handler;dur={(clock() - began) * 1000:.1f}']
    if first:
        parts.append(f'cold;dur={_LOAD_MS:.1f}')
        if 'driver_ms' in _init:  # PORT-COLD-SPLIT: of the init: the driver's import, and an attempt that failed
            parts.append(f"driver;dur={_init['driver_ms']:.1f}")
        if 'failed' in _init:
            parts.append(f"init-failed;dur={_init['ms']:.1f};desc=\"{_init['failed']}\"")
    if _opened is not None and not _opened.get('said'):
        parts.append(f"connect;dur={_opened['ms']:.1f};desc=\"{_opened['at']}\"")
        # PORT-LOGIN-PHASES: of that connect, the login's parts (database.login): tcp, tls, auth, start
        parts.extend(f"{name};dur={_opened['phases'][name]:.1f}" for name in LOGIN_PHASES if name in _opened.get('phases', {}))
        _opened['said'] = True
    said.setdefault('headers', {})['server-timing'] = ', '.join(parts)
    return said


def handler(event, context):
    """The Lambda: one connection by IAM token, opened by its init (warm) or by the first call that needs it, and again
    after it breaks. PORT-COLD-START: every answer says what the call cost (timed)."""
    global _calls
    began, first = time.monotonic(), not _calls
    _calls += 1
    return timed(answered(event), began, first)


def answered(event):
    lazy = lazy_database(os.environ.get('TOWER_DB_USER', 'tower_service'))
    for attempt in (0, 1):
        try:
            return handle(event, lazy, os.environ.get('TOWER_INSTALLATION_TOKEN_SHA256', ''))
        except Unreachable as error:
            # PORT-503-NO-DATABASE: no statement ran, so the call may be sent again, and 503 says so: the gate's client
            # tries a 503 again and gives a delivery up on a 500 (live 11/11 22:17 to 22:21 UTC: the database at its
            # connections' limit, API Gateway's bare 500 on every route, and two deliveries ended on it)
            if attempt:
                return answer(503, {'error': 'unavailable', 'detail': f'the database could not be reached: {error}'})
        except Exception:
            if attempt or not lazy.broken():
                raise
            forget_connection()
    return answer(500, {'error': 'unreachable'})


warm()
_LOAD_MS = round((time.monotonic() - _LOADING) * 1000, 1)
