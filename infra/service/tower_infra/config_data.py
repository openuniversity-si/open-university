"""Configuration as data (DEP9; docs/operations/aws.md 22.5): the service's behaviour keys are read at runtime from
work.config_value (migration 0010), falling back to the compiled defaults, which mirror the registry's (a test pins them
against config/registry/**; the service image has no registry file).

A change is a write: PUT /v1/config/<key> upserts the row, logs config.changed and the table's trigger notifies
`tower_config`; Config.refresh() runs on that event (listen()) and before each autodeploy look, so a change takes effect in
about a second with no deploy and no polling. The wait in listen() is only the safety timeout of a lost notification.
An invalid stored value never reaches a reader: the last good one (or the default) stays and a warning is logged.
Standard library only.
"""
import json
import re
import logging
import os
from pathlib import Path
import threading

LOG = logging.getLogger('tower_infra.config_data')
TENANT = 'torre'  # the tenant whose rows the service reads (TOWER_CONFIG_TENANT)
# name -> (type, default); numbers and integers must be > 0. Mirrors the registry (tested).
SPEC = {
    'deploy.auto': (bool, True),
    'deploy.base_branch': (str, 'mod/roadmap-integration'),
    'deploy.debounce_s': (int, 20),
    'deploy.lost_after_s': (int, 3000),
    'deploy.monthly_usd': (float, 30.0),
    'deploy.alarm_usd': (float, 20.0),
    'deploy.usd_per_min': (float, 0.005),
    'deploy.fast_propagation_s': (float, 10.0),
    'deploy.fast_activate_s': (float, 120.0),
    # IMAGE-PREWARM-A (aws.md 22.9): the image digest that takes each role's work; '' is no pointer (every image works)
    'deploy.live_image_service': (str, ''),
    'deploy.live_image_runner': (str, ''),
    # SLOW-PATH-NO-ROLLOUT-WAIT: the code bundle a task boots when its definition has not seen it: '<sha256>@<merge>', '' none
    'deploy.live_code': (str, ''),
    # DEFAULTS-AS-LIVE (revisão da arquitetura, achado 36): the defaults are the values the engine runs on (the Torre's rows
    # of 11/11): a successor in each task, the canary's own slot. GATE-LOOKS-GONE (D-316): the Spot standbys' key
    # (deploy.prewarm_max_tasks) left with the prewarm
    # IN-TASK-STANDBY: the successor processes the ECS task of each role holds (the standby inside the task); 0 is off
    'deploy.intask_standbys': (int, 1),
    # IMAGE-PREWARM-C: a landing promotes its healthy standbys (22.9a); false lets the landings accumulate
    'deploy.promote': (bool, True),
    # QUEUE-RELOAD: the merge queue's prepare and landed order a code-only merge's reload in place (tower_infra.queue_deploy)
    'deploy.queue_reload': (bool, True),
    # IMAGE-SWAP-TIGHTEN: a standby counts healthy for the landing's swap while its last beat is this recent (seconds)
    'deploy.standby_fresh_s': (float, 3.0),
    # IMAGE-SWAP-FAILOVER: an ECS task standing by takes the role back once the pointed image's live beat is this old (seconds)
    'deploy.live_stale_s': (float, 10.0),
    # DEPLOY-CANARY: a deploy canary (one job through dispatch, take and run) is red when it has not ended well by then (seconds)
    'deploy.canary_limit_s': (float, 120.0),
    # CANARY-OWN-SLOT: 1 gives the deploy canaries a slot of their own in the runner's capacity; 0 is off
    'deploy.canary_slot': (int, 1),
    # ENGINE-REPO (14/11/2026): the engine's repository on its forge (tower_infra.engine.repo), owner/name; the default is
    # the public repository's, and the Torre writes the deployed engine's own
    'service.engine_repo': (str, 'openuniversity-si/open-university'),
    'service.dispatch_s': (float, 1.0),
    # DB-VITALS: the database's disk (bytes) and the ratios of it and of max_connections past which the service alerts
    'service.db_disk_bytes': (int, 21474836480),
    'service.db_alert_disk_ratio': (float, 0.7),
    'service.db_alert_connections_ratio': (float, 0.8),
    # RUNNER-STALL-ALERT: a run handed over to the runner and not taken for this long (seconds) is an alert
    'service.runner_stall_alert_s': (float, 180.0),
    # DISPATCH-STALL-ALERT: a job a dispatcher would start now and nobody starts for this long (seconds) is an alert
    'service.dispatch_stall_alert_s': (float, 120.0),
    'medir.webhook_ack_limit_s': (float, 1.0),
    # the webhook consumer's behaviour rules (DEP9 step 2): read per SQS batch, see webhook_consumer.rules()
    'service.webhook_tolerance_s': (int, 300),
    'service.webhook_drop_stale': (bool, True),
    'service.webhook_drop_bad_signature': (bool, True),
}
# IMAGE-PREWARM-A: writing '' removes the pointer; SLOW-PATH-NO-ROLLOUT-WAIT: and the live code
EMPTY_OK = ('deploy.live_image_service', 'deploy.live_image_runner', 'deploy.live_code')
# IMAGE-PREWARM-B2, IN-TASK-STANDBY: 0 starts no standby; CANARY-OWN-SLOT: 0 is no slot of the canary's own
ZERO_OK = ('deploy.intask_standbys', 'deploy.canary_slot')
# SWAP-SECOND-QUIET: the engine's own state, kept in the same table: written by the engine (the landing, the look, the
# handover), read by the gate of each process, which says so itself (platform.deploy.image_live, the reload's events).
# No platform.config.observed for them: it was an insert, in a transaction of its own, by each service process on the
# swap's very second (live 12/11 03:26 UTC: the longest statements still running when the roles first worked)
OWN = EMPTY_OK
OBSERVE = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
           "select %(id)s, t.id, 'platform.config.observed', clock_timestamp(), 'tower-service', 'config/' || %(name)s, "
           "%(payload)s::jsonb from work.tenant t where t.name = %(tenant)s and not exists "
           "(select 1 from log.event where event_id = %(id)s and type = 'platform.config.observed')")
LOAD = ("select v.key, v.value::text, v.version from work.config_value v join work.tenant t on t.id = v.tenant_id "
        "where t.name = %(tenant)s")


def validate(name, value):
    """The value in the key's registry type, else ValueError (unknown key, wrong type, not > 0, empty string)."""
    if name not in SPEC:
        raise ValueError(f'{name} is not a configurable key')
    want = SPEC[name][0]
    if want is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if type(value) is not want:
        raise ValueError(f'{name} wants {want.__name__}')
    if want in (int, float) and (value < 0 if name in ZERO_OK else value <= 0):
        raise ValueError(f'{name} wants {want.__name__} {">= 0" if name in ZERO_OK else "> 0"}')
    if want is str and not value.strip() and name not in EMPTY_OK:
        raise ValueError(f'{name} wants a non-empty string')
    if name == 'service.engine_repo' and not re.match(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', value):
        raise ValueError('service.engine_repo wants owner/name')
    return value


class Config:
    """The cached values of one tenant. scope() is a context manager giving a database (rows(sql, params))."""

    def __init__(self, scope, tenant=TENANT, keep=None):
        self.scope, self.tenant = scope, tenant
        self.values, self.versions, self.lock = {}, {}, threading.Lock()
        # SETTINGS-HANDED: a file of the task's own (its supervisor's spool) where every good read leaves what it read,
        # for the process the role waits for to start with, before its own read (after its first work)
        self.keep = keep

    def kept(self):
        """SETTINGS-HANDED: the values another process of this task read last (keep), taken as this process's own, with
        their versions; answers whether there were any. Nothing is said in the log (observe): this process reads the
        table itself after its first work, and says what it reads then."""
        if not self.keep:
            return False
        try:
            found = json.loads(Path(self.keep).read_text())
            fresh = {name: (validate(name, value), int(found['versions'][name])) for name, value in found['values'].items()
                     if found.get('tenant') == self.tenant}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
        if not fresh:
            return False
        with self.lock:
            self.values = {name: value for name, (value, _) in fresh.items()}
            self.versions = {name: version for name, (_, version) in fresh.items()}
        return True

    def leave(self):
        """SETTINGS-HANDED: what this process read, written whole into keep. Never raises."""
        if not self.keep:
            return
        try:
            with self.lock:
                said = {'tenant': self.tenant, 'values': dict(self.values), 'versions': dict(self.versions)}
            path = Path(self.keep)
            draft = path.with_name(f'.{path.name}.{os.getpid()}')
            draft.write_text(json.dumps(said))
            os.replace(draft, path)
        except (OSError, TypeError, ValueError):
            pass

    def get(self, name):
        with self.lock:
            return self.values[name] if name in self.values else SPEC[name][1]

    def prefix(self, prefix):
        """{short name: value} of every key under `prefix.`, defaults included."""
        return {name[len(prefix) + 1:]: self.get(name) for name in SPEC if name.startswith(prefix + '.')}

    def stored(self, prefix):
        """{short name: value} of the keys under `prefix.` that have a row (no defaults)."""
        with self.lock:
            return {name[len(prefix) + 1:]: value for name, value in self.values.items() if name.startswith(prefix + '.')}

    def refresh(self, scope=None):
        """Read the table; answers the names whose value changed. A failed read or an invalid row keeps what was there.
        scope: another scope for this read (SETTINGS-ON-LOOP: a late service's first, on its loop's connection)."""
        try:
            with (scope or self.scope)() as db:
                found = db.rows(LOAD, {'tenant': self.tenant})
        except Exception:  # noqa: BLE001 - the last good values stay
            LOG.exception('config: could not read work.config_value; keeping the last values')
            return []
        fresh = {}
        with self.lock:
            before_versions = dict(self.versions)
        for name, text, version in found:
            try:
                fresh[name] = (validate(name, json.loads(text)), int(version))
            except ValueError as error:
                LOG.warning('config.invalid: %s (version %s); keeping the previous value', error, version)
                with self.lock:
                    if name in self.values:
                        fresh[name] = (self.values[name], self.versions.get(name))
        with self.lock:
            before = {name: self.values.get(name, SPEC[name][1]) for name in SPEC}
            self.values = {name: value for name, (value, _) in fresh.items()}
            self.versions = {name: version for name, (_, version) in fresh.items()}
            changed = [name for name in SPEC if self.values.get(name, SPEC[name][1]) != before[name]]
        if changed:
            LOG.info('config: refreshed %s', ', '.join(changed))
        self.leave()  # SETTINGS-HANDED
        self.observe(before_versions)
        return changed

    def observe(self, before):
        """Say in the log which version of each key this process now reads (platform.config.observed, once per key and
        version, the tenant's), so GET /v1/deploy/status can show config_version and scripts/config-latency can time a
        change from the PUT to the service's reading it. Only on a changed version, i.e. on the event; never fatal.
        SWAP-SECOND-QUIET: nothing for the engine's own state (OWN)"""
        with self.lock:
            moved = {name: version for name, version in self.versions.items()
                     if version is not None and before.get(name) != version and name not in OWN}
            values = {name: self.values[name] for name in moved}
        if not moved:
            return
        try:
            with self.scope() as db:
                for name, version in moved.items():
                    db.rows(OBSERVE, {'id': f'platform.config.observed:{self.tenant}:{name}:{version}', 'name': name,
                                      'tenant': self.tenant,
                                      'payload': json.dumps({'name': name, 'version': version, 'value': values[name]})})
        except Exception:  # noqa: BLE001 - an observation is a courtesy; the value is already applied
            LOG.exception('config: could not record the observed versions')


def listen(config, stop, wait, safety_s=300):
    """Refresh `config` on every notification of `tower_config` (wait is Wake(..., CONFIG).wait); `safety_s` is only the
    timeout of a lost notification. A daemon thread; answers it."""
    def loop():
        while not stop.is_set():
            wait(safety_s)
            if stop.is_set():
                break
            config.refresh()
    thread = threading.Thread(target=loop, name='config', daemon=True)
    thread.start()
    return thread
