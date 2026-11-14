"""RUNNER-STALL-ALERT (docs/operations/aws-revisao-arquitetura.md, findings 2 and 3): the service watches the runner.

The runner is one Fargate Spot task. When Spot cannot place it, or it is up and takes nothing, the service goes on
dispatching: runs are handed over (work.run `starting`) and no one takes them; each waits out its lease (5 minutes), is
reaped and handed over again, and a delivery just waits. Nothing said so: the deploy's canary runs only at a deploy, and
the service is the only role that may publish to the platform's topic.

Watch.beat(db), on the live service's heartbeat, reads the runs handed over to the runner's adapter and not taken, and
the age of the oldest (one statement on the partial index run_starting). Past service.runner_stall_alert_s (a runner
task the rollout replaced warms for about a minute, and a run handed over is taken within a second) the service records
platform.runner.stalled {state: stalled, runs, oldest_s, limit_s} (the configuration tenant's, so the port's log query
reads it) and publishes it to the platform's topic; when none is left past the limit, {state: recovered}. Once per change
of state of a process. Never raises.

DISPATCH-STALL-ALERT (the review's finding 32): a service that stands by watches the dispatch. On 11/11 20:41 UTC the
process that had the service's role became a strict standby with no pointer; for 7.7 minutes nobody dispatched and
nothing said so: the ECS health check is green for a standby, the watch above runs in the live service (there was none)
and the port went on accepting jobs. Idle.beat(db), on the heartbeat of a service process that is not live, reads the jobs
a dispatcher would start now: the first candidates of each queue (work.candidates: no open dependency, their time come,
their exclusive key free) whose route has a free slot they may take (mechanisms.ACCOUNT's rule). A live dispatcher starts
such a job on its next tick, so the same job found ready for service.dispatch_stall_alert_s is a dispatch that is not
running, whatever the reason; the process records platform.dispatch.stalled {state: stalled, jobs, oldest_s, limit_s,
task} and publishes it (a standby is a process of the service's task: the role that may publish), and {state: recovered}
when none is left that old. It changes nothing: a strict standby's code may not have landed, so it never takes the role.
"""
import json
import logging
import time
import uuid

from . import canary, config_data, mechanisms

LOG = logging.getLogger('tower_infra.stall')
EVENT = 'platform.runner.stalled'
LIMIT = 'service.runner_stall_alert_s'
WAITING = ("select count(*), coalesce(extract(epoch from clock_timestamp() - min(uuid_extract_timestamp(r.id))), 0)::float8 "
           "from work.run r join work.executor e on e.name = r.executor where r.state = 'starting' and e.adapter = %(adapter)s")
RECORD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          f"select %(id)s, t.id, '{EVENT}', clock_timestamp(), 'tower-service', 'runner', %(payload)s::jsonb "
          "from work.tenant t where t.name = %(tenant)s")
SUBJECTS = {True: 'tower runner: runs are handed over and not taken', False: 'tower runner: taking runs again'}


class Watch:
    """The live service's watch of the runner. config: the service's settings (get(name), tenant); publish(said,
    subject=) sends the alert; adapter: the runner's (runner.Runner's default)."""

    def __init__(self, config, publish=canary.alert, adapter='container'):
        self.config, self.publish, self.adapter, self.stalled = config, publish, adapter, False
        self.tenant = getattr(config, 'tenant', config_data.TENANT)

    def beat(self, db):
        try:
            runs, oldest = db.rows(WAITING, {'adapter': self.adapter})[0]
            limit = float(self.config.get(LIMIT))
            late = float(oldest) >= limit
            if late == self.stalled:
                return None
            said = {'state': 'stalled' if late else 'recovered', 'runs': int(runs), 'oldest_s': round(float(oldest), 1),
                    'limit_s': limit}
            db.rows(RECORD, {'id': f'{EVENT}:{uuid.uuid4()}', 'tenant': self.tenant, 'payload': json.dumps(said)})
            self.stalled = late
            (LOG.warning if late else LOG.info)('stall: %s', json.dumps(said, sort_keys=True))
            self.publish(said, subject=SUBJECTS[late])
            return said
        except Exception:  # noqa: BLE001
            LOG.exception('stall: the runs handed over were not read')
            return None


IDLE_EVENT = 'platform.dispatch.stalled'
IDLE_LIMIT = 'service.dispatch_stall_alert_s'
READY_SCAN = 5  # the candidates read of each queue: the ones a dispatcher starts first
READY = ("select c.id::text from (select distinct tenant_id, queue from work.job where state = 'queued') q "
         f"cross join lateral work.candidates(q.tenant_id, q.queue, {READY_SCAN}) c(id) join work.job j on j.id = c.id "
         "where exists (select 1 from work.capacity k where k.executor = work.route(c.id) and k.in_use < k.slots "
         f"and (k.account <> '{mechanisms.RESERVED}' or j.selector->>'account' = '{mechanisms.RESERVED}')) limit 20")
IDLE_RECORD = RECORD.replace(f"'{EVENT}'", f"'{IDLE_EVENT}'").replace("'runner'", "'dispatch'")
IDLE_SUBJECTS = {True: 'tower service: jobs are ready and nobody dispatches them', False: 'tower service: dispatching again'}


class Idle:
    """A standing-by service process's watch of the dispatch. config: the service's settings (get(name), tenant);
    publish(said, subject=) sends the alert; task: the process's name, said in the event."""

    def __init__(self, config, publish=canary.alert, task=None, clock=time.monotonic):
        self.config, self.publish, self.task, self.clock = config, publish, task, clock
        self.seen, self.stalled = {}, False
        self.tenant = getattr(config, 'tenant', config_data.TENANT)

    def beat(self, db):
        try:
            now = self.clock()
            ready = [row[0] for row in db.rows(READY)]
            self.seen = {job: self.seen.get(job, now) for job in ready}  # since when this process finds each one ready
            oldest = max((now - since for since in self.seen.values()), default=0.0)
            limit = float(self.config.get(IDLE_LIMIT))
            late = oldest >= limit
            if late == self.stalled:
                return None
            said = {'state': 'stalled' if late else 'recovered', 'jobs': len(ready), 'oldest_s': round(oldest, 1),
                    'limit_s': limit, 'task': self.task}
            db.rows(IDLE_RECORD, {'id': f'{IDLE_EVENT}:{uuid.uuid4()}', 'tenant': self.tenant, 'payload': json.dumps(said)})
            self.stalled = late
            (LOG.warning if late else LOG.info)('stall: dispatch %s', json.dumps(said, sort_keys=True))
            self.publish(said, subject=IDLE_SUBJECTS[late])
            return said
        except Exception:  # noqa: BLE001
            LOG.exception('stall: the jobs ready to be dispatched were not read')
            return None
