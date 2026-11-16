"""The port of the infrastructure (P3 F2; ARQUITETURA-ALVO §5): the same commands and queries for any management system
and any worker, with the database as the only state (D-309).

A caller is the installation (its token's sha256 is the installation's, given at deploy) or a tenant (its token's
sha256 is the one the installation registered with it); everything a tenant does and reads is its own. Each command is
one statement that writes its rows and the event it causes together, so the log never misses a transition and a
transition never happens without its event (§3); identifiers are UUIDv7 from the database. Values travel as named
parameters, never inside the SQL. The database is any object with rows(sql, params) -> list of tuples: psycopg in the
Lambda, psql in the gate's test. Standard library only.
"""
import hashlib
import hmac
import json
import os
import re
import time

from . import config_data, subscriptions

PRODUCER = 'port'
TOKEN = re.compile(r'^[0-9a-f]{64}$')
NAME = re.compile(r'^[a-z][a-z0-9-]{1,39}$')
FILTER_COLUMNS = {'type', 'subject', 'correlation_id', 'causation_id', 'producer'}
GROUP_COLUMNS = {'type', 'subject', 'producer', 'correlation_id'}
JOB_FIELDS = ('queue', 'rank', 'not_before', 'deadline', 'executor', 'selector', 'max_attempts', 'backoff_initial',
              'backoff_factor', 'backoff_max', 'retry_on', 'non_retryable', 'input_uri', 'input_digest',
              'idempotency_key', 'exclusive_key', 'memoize')
CASTS = {'rank': 'numeric', 'not_before': 'timestamptz', 'deadline': 'timestamptz', 'selector': 'jsonb',
         'max_attempts': 'int', 'backoff_initial': 'interval', 'backoff_factor': 'numeric', 'backoff_max': 'interval',
         'retry_on': 'text[]', 'non_retryable': 'text[]', 'memoize': 'boolean'}


class PortError(Exception):
    """A refusal with the HTTP status that names it."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def sha256(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def caller(db, token, installation_sha256):
    """('installation', None) or ('tenant', tenant id) for a bearer token; a refusal for any other."""
    if not token:
        raise PortError(401, 'no token')
    digest = sha256(token)
    if installation_sha256 and hmac.compare_digest(digest, installation_sha256):
        return 'installation', None
    found = db.rows("select id::text from work.tenant where token_sha256 = %(digest)s and state = 'active'",
                    {'digest': digest})
    if not found:
        raise PortError(401, 'unknown token')
    return 'tenant', found[0][0]


def event_sql(kind, key, subject, payload, tenant='created.tenant_id', source='created'):
    """The insert of one event from the rows a statement just wrote. Its id is the transition's own (the kind and a
    key from the row: an id, an id and its version, or the values it set), so the same transition is the same event
    (§5) and a reader can drop a repeat."""
    return (f"logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            f"select '{kind}:' || {key}, {tenant}, '{kind}', clock_timestamp(), '{PRODUCER}', {subject}, {payload} "
            f"from {source})")


def installation_only(who):
    if who[0] != 'installation':
        raise PortError(403, 'only the installation may do this')


def tenant_only(who):
    if who[0] != 'tenant':
        raise PortError(403, 'only a tenant may do this')
    return who[1]


def register_tenant(db, who, name, token_sha256):
    installation_only(who)
    if not NAME.match(name or '') or not TOKEN.match(token_sha256 or ''):
        raise PortError(400, 'a tenant needs a name and the sha256 of its token')
    return db.rows("with created as (insert into work.tenant (name, token_sha256) values (%(name)s, %(token)s) "
                   "returning id, id as tenant_id, name), "
                   + event_sql('platform.tenant.registered', 'created.id', "'tenant/' || created.name",
                               "jsonb_build_object('tenant', created.name)")
                   + " select id::text from created", {'name': name, 'token': token_sha256})[0][0]


def set_config(db, who, key, value, reason):
    """DEP9: a behaviour key of the service as data. The value must have the key's registry type; the row is versioned
    with the actor (the tenant's name) and the reason, and platform.config.changed {name, old, new, version} is logged (log.observed_type admits only the platform. family; the registry's config.changed stays the git path's) with it;
    the table's trigger notifies tower_config, so the service's readers refresh on the event."""
    tenant = tenant_only(who)
    if key not in config_data.SPEC:
        raise PortError(404, f'{key} is not a configurable key')
    if not isinstance(reason, str) or not reason.strip():
        raise PortError(400, 'a config change needs a reason')
    try:
        value = config_data.validate(key, value)
    except ValueError as error:
        raise PortError(400, str(error)) from error
    done = db.rows("with old as (select value from work.config_value where tenant_id = %(tenant)s::uuid and key = %(key)s), "
                   "created as (insert into work.config_value (tenant_id, key, value, actor, reason) select "
                   "%(tenant)s::uuid, %(key)s, %(value)s::jsonb, t.name, %(reason)s from work.tenant t "
                   "where t.id = %(tenant)s::uuid on conflict (tenant_id, key) do update set value = excluded.value, "
                   "version = work.config_value.version + 1, actor = excluded.actor, reason = excluded.reason, "
                   "updated_at = clock_timestamp() returning tenant_id, key, value, version, actor), "
                   + event_sql('platform.config.changed', "created.tenant_id || ':' || created.key || ':' || created.version",
                               "'config/' || created.key",
                               "jsonb_build_object('name', created.key, 'old', (select value from old), 'new', created.value, "
                               "'version', created.version, 'actor', created.actor, 'reason', %(reason)s::text, 'source', 'port')")
                   + " select version from created",
                   {'tenant': tenant, 'key': key, 'value': json.dumps(value), 'reason': reason.strip()})
    return {'key': key, 'value': value, 'version': int(done[0][0])}


def get_config(db, who, key):
    """The value the service reads for the key: the tenant's row, else the compiled default (source says which)."""
    tenant = tenant_only(who)
    if key not in config_data.SPEC:
        raise PortError(404, f'{key} is not a configurable key')
    found = db.rows("select value::text, version, actor, reason, updated_at::text from work.config_value "
                    "where tenant_id = %(tenant)s::uuid and key = %(key)s", {'tenant': tenant, 'key': key})
    if not found:
        return {'key': key, 'value': config_data.SPEC[key][1], 'source': 'default'}
    value, version, actor, reason, at = found[0]
    return {'key': key, 'value': json.loads(value), 'source': 'table', 'version': int(version), 'actor': actor, 'reason': reason,
            'updated_at': at}


def configure_executor(db, who, name, config):
    """An executor's configuration, set by whoever registered it: the installation's by the installation, a tenant's
    own by that tenant (P4 F2b: the forge executor maps the forge's installations to tenants)."""
    tenant = None if who[0] == 'installation' else who[1]
    if not isinstance(config, dict):
        raise PortError(400, "an executor's config is an object")
    done = db.rows("with created as (update work.executor set config = %(config)s::jsonb where name = %(name)s "
                   "and tenant_id is not distinct from %(tenant)s::uuid returning name, tenant_id), "
                   + event_sql('executor.configured', "created.name || ':' || md5(%(config)s::text)",
                               "'executor/' || created.name", "jsonb_build_object('executor', created.name)")
                   + " select name from created",
                   {'name': name, 'tenant': tenant, 'config': json.dumps(config, sort_keys=True)})
    if not done:
        raise PortError(404, f'no executor {name} of the caller')
    return {'ok': True}


def register_executor(db, who, name, adapter, config=None, capabilities=None):
    """The installation registers an executor every tenant may use; a tenant registers one only it may use."""
    tenant = None if who[0] == 'installation' else who[1]
    if not NAME.match(name or '') or not adapter:
        raise PortError(400, 'an executor needs a name and an adapter')
    db.rows("with created as (insert into work.executor (name, adapter, tenant_id, config, capabilities) "
            "values (%(name)s, %(adapter)s, %(tenant)s::uuid, %(config)s::jsonb, %(capabilities)s::jsonb) "
            "returning name, tenant_id), "
            + event_sql('executor.registered', 'created.name', "'executor/' || created.name",
                        "jsonb_build_object('executor', created.name, 'adapter', %(adapter)s::text)")
            + " select name from created",
            {'name': name, 'adapter': adapter, 'tenant': tenant, 'config': json.dumps(config or {}),
             'capabilities': json.dumps(capabilities or {})})
    return name


def set_capacity(db, who, executor, account, slots, resets_at=None):
    """The capacity of an executor the caller owns: its slots and the time its quota resets."""
    owned = db.rows('select tenant_id::text from work.executor where name = %(executor)s', {'executor': executor})
    if not owned or owned[0][0] != (None if who[0] == 'installation' else who[1]):
        raise PortError(404, f'no executor {executor} of this caller')
    db.rows("with created as (insert into work.capacity (executor, account, slots, resets_at) "
            "values (%(executor)s, %(account)s, %(slots)s::int, %(resets_at)s::timestamptz) "
            "on conflict (executor, account) do update set slots = excluded.slots, resets_at = excluded.resets_at "
            "returning executor, account, slots, resets_at), "
            + event_sql('capacity.set', "created.executor || ':' || created.account || ':' || created.slots || ':' || "
                        "coalesce(created.resets_at::text, '')", "'executor/' || created.executor", "jsonb_build_object('account', "
                        "created.account, 'slots', created.slots)", tenant='null::uuid')
            + " select executor from created",
            {'executor': executor, 'account': account, 'slots': slots, 'resets_at': resets_at})


def configure_queue(db, who, name, policy='fifo', config=None):
    tenant = tenant_only(who)
    db.rows("with created as (insert into work.queue (tenant_id, name, policy, config) "
            "values (%(tenant)s::uuid, %(name)s, %(policy)s, %(config)s::jsonb) "
            "on conflict (tenant_id, name) do update set policy = excluded.policy, config = excluded.config "
            "returning tenant_id, name, policy, config), "
            + event_sql('platform.queue.configured', "created.tenant_id || ':' || created.name || ':' || created.policy || ':' || "
                        "md5(created.config::text)", "'queue/' || created.name",
                        "jsonb_build_object('queue', created.name, 'policy', created.policy)")
            + " select name from created",
            {'tenant': tenant, 'name': name, 'policy': policy, 'config': json.dumps(config or {})})


def define_limit(db, who, scope, scope_id, meter, maximum, action, resets_at=None):
    """A limit of the tenant: stop, refuse, or wait (AWS12: held until resets_at, a window the limit carries)."""
    tenant = tenant_only(who)
    if action == 'wait' and not resets_at:
        raise PortError(400, 'a wait limit needs resets_at, the time its window ends')
    return db.rows("with created as (insert into work.limits (tenant_id, scope, scope_id, meter, maximum, action, "
                   "resets_at) values (%(tenant)s::uuid, %(scope)s, %(scope_id)s, %(meter)s, %(maximum)s::numeric, "
                   "%(action)s, %(resets_at)s::timestamptz) returning id, tenant_id, meter, maximum, action, resets_at), "
                   + event_sql('limit.defined', 'created.id', "'limit/' || created.id",
                               "jsonb_build_object('meter', created.meter, 'maximum', created.maximum, "
                               "'action', created.action, 'resets_at', created.resets_at)")
                   + " select id::text from created",
                   {'tenant': tenant, 'scope': scope, 'scope_id': scope_id, 'meter': meter, 'maximum': maximum,
                    'action': action, 'resets_at': resets_at})[0][0]


def change_limit(db, who, limit_id, fields):
    """Change a limit of the caller tenant (AWS12): fields maximum, resets_at, action, reset_used (zero the usage) or
    lift (end a wait window now and zero the usage, so held work goes on). Logs limit.changed, which wakes the
    dispatcher."""
    tenant = tenant_only(who)
    fields = fields or {}
    known = {'maximum', 'resets_at', 'action', 'reset_used', 'lift'}
    if not fields or set(fields) - known:
        raise PortError(400, f'a limit change takes some of {", ".join(sorted(known))}')
    sets, params = [], {'id': limit_id, 'tenant': tenant}
    if fields.get('lift'):
        sets += ['resets_at = clock_timestamp()', 'used = 0']
    if 'maximum' in fields:
        sets.append('maximum = %(maximum)s::numeric')
        params['maximum'] = fields['maximum']
    if 'resets_at' in fields:
        sets.append('resets_at = %(resets_at)s::timestamptz')
        params['resets_at'] = fields['resets_at']
    if 'action' in fields:
        sets.append('action = %(action)s')
        params['action'] = fields['action']
    if fields.get('reset_used'):
        sets.append('used = 0')
    if not sets:
        raise PortError(400, 'nothing to change')
    done = db.rows("with created as (update work.limits set " + ', '.join(sets) + " where id = %(id)s::uuid "
                   "and tenant_id = %(tenant)s::uuid returning id, tenant_id, meter, maximum, used, action, resets_at), "
                   + event_sql('limit.changed', "created.id || ':' || md5(created::text || clock_timestamp()::text)",
                               "'limit/' || created.id",
                               "jsonb_build_object('limit_id', created.id, 'meter', created.meter, "
                               "'maximum', created.maximum, 'used', created.used, 'action', created.action, "
                               "'resets_at', created.resets_at)")
                   + " select jsonb_build_object('id', id, 'maximum', maximum, 'used', used, 'action', action, "
                   "'resets_at', resets_at)::text from created", params)
    if not done:
        raise PortError(404, f'no limit {limit_id} of this tenant')
    return json.loads(done[0][0])


LIMIT_FIELDS = ("select jsonb_build_object('id', id, 'scope', scope, 'scope_id', scope_id, 'meter', meter, "
                "'maximum', maximum, 'used', used, 'action', action, 'resets_at', resets_at)::text from work.limits ")


def list_limits(db, who):
    """The caller tenant's own limits, never another tenant's."""
    tenant = tenant_only(who)
    return {'limits': [json.loads(row[0]) for row in db.rows(
        LIMIT_FIELDS + 'where tenant_id = %(tenant)s::uuid order by id', {'tenant': tenant})]}


def get_limit(db, who, limit_id):
    tenant = tenant_only(who)
    found = db.rows(LIMIT_FIELDS + 'where id = %(id)s::uuid and tenant_id = %(tenant)s::uuid',
                    {'id': limit_id, 'tenant': tenant})
    if not found:
        raise PortError(404, f'no limit {limit_id} of this tenant')
    return json.loads(found[0][0])


def define_meter_rate(db, who, meter, derived_meter, rate):
    tenant = tenant_only(who)
    db.rows("with created as (insert into work.meter_rate (tenant_id, meter, derived_meter, rate) "
            "values (%(tenant)s::uuid, %(meter)s, %(derived)s, %(rate)s::numeric) "
            "on conflict (tenant_id, meter, derived_meter) do update set rate = excluded.rate "
            "returning tenant_id, meter, derived_meter, rate), "
            + event_sql('limit.rate.defined', "created.tenant_id || ':' || created.meter || ':' || "
                        "created.derived_meter || ':' || created.rate", "'meter/' || created.meter",
                        "jsonb_build_object('meter', created.meter, 'derived_meter', created.derived_meter, "
                        "'rate', created.rate)")
            + " select meter from created",
            {'tenant': tenant, 'meter': meter, 'derived': derived_meter, 'rate': rate})


def create_job(db, who, spec, said=None):
    """A job of the caller's tenant; the same idempotency key answers the job it created first. said (DEPLOY-CANARY: the
    port's own callers, never a route's body) is added to the payload of job.created, which tags the job in the log."""
    tenant = tenant_only(who)
    fields = [field for field in JOB_FIELDS if spec.get(field) is not None]
    if not {'input_uri', 'input_digest'} <= set(fields):
        raise PortError(400, 'a job needs input_uri and input_digest')
    params = {'tenant': tenant, **{field: encode(field, spec[field]) for field in fields}}
    values = ', '.join(f"%({field})s::{CASTS.get(field, 'text')}" for field in fields)
    depends = spec.get('depends_on') or []
    params['depends'] = json.dumps([item if isinstance(item, dict) else {'job': item} for item in depends])
    created = db.rows(
        f"with created as (insert into work.job (tenant_id, {', '.join(fields)}) values (%(tenant)s::uuid, {values}) "
        "on conflict (tenant_id, idempotency_key) do nothing returning id, tenant_id), "
        "waits as (insert into work.dependency (tenant_id, job_id, depends_on, condition) "
        "select created.tenant_id, created.id, (item->>'job')::uuid, coalesce(item->>'condition', 'succeeded') "
        "from created, jsonb_array_elements(%(depends)s::jsonb) item), "
        + event_sql('job.created', 'created.id', "'job/' || created.id",
                    "jsonb_build_object('job_id', created.id)" + (' || %(said)s::jsonb' if said else ''))
        + " select id::text, true from created",
        {**params, **({'said': json.dumps(said)} if said else {})})
    if created:
        return {'id': created[0][0], 'created': True}
    # GATE-OUTRANKS-PREGATE (criterion 3): the job a pre-gate queued (its rank under every gate's) takes the rank of the
    # delivery's gate that asks for it by the same key: #711's gate waited 15.3 s for its plan and 121.5 s for its checks
    # behind #712's pre-gate (13/11 00:07 UTC), the two at the same ranks; only a queued job moves, never a running one
    if spec.get('rank') is not None:
        existing = db.rows('update work.job set rank = greatest(coalesce(rank, %(rank)s::numeric), %(rank)s::numeric) '
                           'where tenant_id = %(tenant)s::uuid and idempotency_key = %(key)s and state = \'queued\' '
                           'returning id::text', {'tenant': tenant, 'key': spec.get('idempotency_key'), 'rank': spec['rank']})
        if existing:
            return {'id': existing[0][0], 'created': False}
    existing = db.rows('select id::text from work.job where tenant_id = %(tenant)s::uuid and '
                       'idempotency_key = %(key)s', {'tenant': tenant, 'key': spec.get('idempotency_key')})
    return {'id': existing[0][0], 'created': False}


BATCH_MAX = 200  # JOBS-BATCH: the jobs one call creates at most (a gate made 60)


def create_jobs(db, who, body):
    """JOBS-BATCH: POST /v1/jobs/batch {"jobs": [spec, ...]}: each job as POST /v1/jobs creates it, in order, in one
    call: a gate's jobs made four at a time reached the port's Lambda on cold instances (9.9 s to make #636's 39)."""
    jobs = (body or {}).get('jobs')
    if not isinstance(jobs, list) or not jobs or len(jobs) > BATCH_MAX or not all(isinstance(each, dict) for each in jobs):
        raise PortError(400, f'jobs: a list of 1 to {BATCH_MAX} job specs')
    return {'jobs': [create_job(db, who, spec) for spec in jobs]}


def encode(field, value):
    if CASTS.get(field) == 'jsonb':
        return json.dumps(value)
    if CASTS.get(field) == 'text[]':
        return '{' + ','.join(value) + '}'
    if CASTS.get(field) == 'boolean':
        return 'true' if value else 'false'
    return str(value)


def cancel_job(db, who, job_id):
    tenant = tenant_only(who)
    done = db.rows("with created as (update work.job set state = 'cancelled', version = version + 1 "
                   "where id = %(id)s::uuid and tenant_id = %(tenant)s::uuid "
                   "and state in ('queued', 'running', 'waiting') returning id, tenant_id, version), "
                   + event_sql('job.cancelled', "created.id || ':' || created.version", "'job/' || created.id",
                               "jsonb_build_object('job_id', created.id, 'version', created.version)")
                   + " select id::text from created", {'id': job_id, 'tenant': tenant})
    if not done:
        raise PortError(409, f'job {job_id} is not open for this tenant')


def resume_job(db, who, job_id, content):
    """Hand content to a waiting job's executor: the event carries it, and the dispatcher passes it on (P3 F3)."""
    tenant = tenant_only(who)
    done = db.rows("with created as (select id, tenant_id from work.job where id = %(id)s::uuid "
                   "and tenant_id = %(tenant)s::uuid and state = 'waiting'), "
                   + event_sql('job.resume.requested', "created.id || ':' || md5(%(content)s::text)", "'job/' || created.id",
                               "jsonb_build_object('job_id', created.id, 'content', %(content)s::jsonb)")
                   + " select id::text from created",
                   {'id': job_id, 'tenant': tenant, 'content': json.dumps(content)})
    if not done:
        raise PortError(409, f'job {job_id} is not waiting for this tenant')


def get_job(db, who, job_id):
    tenant = tenant_only(who)
    found = db.rows("select to_jsonb(j)::text from (select id, queue, state, executor, selector, attempts, "
                    "max_attempts, result, not_before, version, wait_until, wait_reason, (select coalesce(jsonb_agg(jsonb_build_object("
                    "'n', r.n, 'executor', r.executor, 'state', r.state, 'outcome', r.outcome, 'error_type', "
                    "r.error_type) order by r.n), '[]'::jsonb) from work.run r where r.job_id = job.id) as runs "
                    "from work.job job where id = %(id)s::uuid and tenant_id = %(tenant)s::uuid) j",
                    {'id': job_id, 'tenant': tenant})
    if not found:
        raise PortError(404, f'no job {job_id} for this tenant')
    return json.loads(found[0][0])


LANDED = 'platform.deploy.landed'
LANDED_FIELDS = ('merge_sha', 'base_before', 'pr', 'pr_head', 'functions', 'manifest_key', 'paths',
                 'code')  # IMAGE-PREWARM-C: {code_only, why, bundle_same[, moved]}, as the Origin-era delivery says it


# IMAGE-SWAP-TIGHTEN (docs/operations/aws.md 22.9): the image-only swap decided and written where the landing is recorded,
# in the statement that records it: the pointers move the instant the landing exists, with no service look in between.
SWAP_CONFIG = ("select v.key, v.value::text from work.config_value v join work.tenant t on t.id = v.tenant_id "
               "where t.name = %(tenant)s and v.key = any(string_to_array(%(keys)s, ','))")
# the head of the base before this merge as the log knows it: the newest push of the base (its after) or landing (its
# merge sha) that is not this merge, as the autodeploy's heads would put it before the merge
BASE_HEAD = (
    "select head from ((select u->>'after' as head, e.occurred_at from log.event e "
    "cross join lateral jsonb_array_elements(e.payload #> '{delivery,event,payload,refUpdates}') u "
    "where e.type = 'forge.repository.pushed' and e.occurred_at > now() - interval '7 days' "
    "and e.payload #> '{delivery,event,payload,refUpdates}' @> %(refs)s::jsonb and u->>'ref' = %(ref)s "
    "and coalesce(u->>'after', '') not in ('', %(merge)s) and coalesce(u->>'deleted', 'false') <> 'true' "
    "order by e.occurred_at desc limit 1) "
    "union all (select payload->>'merge_sha', occurred_at from log.event where type = 'platform.deploy.landed' "
    "and occurred_at > now() - interval '7 days' and payload->>'merge_sha' <> %(merge)s order by occurred_at desc limit 1)) h "
    "order by occurred_at desc limit 1")
LANDED_ONLY = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
               f"select %(id)s, %(tenant)s::uuid, '{LANDED}', clock_timestamp(), '{PRODUCER}', 'deploy/landed', %(payload)s::jsonb "
               f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{LANDED}' "
               "and occurred_at > now() - interval '2 days') returning 1")


def stored(db, tenant, names):
    """{name: value} of the tenant's keys as the service reads them: the row, else the registry default (an invalid row
    is the default too). One read, for the port's own decisions (the landing's swap, DEPLOY-CANARY's limit)."""
    cfg = {name: config_data.SPEC[name][1] for name in names}
    for name, text in db.rows(SWAP_CONFIG, {'tenant': tenant, 'keys': ','.join(names)}):
        try:
            cfg[name] = config_data.validate(name, json.loads(text))
        except ValueError:  # an invalid row is the default, as the service reads it
            pass
    return cfg


def deploy_landed(db, who, body):
    """FAST-ON-LANDED: the delivery that merged a PR tells the registry what it landed, as the event platform.deploy.landed
    (merge sha, the base before, the PR head, the fast Lambdas it changed, the gate's manifest key, the paths). Origin's push
    events list no files, so the autodeploy reads its fast targets from this event (it wakes the look, migration 0013).
    Idempotent by the merge sha: the same landing is the same event. Only the Origin-era delivery (scripts/deliver,
    gate_infra.announce_landed) asks it, dormant on purpose (D-316). LANDING-PREWARM-GONE: the landing no longer swaps
    onto the bundle a prewarm job built (prewarm:code:<head>): the prewarm left (D-316), and a code-only merge of the
    merge queue goes live by queue_deploy's swap or its reload in place."""
    tenant = tenant_only(who)
    body = body or {}
    sha = str(body.get('merge_sha') or '')
    if not re.fullmatch(r'[0-9a-f]{7,64}', sha) or not body.get('pr_head'):
        raise PortError(400, 'a landing needs merge_sha and pr_head')
    functions, paths = body.get('functions'), body.get('paths')
    if not isinstance(functions, list) or not (paths is None or isinstance(paths, list)):
        raise PortError(400, 'functions is a list (empty: no fast target) and paths a list')
    payload = {name: body.get(name) for name in LANDED_FIELDS}
    payload.update(functions=[str(each) for each in functions], pr=str(body.get('pr') or ''),
                   paths=[str(each) for each in paths] if paths is not None else None)
    db.rows(LANDED_ONLY, {'id': f'{LANDED}:{sha}', 'tenant': tenant, 'payload': json.dumps(payload)})
    return {'event_id': f'{LANDED}:{sha}', 'merge_sha': sha}


WARM_ROWS = 20  # RUNNER-WARM-STATUS: the warm-ups the deploy status keeps (the runner's tasks of the last deploys)
LIVE_ROWS = 20  # IMAGE-PREWARM-A: the image swaps the deploy status keeps
# SUCCESSOR-WINDOW (criterion 3): the successors' events the status keeps, of a day. The delivery at the train's front reads
# its branch's want and its bundle's warm there (merge_train): with 20 rows, a few bundles' events (wanted, holds, up,
# warm, rehearsed, reserve: about eight each) pushed #707's want out, the delivery read no want, did not wait, and the
# landing found no standby of its premerge's bundle (13/11 23:41:11 UTC; the swap by the order 13.97 s later)
SUCCESSOR_ROWS = 200
STACK_ROWS = 20  # ROLLOUT-PARTS: the app stacks' ends the deploy status keeps
SWAP_ROWS = 20  # IMAGE-PREWARM-C: the landings' image swaps (or why not) and the pointers' retirements the status keeps
CANARY_ROWS = 20  # DEPLOY-CANARY: the canaries' verdicts the deploy status keeps
ECS_ROWS = 20  # ECS-STOPS-READ: the stopped tasks and the services' actions the deploy status keeps
LANDINGS_MOST = 200  # STATUS-LANDINGS: the most landings a caller of the status may ask for (?landings=N)


def status_rows(landings):
    """STATUS-LANDINGS: (image_live rows, image_swap rows) of the deploy status for a caller that asks for its newest
    `landings` landings: one image_swap and two image_live (one a role) each. None, or what is no number from 1 to
    LANDINGS_MOST, is the status as every caller reads it (LIVE_ROWS, SWAP_ROWS: ten landings). The goal of the swap
    is a p99 over N >= 10 landings, and the measure read the newest ten whatever the series (live 12/11: fifteen
    landings since 05:50 UTC, n=10 reported)."""
    try:
        count = int(landings)
    except (TypeError, ValueError):
        return LIVE_ROWS, SWAP_ROWS
    if not 1 <= count <= LANDINGS_MOST:
        return LIVE_ROWS, SWAP_ROWS
    return max(LIVE_ROWS, 2 * count), max(SWAP_ROWS, count)


def canary_rows(landings):
    """FIRST-JOB-REHEARSED: the canaries' verdicts for a caller that asks for its newest `landings` landings: a swap's
    and a reload's each (the first job after a swap is measured by the swap's canary, over the same series as the swap).
    CANARY_ROWS for every other caller."""
    swaps = status_rows(landings)[1]
    return CANARY_ROWS if swaps == SWAP_ROWS else max(CANARY_ROWS, 2 * swaps)


RELOAD_ROWS = 40  # RELOAD-WITHOUT-STANDBY: the reloads in place the status keeps: an order says nine things (ordered, done, and
# started, reloaded and proven of each role), and deploy.sh reads both roles' reloaded of the head's bundle from them


# READY-BY-BEATS: the roles whose standby of a bundle beat within deploy.standby_fresh_s: what LANDED_SWAP's `fresh` reads
# READY-REHEARSAL: and when both roles beat, the same statement notifies tower_config (no row is written): every gate's
# listener reads the pointer as it will at the swap, and each standby warms its connections again on its next pass
# (live_image.Warm), so what the landing will wake was awake a second or so before it. The delivery at the front asks
# this just before it merges (merge_train.ready); on a host that pages, a backend idle for seconds wakes to page faults,
# and the swap woke them all at once
READY_ROLES = ("with beats as (select string_agg(distinct role, ',' order by role) as roles from work.standby_beat "
               "where digest = %(digest)s and beat_at > clock_timestamp() - make_interval(secs => %(fresh_s)s::float8)) "
               "select roles, case when roles = 'runner,service' then pg_notify('tower_config', 'deploy.ready')::text end "
               "from beats")


def deploy_ready(db, who, digest):
    """GET /v1/deploy/ready/<sha256>: whether a landing of this bundle would swap now, by the evidence its statement
    uses: {digest, roles: the roles whose standby of the bundle beat within deploy.standby_fresh_s, fresh_s, ready}.
    READY-BY-BEATS: the delivery at the front waited for its successors by the events they said once (up, warm); a
    successor that said them and is gone since (its task was replaced by a rollout, its slot went to another bundle)
    still counted, and the landing found no standby (live 12/11 00:12 UTC: #547, 16.8 s). For any caller the port knows."""
    fresh_s = stored(db, os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT), ('deploy.standby_fresh_s',))[
        'deploy.standby_fresh_s']
    found = db.rows(READY_ROLES, {'digest': digest, 'fresh_s': fresh_s})
    roles = sorted(filter(None, str(found[0][0] or '').split(','))) if found else []
    return {'digest': digest, 'roles': roles, 'fresh_s': fresh_s, 'ready': {'runner', 'service'} <= set(roles)}


# STATUS-EVENTS-AT: when an event of the swap happened (the log's own time, epoch seconds), in the status's image_live,
# image_swap and image_retired, which did not say it (a `at` the event already carries stays): the order of a swap, its
# first work and a pointer handed back was read from other events' times (12/11: the handback 8 s after #548's swap)
STATUS_AT = "(jsonb_build_object('at', round(extract(epoch from occurred_at)::numeric, 3)) || payload)::text"


def deploy_status(db, who, landings=None):
    """What the last deploy did (DEP1/DEP3), for any caller the port knows. The port's Lambda has no route to Parameter
    Store, so the service (which has) publishes the state as platform.deploy.observed events (autodeploy.py); this answers
    the newest one the caller may see: its tenant's or the installation's (tenant_id null, which is where the service
    writes them), never another tenant's. Nothing yet is 200 with nulls. Secrets are not in it: deploy.sh redacts the tail."""
    tenant = who[1] if who[0] == 'tenant' else None
    live_rows, swap_rows = status_rows(landings)
    found = db.rows("select payload::text from log.event where type = 'platform.deploy.observed' and "
                    "(tenant_id is null or tenant_id = %(tenant)s::uuid) and occurred_at > now() - interval '400 days' "
                    "order by occurred_at desc limit 1", {'tenant': tenant})
    seen = json.loads(found[0][0]) if found else {}
    build = seen.get('last_build')
    # RUNNER-WARM-STATUS: the runner tasks' warm-ups (platform.runner.warm, written by the task with tenant_id null: the
    # runner belongs to the installation), which the tenant's log query never returns; the newest WARM_ROWS, newest first
    warm = db.rows("select payload::text from log.event where type = 'platform.runner.warm' and tenant_id is null "
                   "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                   {'limit': WARM_ROWS})
    # IMAGE-PREWARM-A: the image swaps (platform.deploy.image_live, written by the standby that turned live, tenant_id
    # null like the warm-ups), the newest LIVE_ROWS, newest first
    live = db.rows(f"select {STATUS_AT} from log.event where type = 'platform.deploy.image_live' and tenant_id is null "
                   "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                   {'limit': live_rows})
    # IN-TASK-STANDBY: platform.deploy.successor (tenant_id null): the merge queue's want of a successor inside each ECS task
    # {digest, key, branch, state: wanted|withdrawn} and each successor's first beat {role, digest, task, state: up}
    successors = db.rows("select payload::text from log.event where type = 'platform.deploy.successor' and tenant_id is null "
                         "and occurred_at > now() - interval '1 day' order by occurred_at desc limit %(limit)s",
                         {'limit': SUCCESSOR_ROWS})
    # ROLLOUT-PARTS: the app stacks' ends as CloudFormation said them (platform.deploy.ended {stack, status, source}, the
    # port's EventBridge rule), newest first: where a rollout's seconds end
    stacks = db.rows("select (jsonb_build_object('at', round(extract(epoch from occurred_at)::numeric, 3)) || payload)::text "
                     "from log.event where type = 'platform.deploy.ended' and tenant_id is null "
                     "and payload->>'source' = 'cloudformation' and occurred_at > now() - interval '30 days' "
                     "order by occurred_at desc limit %(limit)s", {'limit': STACK_ROWS})
    # FAST-SERIES: a caller that asks for a series (?landings=N) reads the Lambdas' pointer swaps from the log itself
    # (platform.deploy.fast, the installation's, newest first), as many as the image swaps it asks for: the observation
    # keeps the newest FAST_KEEP (20), and the phase's proof counts 50 swaps (DEP8). Any other caller reads the observation's
    fast = None
    if swap_rows != SWAP_ROWS:
        fast = [json.loads(row[0]) for row in db.rows(
            "select (jsonb_build_object('at', extract(epoch from occurred_at)::bigint) || payload)::text from log.event "
            "where type = 'platform.deploy.fast' and tenant_id is null and occurred_at > now() - interval '30 days' "
            "order by occurred_at desc limit %(limit)s", {'limit': swap_rows})]
    # IMAGE-PREWARM-C: platform.deploy.image_swap {head, swapped, digest, key, wrote_at, landed_s | why} (the autodeploy, at a
    # landing) and platform.deploy.image_retired {digest, by: handover|reconciled|revert, keys} (tenant_id null), newest first;
    # IMAGE-SWAP-FAILOVER: by failover {role, task, stale_s} (the ECS task's watchdog) and by handback {role, task} (SIGTERM)
    # DEPLOY-CANARY: by canary {role, task, canary, state, age_s} (the ECS task's watch: the swap's canary job is red)
    swaps = db.rows(f"select {STATUS_AT} from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
                    "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                    {'limit': swap_rows})
    # ECS-STOPS-READ: platform.ecs.task_stopped {task, group, capacity, stop_code, reason, containers, ...} and
    # platform.ecs.service_action {name, level, reason, services} (tenant_id null: the port writes them from ECS's own
    # events, http_port.ecs_state), newest first, each with its type. They were written and nothing read them: the log's
    # query answers a tenant's events only, so why a task stopped was kept where no session could see it (12/11: three
    # tasks stopped after the rules were applied and none could be shown)
    ecs = db.rows("select (jsonb_build_object('at', round(extract(epoch from occurred_at)::numeric, 3), 'type', type) "
                  "|| payload)::text from log.event where type in ('platform.ecs.task_stopped', "
                  "'platform.ecs.service_action') and tenant_id is null and occurred_at > now() - interval '30 days' "
                  "order by occurred_at desc limit %(limit)s", {'limit': ECS_ROWS})
    # SPOT-KEEP: the runner tasks' lives: each task_up and each stop of a task's process (the configuration tenant's
    # platform.process.stopped, mode task), newest first: the measure of the role with no runner when a task is lost
    # VERIFY-AT-UP: and the service's task_up too, read in the same statement: the build that verifies a rollout settles a
    # stack when its new task says it is up with the image the rollout deployed (task_up, below), not at the stack's end
    lives = db.rows("select (jsonb_build_object('at', round(extract(epoch from occurred_at)::numeric, 3), 'type', type) "
                    "|| payload)::text from log.event where occurred_at > now() - interval '30 days' and ("
                    "(type = 'platform.deploy.task_up' and tenant_id is null and payload->>'role' in ('runner', 'service')) or "
                    "(type = 'platform.process.stopped' and producer = 'tower-runner' and payload->>'mode' = 'task')) "
                    "order by occurred_at desc limit %(limit)s", {'limit': ECS_ROWS * 3})
    lives = [json.loads(row[0]) for row in lives or []]
    ups = [each for each in lives if each.get('type') == 'platform.deploy.task_up'][:ECS_ROWS]
    lives = [each for each in lives if each.get('type') != 'platform.deploy.task_up' or each.get('role') == 'runner']
    retired = db.rows(f"select {STATUS_AT} from log.event where type = 'platform.deploy.image_retired' and tenant_id is null "
                      "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                      {'limit': SWAP_ROWS})
    # IMAGE-SWAP-RELOAD: platform.deploy.image_reload {role, digest, task, state: started|reloaded|failed} (tenant_id null,
    # the ECS task that loads a swapped bundle in place): reloaded carries reload_s, the pointer's write to its first work
    # RELOAD-WITHOUT-STANDBY: and a landing with no standby pair: {state: ordered, digest, key, head, landed_s}, each role's
    # started, reloaded (reload_s: the order to its first work), proven or failed {by: its judge, order_s}, back, and done
    reloads = db.rows("select payload::text from log.event where type = 'platform.deploy.image_reload' and tenant_id is null "
                      "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                      {'limit': RELOAD_ROWS})
    code = db.rows("select v.value #>> '{}' from work.config_value v join work.tenant t on t.id = v.tenant_id "
                   "where t.name = %(tenant)s and v.key = 'deploy.live_code'",
                   {'tenant': os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)})
    # DEPLOY-CANARY: platform.deploy.canary {ok, stage, seconds, key, id, at, line[, digest, head]} (tenant_id null: the
    # verdict of each canary job, tower_infra.canary), newest first
    canaries = db.rows("select payload::text from log.event where type = 'platform.deploy.canary' and tenant_id is null "
                       "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s",
                       {'limit': canary_rows(landings)})
    # LAMBDA-PRUNE-STATUS: each daily pass of the prune look, platform.deploy.prune {state, versions, kept, objects, bytes,
    # named, seconds, packages_skipped} (tenant_id null, so the log's query never answers it), newest first
    prunes = db.rows("select (jsonb_build_object('at', round(extract(epoch from occurred_at)::numeric, 3)) || payload)::text "
                     "from log.event where type = 'platform.deploy.prune' and tenant_id is null "
                     "and occurred_at > now() - interval '30 days' order by occurred_at desc limit %(limit)s", {'limit': ECS_ROWS})
    # DEP9 step 2: the version of each config key the service says it reads now (platform.config.observed, written by the
    # service when it applies a refresh), so a change can be timed from the PUT to the service's reading it
    versions = db.rows("select distinct on (payload->>'name') payload->>'name', (payload->>'version')::int, "
                       "occurred_at::text from log.event where type = 'platform.config.observed' and "
                       "tenant_id = %(tenant)s::uuid order by payload->>'name', (payload->>'version')::int desc",
                       {'tenant': tenant}) if tenant else []
    return {'config_version': {name: {'version': int(version), 'observed_at': at} for name, version, at in versions},
            'last_sha': seen.get('last_sha'), 'last_build': build if isinstance(build, dict) else None,
            'observed_at': seen.get('observed_at'), 'ring': seen.get('ring'),
            'head': seen.get('head'), 'pending': seen.get('pending'), 'source': 'registry',
            # DEP7: what the last cycles took and cost, and the month against the alarm and the hard stop
            'cycle': seen.get('cycle'), 'cycles': seen.get('cycles') or [], 'cost': seen.get('cost'),
            # DEP7-BISECT-FIX: what steers the next build (bisect) or names a commit (culprit), each with its reason
            # DEP8: the newest pointer swaps (function, version, sha, swap_ms, ok, rolled_back)
            'fast': fast if fast is not None else seen.get('fast') or [],
            # RUNNER-WARM-STATUS: each runner task's warm-up before its slots open ({task, seconds, ok})
            'runner_warm': [json.loads(row[0]) for row in warm or []],
            # IMAGE-PREWARM-A: each pointer swap a standby saw ({role, digest, version, task, swap_s})
            'image_live': [json.loads(row[0]) for row in live or []],
            # IMAGE-PREWARM-B2: each standby's transition ({role, digest, task, branch, state, at})
            'successor': [json.loads(row[0]) for row in successors or []],  # IN-TASK-STANDBY
            'stacks': [json.loads(row[0]) for row in stacks or []],  # ROLLOUT-PARTS
            'image_swap': [json.loads(row[0]) for row in swaps or []],  # IMAGE-PREWARM-C
            'image_retired': [json.loads(row[0]) for row in retired or []],
            'image_reload': [json.loads(row[0]) for row in reloads or []],  # IMAGE-SWAP-RELOAD
            'ecs': [json.loads(row[0]) for row in ecs or []],  # ECS-STOPS-READ
            'runner_life': lives[:ECS_ROWS * 2],  # SPOT-KEEP
            'task_up': ups,  # VERIFY-AT-UP: each ECS task of the two roles that said it is up ({stack, role, task, image, code})
            # SLOW-PATH-NO-ROLLOUT-WAIT: deploy.live_code, '<bundle sha256>@<merge>' ('' none): what deploy.sh verifies
            'live_code': str(code[0][0] or '') if code else '',
            'canary': [json.loads(row[0]) for row in canaries or []],  # DEPLOY-CANARY
            'prune': [json.loads(row[0]) for row in prunes or []],  # LAMBDA-PRUNE-STATUS
            'bisect': seen.get('bisect'), 'culprit': seen.get('culprit'), 'bisect_note': seen.get('note'),
            # DEP-WATCHDOG: the build in flight (step, elapsed_s) and the last ring declared lost ('lost: no ended build after N s')
            'in_progress': seen.get('in_progress'), 'lost': seen.get('lost')}


TRAIN_LEASE_S, TRAIN_LEASE_MAX_S = 900, 86400  # TRAIN-LEASE: the default lease of an entry and its ceiling (a safety for a dead delivery)
# The long poll stays under the API's 30 s; a burst of other deliveries' events ends it too. PORT-LONG-POLL-TIMEOUT: the
# 30 s are the port's integration timeout (40-port.json), which was 10 s: every wait past it answered 503 (live 11/11)
TRAIN_WAIT_MAX_S, TRAIN_WAKES = 20, 3
TRAIN_ENTRIES = ("select coalesce(jsonb_agg(jsonb_build_object('pr', pr, 'head', head, 'files', files, 'joined_at', joined_at, "
                 "'lease_until', lease_until) "
                 "order by id), '[]'::jsonb)::text from work.train where tenant_id = %(tenant)s::uuid and base = %(base)s "
                 "and ended_at is null")


def lease_of(body_or_value):
    """The lease in seconds a caller asks for (its delivery.train_lease_s), within the port's bounds."""
    try:
        seconds = float(body_or_value)
    except (TypeError, ValueError):
        return TRAIN_LEASE_S
    return min(max(seconds, 1.0), TRAIN_LEASE_MAX_S) if seconds > 0 else TRAIN_LEASE_S


def train_expire(db, tenant, base):
    """TRAIN-LEASE: every open entry of the base whose lease ran out is marked `expired` (its delivery died), an event
    platform.train.expired; the row update NOTIFYs tower_train, which wakes the entry behind. Idempotent."""
    db.rows("with done as (update work.train set ended_at = clock_timestamp(), ended = 'expired', "
            "reason = 'the lease ran out: its delivery stopped renewing it' "
            "where tenant_id = %(tenant)s::uuid and base = %(base)s and ended_at is null and lease_until < clock_timestamp() "
            "returning id, tenant_id, base, pr, head, ended, reason), "
            "logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            f"select 'train.expired:' || done.id, done.tenant_id, 'platform.train.expired', clock_timestamp(), '{PRODUCER}', "
            "'train/' || done.base, jsonb_build_object('base', done.base, 'pr', done.pr, 'head', done.head, "
            "'reason', done.reason) from done) select id from done", {'tenant': tenant, 'base': base})


def train_renew(db, who, base, pr, lease_s=None, expire=True):
    """The delivery of `pr` renews its lease (an event of its own: joined, checks started, decided, a long poll). Answers
    the state with `gone` when the entry is not open any more (it expired or left): the delivery must stop waiting."""
    tenant = tenant_only(who)
    if not base or not pr:
        raise PortError(400, 'a train renewal needs base and pr')
    if expire:
        train_expire(db, tenant, base)
    db.rows("update work.train set lease_until = clock_timestamp() + make_interval(secs => %(lease)s::float8) "
            "where tenant_id = %(tenant)s::uuid and base = %(base)s and pr = %(pr)s and ended_at is null "
            "returning id", {'tenant': tenant, 'base': base, 'pr': str(pr), 'lease': lease_of(lease_s)})
    state = train_state(db, who, base)
    where = [entry['pr'] for entry in state['entries']]
    return dict(state, state='front' if where[:1] == [str(pr)] else 'queued' if str(pr) in where else 'gone')


def train_join(db, who, base, pr, head, files=None, lease_s=None):
    """The delivery of `pr` takes its place at the end of the base's queue (idempotent: again, it keeps its place and
    takes the new head and files). The first time is the event platform.train.joined."""
    tenant = tenant_only(who)
    if not base or not pr or not head:
        raise PortError(400, 'a train entry needs base, pr and head')
    train_expire(db, tenant, base)
    db.rows("with created as (insert into work.train (tenant_id, base, pr, head, files, lease_until) "
            "values (%(tenant)s::uuid, %(base)s, %(pr)s, %(head)s, %(files)s::jsonb, "
            "clock_timestamp() + make_interval(secs => %(lease)s::float8)) "
            "on conflict (tenant_id, base, pr) where ended_at is null do update set head = excluded.head, "
            "files = excluded.files, lease_until = excluded.lease_until returning id, tenant_id, base, pr, head, (xmax = 0) as fresh), "
            + event_sql('platform.train.joined', "created.id", "'train/' || created.base",
                        "jsonb_build_object('base', created.base, 'pr', created.pr, 'head', created.head)",
                        source='created where created.fresh')
            + " select id from created",
            {'tenant': tenant, 'base': base, 'pr': str(pr), 'head': head, 'files': json.dumps(list(files or [])),
             'lease': lease_of(lease_s)})
    return train_state(db, who, base)


def train_end(db, who, base, pr, ended, reason=None):
    """The entry leaves the queue: `landed` (the front merged) or `left` (red, given up, removed); the event
    platform.train.landed or platform.train.left wakes the waiting deliveries. Idempotent: an entry already out is a no-op."""
    tenant = tenant_only(who)
    if ended not in ('landed', 'left'):
        raise PortError(400, 'ended is landed or left')
    train_expire(db, tenant, base)
    db.rows("with done as (update work.train set ended_at = clock_timestamp(), ended = %(ended)s, reason = %(reason)s "
            "where tenant_id = %(tenant)s::uuid and base = %(base)s and pr = %(pr)s and ended_at is null "
            "returning id, tenant_id, base, pr, head, ended, reason), "
            f"logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            f"select 'train.' || done.ended || ':' || done.id, done.tenant_id, 'platform.train.' || done.ended, "
            f"clock_timestamp(), '{PRODUCER}', 'train/' || done.base, jsonb_build_object('base', done.base, "
            f"'pr', done.pr, 'head', done.head, 'reason', done.reason) from done) select id from done",
            {'tenant': tenant, 'base': base, 'pr': str(pr), 'ended': ended, 'reason': reason})
    return train_state(db, who, base)


def train_state(db, who, base=None):
    """The queue of a base in order (position 0 is the front), or every base's when none is named."""
    tenant = tenant_only(who)
    if base is None:
        bases = [row[0] for row in db.rows("select distinct base from work.train where tenant_id = %(tenant)s::uuid "
                                           "and ended_at is null order by base", {'tenant': tenant})]
        return {'queues': {each: train_state(db, who, each)['entries'] for each in bases}}
    entries = json.loads(db.rows(TRAIN_ENTRIES, {'tenant': tenant, 'base': base})[0][0])
    return {'base': base, 'entries': [dict(entry, position=index) for index, entry in enumerate(entries)]}


def train_wait(db, who, body, wake=None, clock=time.monotonic):
    """The long poll of a waiting delivery: answers `front` as soon as the pr is at the head of its base's queue, `gone`
    when it is not in the queue, `queued` with timed_out when the safety timeout ends the wait first (the caller asks
    again). The wait is the LISTEN of `wake` (migration 0011's tower_train), started before the first read so no event
    falls between the read and the wait; without a wake there is nothing to wait on and the state is answered now.
    PORT-LONG-POLL-TIMEOUT: the timeout bounds the whole call, not each wait: a wake that is not this entry's front
    waits again only for what is left (three wakes of 20 s each outlived the API's 30 s)."""
    base, pr = body.get('base'), str(body.get('pr'))
    until = clock() + min(float(body.get('timeout_s') or TRAIN_WAIT_MAX_S), TRAIN_WAIT_MAX_S)
    if wake is not None:
        wake.listening()
    try:
        train_renew(db, who, base, pr, body.get('lease_s'))  # TRAIN-LEASE: the long poll is the waiting delivery's own event
        for _ in range(TRAIN_WAKES):
            train_expire(db, tenant_only(who), base)
            state = train_state(db, who, base)
            entries = state['entries']
            if not any(entry['pr'] == pr for entry in entries):
                return dict(state, state='gone')
            if entries[0]['pr'] == pr:
                return dict(state, state='front')
            left = until - clock()
            if wake is None or left <= 0 or not wake.wait(left):
                break
        train_expire(db, tenant_only(who), base)  # the long poll's own safety timeout also notices a dead front
        state = train_state(db, who, base)
        where = [entry['pr'] for entry in state['entries']]
        return dict(state, state='front' if where[:1] == [pr] else 'queued' if pr in where else 'gone', timed_out=True)
    finally:
        if wake is not None:
            wake.close()


def query_log(db, who, filters=None, payload=None, since=None, group_by=None, limit=None):
    """The raw log of the caller's tenant: filters on the envelope and on payload fields, and counts by the columns
    the caller groups by; the caller chooses what matters, the infrastructure only answers."""
    tenant = tenant_only(who)
    filters, payload, group_by = filters or {}, payload or {}, group_by or []
    if set(filters) - FILTER_COLUMNS or set(group_by) - GROUP_COLUMNS:
        raise PortError(400, f'filters on {sorted(FILTER_COLUMNS)} and groups by {sorted(GROUP_COLUMNS)}')
    params = {'tenant': tenant, 'since': since, 'limit': limit or 100}
    where = ['tenant_id = %(tenant)s::uuid'] + (['occurred_at >= %(since)s::timestamptz'] if since else [])
    for index, (column, value) in enumerate(sorted(filters.items())):
        where.append(f'{column} = %(f{index})s')
        params[f'f{index}'] = value
    for index, (key, value) in enumerate(sorted(payload.items())):
        where.append(f"payload->>%(pk{index})s = %(pv{index})s")
        params[f'pk{index}'], params[f'pv{index}'] = key, str(value)
    if group_by:
        columns = ', '.join(group_by)
        sql = (f"select coalesce(jsonb_agg(to_jsonb(g)), '[]'::jsonb)::text from (select {columns}, count(*) "
               f"as count, min(occurred_at) as first, max(occurred_at) as last from log.event where "
               f"{' and '.join(where)} group by {columns} order by {columns} limit %(limit)s::int) g")
    else:
        sql = (f"select coalesce(jsonb_agg(to_jsonb(e) order by e.occurred_at, e.event_id), '[]'::jsonb)::text from "
               f"(select event_id, type, "
               f"occurred_at, producer, subject, correlation_id, causation_id, payload from log.event where "
               f"{' and '.join(where)} order by occurred_at, event_id limit %(limit)s::int) e")
    return json.loads(db.rows(sql, params)[0][0])


def subscribe(db, who, sink, types=None):
    """A subscription of the caller's tenant to its own log, from now on; its sink is an HTTPS URL or an SNS topic of
    the installation (tower_infra.subscriptions delivers to it)."""
    tenant = tenant_only(who)
    if not subscriptions.understood(sink):
        raise PortError(400, 'a sink is an https:// URL or an SNS topic ARN')
    return db.rows("with created as (insert into log.subscription (tenant_id, sink, types) "
                   "values (%(tenant)s::uuid, %(sink)s, %(types)s::text[]) returning id, tenant_id, sink), "
                   + event_sql('platform.subscription.created', 'created.id', "'subscription/' || created.id",
                               "jsonb_build_object('sink', created.sink)")
                   + " select id::text from created",
                   {'tenant': tenant, 'sink': sink, 'types': '{' + ','.join(types or []) + '}'})[0][0]


def list_subscriptions(db, who):
    """WEBHOOK-DEAD-ALERT: the caller's tenant's subscriptions, so a standing one (an alert) can be seen, not only made."""
    return json.loads(db.rows(
        "select coalesce(jsonb_agg(jsonb_build_object('id', id, 'sink', sink, 'types', types, 'state', state, "
        "'read_until', read_until) order by id), '[]'::jsonb)::text from log.subscription where tenant_id = %(tenant)s::uuid",
        {'tenant': tenant_only(who)})[0][0])


def rewind_subscription(db, who, subscription, since):
    """Replay from a point: the tenant's own subscription reads its log again from `since`."""
    tenant = tenant_only(who)
    if not since:
        raise PortError(400, 'a rewind needs since, a timestamp')
    if not db.rows('select log.rewind(%(id)s::uuid, %(tenant)s::uuid, %(since)s::timestamptz)',
                   {'id': subscription, 'tenant': tenant, 'since': since})[0][0] in (True, 't'):
        raise PortError(404, 'no such subscription')
    return {'id': subscription, 'since': since}


def cancel_subscription(db, who, subscription):
    """Stop a subscription of the caller's tenant: its state becomes `cancelled`, which the deliverer's active query
    skips, and platform.subscription.cancelled is logged once. Idempotent; another tenant's id looks like no id."""
    tenant = tenant_only(who)
    params = {'id': subscription, 'tenant': tenant}
    done = db.rows("with created as (update log.subscription set state = 'cancelled' "
                   "where id = %(id)s::uuid and tenant_id = %(tenant)s::uuid and state <> 'cancelled' "
                   "returning id, tenant_id), "
                   + event_sql('platform.subscription.cancelled', 'created.id', "'subscription/' || created.id",
                               "jsonb_build_object('subscription_id', created.id)")
                   + " select id::text from created", params)
    if not done and not db.rows('select 1 from log.subscription where id = %(id)s::uuid and tenant_id = %(tenant)s::uuid',
                                params):
        raise PortError(404, 'no such subscription')
    return {'id': subscription, 'state': 'cancelled'}
