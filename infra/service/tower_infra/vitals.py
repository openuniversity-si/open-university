"""DB-VITALS (docs/operations/aws-revisao-arquitetura.md, findings 10 and 13): the engine measures its own database.

The database is one db.t4g.micro with a 20 GB disk: a full disk or a full table of connections stops the whole engine at
once, and neither was measured anywhere but in the AWS account, which no session reads. The live service measures both
on the connections it already has and writes what it saw as an event of the log:

  platform.db.vitals {database_bytes, disk_bytes, disk_ratio, log_bytes, log_events, tables: {name: bytes} (the five
                      largest), connections, connections_peak, peak_by_user, peak_by_app, max_connections,
                      connections_ratio, window_s, alerts: [disk|connections],
                      rss_mb, rss_peak_mb, task_mb, task_limit_mb (memory(): each only when it can be read),
                      passes, stalled, stalls: [{at, ms}] (DB-STALL-EVIDENCE, below),
                      host: {mem, load, cpu} (DB-HOST-VITALS, below: only when the database can say it),
                      server: {name: setting} (SERVER-SETTINGS-READ: the settings that size the server's memory)}

Vitals.beat(db), on the service's heartbeat, counts the database's connections by user and by application_name (one
statement over pg_stat_activity) and keeps the peak; DB-LISTEN-ONE: the engine names every connection it opens
tower-<role>:<purpose> (database.named), so peak_by_app says which process holds the table and what for (the APPS
largest, the rest as `others`). Vitals.record(db), once on a task's second beat (not its first: that pass may be
the first after an image swap, whose seconds are counted) and then on the hourly pass that keeps the log's partitions
ahead, reads the sizes, writes the event with the peak of its window and starts a new one.
A threshold crossed (service.db_alert_disk_ratio of service.db_disk_bytes; service.db_alert_connections_ratio of
max_connections, by the peak) is in the event's alerts, and is published to the platform's topic when the alerts differ
from those of the last event recorded: once when it starts, once when it ends, however many tasks restart in between.
The event belongs to the configuration tenant (config.tenant), so its token reads it:
POST /v1/log/query {filters: {type: platform.db.vitals}, since}. Never raises: a measure that fails is logged and tried again.

DB-STALL-EVIDENCE: live 12/11 two swaps took 1.05 and 1.32 s with every statement of their second still running and
waiting on nothing (SWAP-TAIL-WAITS: a BEGIN for 127 ms, a 1 ms insert for 1.3 s): the database's host stalled, and
nothing said whether it does so only at a landing. The live service's idle dispatch pass is a probe it already runs:
the same few statements on its kept connection, milliseconds each. Vitals.passed(seconds, started), told by the loop
after every tick, counts the passes that started no run (passes), those that took STALL_S or more (stalled) and keeps
the STALLS worst of the window with when they were (stalls: at, the wall clock's seconds; ms), so the stalls can be
laid beside the landings, the logins and the account's metrics. No statement is added.

DB-HOST-VITALS: the host's own memory, swap, load and CPU times, read through SQL (work.host_vitals(), migration 0017,
over pg_proctab, which the owner's step creates where RDS offers it: tower_infra.dbinit): whether the db.t4g.micro is
short of memory when it freezes was a metric of the AWS account only. host(db) asks first whether the function is
there (code before its migration), then calls it; it is null without the extension and never raises, so the event
simply has no `host` until the database can say it.

HOST-RATES: pg_cputime's counters run since the host's boot; the event carries the shares of the window between two
readings of this process (host.rates: user, nice, system, idle, iowait, window_s), the first of them taken on the
process's first beat, so what a change of the server's memory does to the time the host waits for its disk is read in
the events themselves.
"""
import json
import logging
from pathlib import Path
import time
import uuid

from . import canary, config_data

LOG = logging.getLogger('tower_infra.vitals')
EVENT = 'platform.db.vitals'
DISK, DISK_RATIO, CONNECTIONS_RATIO = 'service.db_disk_bytes', 'service.db_alert_disk_ratio', 'service.db_alert_connections_ratio'
# VITALS-LOGINS: with the connections, those born since the last beat (by who opened them), and the sessions the database
# has opened in all (pg_stat_database: every login, also one that came and went between two beats)
CONNECTIONS = ("select coalesce(usename::text, '-'), coalesce(nullif(application_name, ''), '-'), count(*), "
               "count(*) filter (where backend_start > clock_timestamp() - make_interval(secs => %(since)s::float8)), "
               "(select sessions from pg_stat_database where datname = current_database()) "
               "from pg_stat_activity where datname = current_database() group by 1, 2")
APPS = 12  # DB-LISTEN-ONE: how many application names an event carries
# DB-SWAP-CUT (achado 37): the backends idle for a minute or more, by who opened them: what the host keeps for nobody
IDLE = ("select coalesce(nullif(application_name, ''), '-'), count(*) from pg_stat_activity "
        "where datname = current_database() and state = 'idle' and state_change < clock_timestamp() - interval '60 seconds' "
        "group by 1")
STALL_S, STALLS = 0.25, 5  # DB-STALL-EVIDENCE: an idle pass this long stalled; how many of a window the event carries
# STALL-SAYS-WHAT: how many of a window's stalls say what the database was doing while they lasted, how many of its
# statements each one says, and how much of a statement's text
EVIDENCED, SAID, TEXT = 2, 4, 64
SIZES = ("select pg_database_size(current_database()), current_setting('max_connections')::int, "
         "coalesce(sum(pg_total_relation_size(i.inhrelid)), 0)::bigint, coalesce(sum(greatest(c.reltuples, 0)), 0)::bigint "
         "from pg_inherits i join pg_class c on c.oid = i.inhrelid where i.inhparent = 'log.event'::regclass")
TABLES = ("select n.nspname || '.' || c.relname, pg_total_relation_size(c.oid) from pg_class c "
          "join pg_namespace n on n.oid = c.relnamespace where c.relkind = 'r' "
          "and n.nspname not in ('pg_catalog', 'information_schema') order by 2 desc limit 5")
# SERVER-SETTINGS-READ: what sizes the server's memory, as pg_settings says it to the service's own login
SERVER_NAMES = ('shared_buffers', 'max_connections', 'work_mem', 'maintenance_work_mem', 'autovacuum_work_mem',
                'autovacuum_max_workers', 'wal_buffers', 'temp_buffers', 'effective_cache_size', 'max_worker_processes',
                'max_parallel_workers', 'max_parallel_workers_per_gather', 'synchronous_commit', 'huge_pages', 'jit')
SERVER = "select name, setting, unit from pg_settings where name = any(string_to_array(%(names)s, ','))"
# RUNNER-OWN-LOGIN: whether the runner's login is there and holds what the service grants it (migration 0019): null with
# no such login, else whether it may write to the log. Read before the runner's stack is told to use it
RUNNER_LOGIN = ("select has_table_privilege(to_regrole('tower_runner'), 'log.event'::regclass, 'insert') "
                "and has_function_privilege(to_regrole('tower_runner'), to_regprocedure('work.take_run(text,text)'), 'execute')")
# DB-HOST-VITALS: is the function there (never fails: the code may run before migration 0017), and what it answers
HOST_THERE = "select to_regprocedure('work.host_vitals()') is not null"
HOST = 'select work.host_vitals()::text'
# the event is the configuration tenant's, like platform.config.observed: the port's log query answers a tenant its own
LAST = (f"select e.payload->'alerts' from log.event e join work.tenant t on t.id = e.tenant_id "
        f"where e.type = '{EVENT}' and t.name = %(tenant)s order by e.occurred_at desc limit 1")
RECORD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          f"select %(id)s, t.id, '{EVENT}', clock_timestamp(), 'tower-service', 'database', %(payload)s::jsonb "
          "from work.tenant t where t.name = %(tenant)s")


def alerts(said, disk_ratio, connections_ratio):
    """The thresholds a measure crosses, in a fixed order."""
    return [name for name, value, limit in (('disk', said['disk_ratio'], disk_ratio),
                                            ('connections', said['connections_ratio'], connections_ratio)) if value >= limit]


STATUS, CGROUP = '/proc/self/status', '/sys/fs/cgroup'
RSS = {'VmRSS': 'rss_mb', 'VmHWM': 'rss_peak_mb'}
TASK = (('task_mb', ('memory.current', 'memory/memory.usage_in_bytes')),  # cgroup v2's file, then v1's
        ('task_limit_mb', ('memory.max', 'memory/memory.limit_in_bytes')))
NO_LIMIT = 2 ** 60  # cgroup v1 says no limit with a number near 2 ** 63; v2 says `max`


def memory(status=STATUS, cgroup=CGROUP):
    """The service process's own memory in MiB, read from files (whether a second service process fits in the task):
    rss_mb and rss_peak_mb (VmRSS and VmHWM of /proc/self/status), task_mb and task_limit_mb (the cgroup's memory in use
    and its limit). What cannot be read is left out, and so is a limit that is none. Never raises."""
    said = {}
    try:
        for line in Path(status).read_text(encoding='utf-8').splitlines():
            name, _, value = line.partition(':')
            if name in RSS:
                said[RSS[name]] = round(int(value.split()[0]) / 1024, 1)  # kB
    except (OSError, ValueError, IndexError):
        pass
    for field, names in TASK:
        for name in names:
            try:
                size = int((Path(cgroup) / name).read_text(encoding='utf-8').strip())
            except (OSError, ValueError):  # not this cgroup version's file, or `max`
                continue
            if size < NO_LIMIT:
                said[field] = round(size / 2 ** 20, 1)
            break
    return said


def host(db):
    """DB-HOST-VITALS: {host: {mem, load, cpu}} as work.host_vitals() says it ({error} when one of pg_proctab's functions
    failed); {} without the function, without the extension, or when it cannot be asked. Never raises."""
    try:
        there = db.rows(HOST_THERE)
        if not there or there[0][0] not in (True, 't'):
            return {}
        found = db.rows(HOST)
        said = found[0][0] if found else None
        said = json.loads(said) if isinstance(said, str) else said
        return {'host': said} if said else {}
    except Exception:  # noqa: BLE001
        LOG.exception("vitals: the host's vitals were not read")
        return {}


def rates(before, after, window_s):
    """HOST-RATES: how the host spent the time between two readings of pg_cputime's counters (they run since its boot):
    each counter's growth over the growth of all of them (user, nice, system, idle, iowait: no clock rate, no count of
    cores to know), with the window's seconds; None when nothing moved or a counter went back (the host restarted)."""
    try:
        moved = {name: float(after[name]) - float(before[name]) for name in after if name in before}
        total = sum(moved.values())
        if total <= 0 or any(value < 0 for value in moved.values()):
            return None
        return {**{name: round(value / total, 3) for name, value in moved.items()}, 'window_s': round(window_s, 1)}
    except (TypeError, ValueError):
        return None


def server(db):
    """SERVER-SETTINGS-READ: {server: {name: setting with its unit}} of SERVER_NAMES as the database says them; {} when it
    says none or cannot be asked. Never raises."""
    try:
        # the value, then its unit apart: pg_settings counts shared_buffers in pages (`8192 8kB`), and glued they read
        # as another number (live 12/11: `81928kB`)
        said = {name: f'{setting} {unit}' if unit else str(setting)
                for name, setting, unit in db.rows(SERVER, {'names': ','.join(SERVER_NAMES)})}
        return {'server': said} if said else {}
    except Exception:  # noqa: BLE001
        LOG.exception("vitals: the server's settings were not read")
        return {}


def runner_login(db):
    """RUNNER-OWN-LOGIN: {runner_login: 'granted' | 'not granted' | 'no login'} as the database says it; {} when it cannot
    be asked. Never raises."""
    try:
        found = db.rows(RUNNER_LOGIN)
        said = found[0][0] if found else None
        return {'runner_login': 'no login' if said is None else 'granted' if said in (True, 't') else 'not granted'}
    except Exception:  # noqa: BLE001
        LOG.exception("vitals: the runner's login was not read")
        return {}


def tally(rows, column):
    """The connections of CONNECTIONS's rows by one of their columns (0 the user, 1 the application name)."""
    counts = {}
    for row in rows:
        counts[row[column]] = counts.get(row[column], 0) + int(row[2])
    return counts


def largest(by_app, most=APPS):
    """DB-LISTEN-ONE: the `most` application names that hold the most connections; the rest add up under `others`."""
    ranked = sorted(by_app.items(), key=lambda item: (-item[1], item[0]))
    rest = sum(count for _, count in ranked[most:])
    return dict(ranked[:most] + ([('others', rest)] if rest else []))


class Vitals:
    """The live service's measure of its database. config: the service's settings (get(name), tenant); publish(said, subject=)
    sends an alert; clock is monotonic seconds."""

    def __init__(self, config, publish=canary.alert, clock=time.monotonic, wall=time.time, evidence=None):
        self.config, self.publish, self.clock, self.wall = config, publish, clock, wall
        self.passes, self.stalled, self.stalls = None, 0, []  # DB-STALL-EVIDENCE: None until a pass is told
        self.cpu = None  # HOST-RATES: (when, the host's CPU counters) of the last reading
        self.tenant = getattr(config, 'tenant', config_data.TENANT)
        self.peak, self.by_user, self.by_app, self.now, self.current, self.apps = 0, {}, {}, 0, {}, {}
        self.since, self.beats, self.recorded = clock(), 0, False
        self.most, self.alerting = None, []  # VITALS-ALERT-AT-BEAT: max_connections and the alerts of the last event
        # STALL-SAYS-WHAT: evidence(window_s) answers what the database was doing in the last window_s seconds
        # (live_image.busy's shape: {busy: [{q, n, ms, active, of, waits}], logins}); how many stalls of the window asked it
        self.evidence, self.evidenced = evidence, 0
        # VITALS-LOGINS: the logins of the window: when the last beat was, the database's count of sessions at the
        # window's start and now, and the connections seen born between two beats, by application name
        self.beat_at, self.sessions, self.opened, self.born = None, None, None, {}

    def read_host(self, db):
        """DB-HOST-VITALS, HOST-RATES: host(db), with the shares of the host's time since this process's last reading
        (rates) when both have the CPU's counters."""
        found = host(db)
        cpu = (found.get('host') or {}).get('cpu')
        if isinstance(cpu, dict):
            said = rates(self.cpu[1], cpu, self.clock() - self.cpu[0]) if self.cpu is not None else None
            if said:
                found = {'host': {**found['host'], 'rates': said}}
            self.cpu = (self.clock(), cpu)
        return found

    def passed(self, seconds, started=0):
        """DB-STALL-EVIDENCE: one dispatch pass of the live service, as its loop timed it. A pass that started no run is
        the probe: counted, and one of STALL_S or more is kept among the window's worst. Never raises."""
        try:
            if started:
                return  # its length is its work
            took = float(seconds)
            self.passes = (self.passes or 0) + 1
            if took >= STALL_S:
                self.stalled += 1
                self.stalls.append({'at': round(self.wall(), 3), 'ms': round(took * 1000), **self.during(took)})
                self.stalls = sorted(self.stalls, key=lambda each: -each['ms'])[:STALLS]
        except (TypeError, ValueError):
            pass

    def during(self, took):
        """STALL-SAYS-WHAT: what the database was doing while a pass stalled, asked right after it: the SAID
        statements of the window that ran longest (their text's first TEXT characters, how many backends, their
        milliseconds, how many still run, the event or key they name and what they wait on) and the logins of the
        window. Only the first EVIDENCED stalls of a window ask (the reading is itself a statement on a host that
        stalls), and only when the service gave a way to ask. Live 12/11: a stall of 0.4 to 0.6 s within a second of
        nearly every landing, and nothing said what ran then: the swap's own evidence is read before it, and since
        SWAP-EVIDENCE-WHEN-SLOW not at all on a fast swap. Never raises: {} when there is nothing to say."""
        if self.evidence is None or self.evidenced >= EVIDENCED:
            return {}
        self.evidenced += 1
        try:
            found = self.evidence(took + STALL_S) or {}
            ran = sorted((each for each in found.get('busy') or [] if isinstance(each, dict)),
                         key=lambda each: -(each.get('ms') or 0))[:SAID]
            said = [{**{name: each[name] for name in ('n', 'ms', 'active', 'of', 'waits') if each.get(name) not in (None, [])},
                     'q': str(each.get('q') or '')[:TEXT]} for each in ran]
            return {**({'busy': said} if said else {}), **({'logins': found['logins']} if found.get('logins') else {})}
        except Exception:  # noqa: BLE001
            LOG.exception('vitals: what the database was doing during a stall was not read')
            return {}

    def logged_in(self, rows):
        """VITALS-LOGINS: of a beat's rows, the connections born since the last beat (by application name) and the
        database's sessions so far. A login is a fork, a TLS handshake and the IAM token's check on the database's
        host: alone 0.06 to 0.17 s, five at once 0.42 to 1.2 s each (live 12/11, the port's Server-Timing), and
        nothing said how many the engine makes in an hour, nor who makes them. Rows without the columns (an older
        statement, a test's stand-in) say nothing."""
        for row in rows:
            born = int(row[3] or 0) if len(row) > 3 else 0
            if born:
                self.born[row[1]] = self.born.get(row[1], 0) + born
        seen = [row[4] for row in rows if len(row) > 4 and row[4] is not None]
        if seen:
            self.opened = int(seen[0])
            if self.sessions is None:
                self.sessions = self.opened

    def logins(self):
        """VITALS-LOGINS: the event's fields: logins (every session the database opened in the window, this
        process's own readings apart) and logins_by_app (those seen born between two beats: one that came and went
        inside a beat is in logins alone)."""
        said = {}
        if self.sessions is not None and self.opened is not None:
            said['logins'] = max(self.opened - self.sessions, 0)
        if self.born:
            said['logins_by_app'] = largest(self.born)
        return said

    def beat(self, db):
        """The connections open now, counted by user and by application name; the largest count of the window is kept
        with who held it."""
        try:
            if self.cpu is None and self.beats == 0:  # HOST-RATES: the process's first reading, so its first event has rates
                self.read_host(db)
            now = self.clock()
            found = db.rows(CONNECTIONS, {'since': 0.0 if self.beat_at is None else round(now - self.beat_at, 3)})
            self.beat_at = now
            self.logged_in(found)
            self.current, self.apps = tally(found, 0), tally(found, 1)
            self.now = sum(self.current.values())
            if self.now > self.peak:
                self.peak, self.by_user, self.by_app = self.now, self.current, self.apps
            self.beats += 1
            if not self.recorded and self.beats > 1:  # a task's first measure is not an hour away, nor on its first pass
                self.record(db)
            elif (self.most and 'connections' not in self.alerting
                  and self.now / self.most >= self.config.get(CONNECTIONS_RATIO)):
                # VITALS-ALERT-AT-BEAT: the threshold crossed is said on the beat that sees it, not on the hour: live
                # 11/11 the event of 22:14 read 36 of 79, the database was at its limit three minutes later (the port
                # answered 500 for four minutes) and the next event was due at 23:14
                self.record(db)
        except Exception:  # noqa: BLE001
            LOG.exception('vitals: the connections were not counted')

    def record(self, db):
        """The sizes and the window's peak written as one event; alerts that changed since the last event are published."""
        try:
            database, most, log_bytes, log_events = (int(value) for value in db.rows(SIZES)[0])
            disk = int(self.config.get(DISK))
            peak, by_user, by_app = ((self.peak, self.by_user, self.by_app) if self.peak
                                     else (self.now, self.current, self.apps))  # no beat in the window
            said = {'database_bytes': database, 'disk_bytes': disk, 'disk_ratio': round(database / disk, 4),
                    'log_bytes': log_bytes, 'log_events': log_events,
                    'tables': {name: int(size) for name, size in db.rows(TABLES)},
                    'connections': self.now, 'connections_peak': peak, 'peak_by_user': by_user,
                    'peak_by_app': largest(by_app),
                    'idle_by_app': largest({name: int(count) for name, count in db.rows(IDLE)}),  # DB-SWAP-CUT
                    'max_connections': most, 'connections_ratio': round(peak / most, 4),
                    'window_s': round(self.clock() - self.since, 1), **memory(),
                    **({} if self.passes is None else {'passes': self.passes, 'stalled': self.stalled}),
                    **({'stalls': sorted(self.stalls, key=lambda each: each['at'])} if self.stalls else {}),
                    **self.logins()}
            said.update(self.read_host(db))  # DB-HOST-VITALS: the host's memory, swap and load, when the database can say them
            said.update(server(db))  # SERVER-SETTINGS-READ: what sizes the server's memory
            said.update(runner_login(db))  # RUNNER-OWN-LOGIN: is the runner's login there, and granted
            said['alerts'] = alerts(said, self.config.get(DISK_RATIO), self.config.get(CONNECTIONS_RATIO))
            last = db.rows(LAST, {'tenant': self.tenant})
            before = [] if not last else json.loads(last[0][0]) if isinstance(last[0][0], str) else last[0][0] or []
            db.rows(RECORD, {'id': f'{EVENT}:{uuid.uuid4()}', 'tenant': self.tenant, 'payload': json.dumps(said)})
            self.peak, self.by_user, self.by_app = 0, {}, {}  # a new window
            self.passes, self.stalled, self.stalls = (None if self.passes is None else 0), 0, []
            self.evidenced = 0  # STALL-SAYS-WHAT: the next window's first stalls ask again
            self.sessions, self.born = self.opened, {}  # VITALS-LOGINS: the next window counts from here
            self.since, self.recorded = self.clock(), True
            self.most, self.alerting = most, said['alerts']
            if said['alerts'] != before:
                LOG.warning('vitals: alerts %s (were %s): %s', said['alerts'], before, json.dumps(said, sort_keys=True))
                self.publish(said, subject=f"tower database: {', '.join(said['alerts']) or 'back under its thresholds'}")
            return said
        except Exception:  # noqa: BLE001
            LOG.exception('vitals: the database was not measured')
            return None
