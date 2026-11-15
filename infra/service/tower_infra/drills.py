"""DRILLS (the Torre, 13/11 ~16:20 BRT: what waits for an incident is provoked, under control, and proved): the drill the
live service runs when the installation (or the configuration tenant) asks the port.

  - POST /v1/deploy/drills {kind: lambda-rollback[, function]}: the rollback of a port Lambda rehearsed. The live alias of
    the function (tower-port-api by default) is moved to the version before the one it names and back, each move the
    same pointer write a fast deploy's rollback is (fastdeploy.FastDeploy.rollback), each waited until the alias answers
    that version healthy (fastdeploy's propagate). Said: rollback_ms, rollback_propagation_ms, forward_ms,
    forward_propagation_ms. Whatever fails on the way, the alias is put back on the version it named.
  - GET /v1/deploy/drills/<id>: its newest state.
Each ask is one event platform.deploy.drill {id, state: asked, kind, ...} and a NOTIFY of tower_deploy; the live service
takes each once (taken) and says done {...} or failed {why}. GATE-LOOKS-GONE (D-316): the runner-placement drill left with
the RUNNER-ON-DEMAND look it provoked.
"""
import json
import logging
import time

LOG = logging.getLogger('tower_infra.drills')
EVENT = 'platform.deploy.drill'
KINDS = ('lambda-rollback',)
FUNCTIONS = ('tower-port-api',)  # GATE-SHUTDOWN (#17): the webhook consumer and the ack-ingress left the port stack
ASKED_S = 600
SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"select %(event)s, null, '{EVENT}', clock_timestamp(), %(producer)s, 'deploy/drill', %(payload)s::jsonb "
       "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
       f"where not exists (select 1 from log.event where event_id = %(event)s and type = '{EVENT}' "
       "and occurred_at > now() - interval '1 day') returning type) "
       "select said.type from said cross join lateral (select pg_notify('tower_deploy', said.type)) n")
NEWEST = (f"select payload::text from log.event where type = '{EVENT}' and tenant_id is null "
          "and occurred_at > now() - interval '1 day' and payload->>'id' = %(id)s order by occurred_at desc limit 1")
OPEN = (f"select a.payload::text from log.event a where a.type = '{EVENT}' and a.tenant_id is null "
        "and a.payload->>'state' = 'asked' and a.occurred_at > clock_timestamp() - make_interval(secs => %(asked_s)s::float8) "
        f"and not exists (select 1 from log.event t where t.type = '{EVENT}' and t.tenant_id is null "
        "and t.payload->>'id' = a.payload->>'id' and t.payload->>'state' <> 'asked') order by a.occurred_at")


def say(db, ident, state, producer, **more):
    return bool(db.rows(SAY, {'event': f'{EVENT}:{ident}:{state}', 'producer': producer,
                              'payload': json.dumps({'id': ident, 'state': state, **more})}))


def ask(db, who, body, clock=time.time_ns, configured=None):
    """POST /v1/deploy/drills: a drill asked of the live service (the installation or the configuration tenant)."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    body = body or {}
    kind = str(body.get('kind') or '')
    function = str(body.get('function') or 'tower-port-api')
    if kind not in KINDS or (kind == 'lambda-rollback' and function not in FUNCTIONS):
        raise port.PortError(400, f'kind is one of {", ".join(KINDS)}; a lambda-rollback names one of {", ".join(FUNCTIONS)}')
    ident = str(clock())
    say(db, ident, 'asked', port.PRODUCER, kind=kind, **({'function': function} if kind == 'lambda-rollback' else {}))
    return {'id': ident, 'state': 'asked'}


def state(db, who, ident, configured=None):
    """GET /v1/deploy/drills/<id>: its newest state (404 for none in a day)."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    found = db.rows(NEWEST, {'id': str(ident)})
    if not found:
        raise port.PortError(404, 'no such drill')
    return json.loads(found[0][0]) if isinstance(found[0][0], str) else found[0][0]


class Drills:
    """The live service's half: each asked drill done once."""

    def __init__(self, fast, clock=time.monotonic):
        self.fast, self.clock = fast, clock  # fast: a fastdeploy.FastDeploy (its Lambda client, invoke and propagate)

    def lambda_rollback(self, function):
        lam = self.fast.lam
        current = str(lam.get_alias(FunctionName=function, Name='live')['FunctionVersion'])
        if not current.isdigit() or int(current) < 2:
            raise RuntimeError(f'the alias names {current}: no published version before it')
        previous = str(int(current) - 1)
        said, entry = {'function': function, 'current': current, 'previous': previous, 'rollback_healthy': False,
                       'rollback_propagated': False}, {}
        try:
            began = self.clock()
            lam.update_alias(FunctionName=function, Name='live', FunctionVersion=previous)
            said['rollback_ms'] = round((self.clock() - began) * 1000, 1)
            why = self.fast.propagate(function, previous, entry)
            said.update(rollback_propagation_ms=entry.get('propagation_ms'), rollback_propagated=bool(entry.get('propagated')),
                        rollback_healthy=why is None)
        finally:  # the alias back on the version it named, whatever happened
            began = self.clock()
            lam.update_alias(FunctionName=function, Name='live', FunctionVersion=current)
            said['forward_ms'] = round((self.clock() - began) * 1000, 1)
        entry = {}
        why = self.fast.propagate(function, current, entry)
        said.update(forward_propagation_ms=entry.get('propagation_ms'), forward_propagated=bool(entry.get('propagated')),
                    forward_healthy=why is None)
        said['ok'] = all(said[key] for key in ('rollback_healthy', 'rollback_propagated', 'forward_healthy', 'forward_propagated'))
        return said

    def step(self, db):
        done = 0
        for (payload,) in db.rows(OPEN, {'asked_s': ASKED_S}):
            asked = json.loads(payload) if isinstance(payload, str) else payload
            if not say(db, asked['id'], 'taken', 'tower-service'):
                continue
            try:
                said = self.lambda_rollback(asked.get('function') or 'tower-port-api')
            except Exception as error:  # noqa: BLE001 - said; the next ask tries again
                say(db, asked['id'], 'failed', 'tower-service', why=f'{type(error).__name__}: {error}'[:300])
                LOG.warning('drills: %s failed: %s', asked.get('kind'), error)
                continue
            say(db, asked['id'], 'done', 'tower-service', kind=asked.get('kind'), **said)
            LOG.info('drills: %s done: %s', asked.get('kind'), said)
            done += 1
        return done

