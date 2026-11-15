"""RUNNER-ON-DEMAND (the review's finding 3; the Torre's approval of 13/11 ~14:15 BRT, ~US$ 1 a month): the runner on
Fargate on demand only while Spot cannot place it.

The runner is one task of the ECS service tower-runner on FARGATE_SPOT. Spot taking the task back is covered (SPOT-KEEP:
the process keeps taking runs until the task ECS starts in its place says it is up); Spot having no capacity for that
replacement is not: ECS says SERVICE_TASK_PLACEMENT_FAILURE (an ECS Service Action, platform.ecs.service_action in the
log, the bootstrap's rule tower-ecs-service-action) and tries again, and the engine has no runner meanwhile. ECS does
not fall from one capacity provider to another. So the live service's look:
  - at a placement failure of tower-runner, with no fallback of its own running, runs one task of the same task
    definition (tower-runner: the image, the code and the role the service's tasks have) on FARGATE, on demand, in the
    tasks' network; it starts like the replacement ECS could not place, and says platform.deploy.ondemand {started};
  - once a runner task other than it says it is up (platform.deploy.task_up, role runner, another host: Spot placed
    the service's task again), it stops its task (a stop is Spot's warning to the runner's process: SPOT-KEEP hands the
    runs over, the one up already) and says {stopped}; a task of its own that ended without it says {ended};
  - a service that starts again reads its open fallback back from the log, so a reload does not leave one running.
Every step by an event of ECS or of the runner; the look's fallback wait is the other looks'.

GATE-SHUTDOWN (14/11/2026, D-314; #17, #22): this look served the AWS gate on Origin, which is shut down (the gate is
GitHub's tower/gate and its merge queue): serve() starts it only under service.gate_looks, false by default. Its code
stays whole, so a row of work.config_value turns it back on at the next start.

This module runs in the service alone: no port Lambda's package holds it (scripts/lib/deploy_classify.LAMBDA_MODULES),
so a change here is a code-only merge of the service (QUEUE-SWAP: its heir is up before the landing).
"""
import json
import logging
import time

LOG = logging.getLogger('tower_infra.ondemand')
EVENT = 'platform.deploy.ondemand'
SERVICE, FAMILY, CONTAINER, STARTED_BY = 'tower-runner', 'tower-runner', 'runner', 'ondemand'
PLACEMENT = 'SERVICE_TASK_PLACEMENT_FAILURE'
FAILED = ("select extract(epoch from occurred_at)::float8, payload->>'drill' from log.event where type = 'platform.ecs.service_action' "
          "and tenant_id is null and occurred_at > to_timestamp(%(since)s::float8) and payload->>'name' = %(name)s "
          "and payload->'services' ? %(service)s order by occurred_at desc limit 1")
UP = ("select payload->>'task' from log.event where type = 'platform.deploy.task_up' and tenant_id is null "
      "and payload->>'role' = 'runner' and occurred_at > to_timestamp(%(since)s::float8) and split_part(payload->>'task', '.', 1) <> %(host)s "
      "order by occurred_at desc limit 1")
# DRILLS: the fallback's own task said it is up (a drill stops it then: Spot placed the runner all along)
OWN_UP = ("select extract(epoch from occurred_at)::float8 from log.event where type = 'platform.deploy.task_up' "
          "and tenant_id is null and payload->>'role' = 'runner' and occurred_at > to_timestamp(%(since)s::float8) "
          "and split_part(payload->>'task', '.', 1) = %(host)s order by occurred_at limit 1")
OPEN = (f"select payload::text from log.event where type = '{EVENT}' and tenant_id is null "
        "and occurred_at > now() - interval '7 days' order by occurred_at desc limit 1")
SAY = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"select %(id)s, null, '{EVENT}', clock_timestamp(), 'ondemand', 'deploy/ondemand', %(payload)s::jsonb "
       f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{EVENT}')")
ENDED = ('STOPPED', 'DEPROVISIONING', 'STOPPING')


def host_of(task):
    """The host a runner's process says it is on (platform.deploy.task_up's task), from DescribeTasks' ENI: its first
    label (ip-a-b-c-d), which the queries compare with the first label of the task's name, whatever the DNS suffix."""
    for attachment in task.get('attachments') or []:
        for detail in attachment.get('details') or []:
            if detail.get('name') == 'privateIPv4Address' and detail.get('value'):
                return 'ip-' + detail['value'].replace('.', '-')
    return None


class OnDemand:
    def __init__(self, ecs, cluster, network, clock=time.time):
        self.ecs, self.cluster, self.network, self.clock = ecs, cluster, network, clock
        self.since, self.task, self.started, self.host, self.read, self.drill = None, None, None, None, False, None

    def say(self, db, state, **more):
        payload = {'state': state, 'task': self.task, **more}
        db.rows(SAY, {'id': f'{EVENT}:{self.task}:{state}', 'payload': json.dumps(payload)})
        LOG.info('ondemand: %s %s %s', state, self.task, more)

    def recover(self, db):
        """A service that starts again: the fallback the log says started and never ended is this look's."""
        self.read = True
        row = db.rows(OPEN)
        said = json.loads(row[0][0]) if row else {}
        if said.get('state') == 'started' and said.get('task'):
            self.task, self.started, self.drill = said['task'], float(said.get('at') or self.clock()), said.get('drill')

    def step(self, db):
        if not self.read:
            self.recover(db)
        since = self.since if self.since is not None else self.clock() - 120.0
        self.since = self.clock()
        if self.task is None:
            failed = db.rows(FAILED, {'since': since, 'name': PLACEMENT, 'service': SERVICE})
            return self.run(db, failed[0][0], failed[0][1] if len(failed[0]) > 1 else None) if failed else None
        return self.follow(db)

    def run(self, db, at, drill=None):
        try:
            out = self.ecs.run_task(
                cluster=self.cluster, taskDefinition=FAMILY, count=1, platformVersion='LATEST',
                capacityProviderStrategy=[{'capacityProvider': 'FARGATE', 'weight': 1}],
                networkConfiguration={'awsvpcConfiguration': self.network}, startedBy=STARTED_BY,
                tags=[{'key': 'project', 'value': 'tower'}, {'key': 'role', 'value': 'runner'},
                      {'key': 'ondemand', 'value': 'spot-placement-failure'}])
            if not out.get('tasks'):
                raise RuntimeError(f"no task: {out.get('failures')}")
        except Exception as error:  # noqa: BLE001 - the next placement failure tries again
            LOG.error('ondemand: RunTask of the on-demand runner failed: %s', error)
            return 'refused'
        self.task, self.started, self.host, self.drill = out['tasks'][0]['taskArn'], self.clock(), None, drill
        self.say(db, 'started', at=self.started, failure_at=at, **({'drill': drill} if drill else {}))
        return 'started'

    def follow(self, db):
        """The fallback's task: its host once ECS gives it, its end, and Spot's runner back (then it is stopped)."""
        try:
            found = (self.ecs.describe_tasks(cluster=self.cluster, tasks=[self.task]).get('tasks') or [None])[0]
        except Exception as error:  # noqa: BLE001 - the next look reads it again
            LOG.warning('ondemand: DescribeTasks of %s failed: %s', self.task, error)
            return None
        if found is None or found.get('lastStatus') in ENDED:
            self.say(db, 'ended', why=(found or {}).get('stoppedReason') or 'gone')
            self.task = self.host = None
            return 'ended'
        self.host = self.host or host_of(found)
        if not self.host:
            return None
        if self.drill:  # DRILLS: Spot placed the runner all along: the fallback is stopped once it said it is up
            up = db.rows(OWN_UP, {'since': self.started, 'host': self.host})
            if not up:
                return None
            more, reason = {'drill': self.drill, 'up_s': round(float(up[0][0]) - self.started, 1)}, 'DRILLS: the drill is over'
        else:
            back = db.rows(UP, {'since': self.started, 'host': self.host})
            if not back:
                return None
            more, reason = {'spot': back[0][0]}, 'RUNNER-ON-DEMAND: Spot placed the runner again'
        try:
            self.ecs.stop_task(cluster=self.cluster, task=self.task, reason=reason)
        except Exception as error:  # noqa: BLE001 - the next look stops it
            LOG.warning('ondemand: StopTask of %s failed: %s', self.task, error)
            return None
        self.say(db, 'stopped', **more)
        self.task = self.host = self.drill = None
        return 'stopped'


def start(scope, stop, wait, active=None, environ=None, make=None):
    """The look in a daemon thread (the live service's alone); None without the cluster and network (a local run). Its ECS
    client is made at its first active look (LOOKS-AFTER-WORK: a process the role waits for makes none on the swap)."""
    import os
    import threading
    from . import prewarm
    environ = os.environ if environ is None else environ
    if make is None and not prewarm.configured(environ):
        LOG.info('ondemand: off (no cluster or network to run a task in)')
        return None

    def made():
        found = prewarm.from_boto3(scope, environ=environ)
        return None if found is None else OnDemand(found.ecs, found.cluster, found.network)
    look = None

    def loop():
        nonlocal look
        while not stop.is_set():
            if active is None or active():
                try:
                    look = look or (make or made)()
                    if look is None:
                        return
                    with scope() as db:
                        look.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('ondemand: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='ondemand', daemon=True)
    thread.start()
    return thread
