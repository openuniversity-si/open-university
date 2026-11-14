"""The migrations of the infrastructure's schemas, applied when the service starts (P3 F1).

Every infra/db/migrations/NNNN_name.sql the database has not applied runs in order, each in one transaction together
with the partitions of log.event for this month and the next and the event platform.migration.applied that records
it, under a session advisory lock so two starting tasks never apply one migration twice. What is applied is read from
the log itself: the schemas keep the thirteen tables of ARQUITETURA-ALVO §3. Every start also keeps the next month's
partition of log.event ahead of the clock.

The database is any object with rows(sql) -> list of tuples and run(sql), which executes a script in one transaction:
psycopg in the service (scripts of many statements go by the simple query protocol), psql in the gate's test. This
module uses the standard library only.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile

NAME = re.compile(r'^\d{4}_[a-z0-9_]+\.sql$')
EVENT = 'platform.migration.applied'
LOCK = "select pg_advisory_lock(hashtext('tower-infra-migrations'))"
UNLOCK = "select pg_advisory_unlock(hashtext('tower-infra-migrations'))"
HAS_LOG = "select to_regclass('log.event') is not null"
APPLIED = f"select payload->>'migration' from log.event where type = '{EVENT}' order by occurred_at"
# RUNNER-OWN-LOGIN: what the runner's login may do is granted here, by the owner of the tables, on every pass: the login is
# created by the owner's step (dbinit), which may run after the migration that made the grants' function was applied
GRANTS = """do $grants$
begin
  if to_regprocedure('work.grant_runner()') is not null then
    perform work.grant_runner();
  end if;
end $grants$;"""
PARTITIONS = """do $partitions$
declare first_day date;
begin
  for first_day in select generate_series(date_trunc('month', now()), date_trunc('month', now()) + interval '1 month',
                                          interval '1 month')::date loop
    execute format('create table if not exists log.%I partition of log.event for values from (%L) to (%L)',
                   'event_' || to_char(first_day, 'YYYY_MM'), first_day, (first_day + interval '1 month')::date);
  end loop;
end $partitions$;"""


def migrations(directory):
    """The migration files of a directory, in the order of their numbers."""
    return sorted(path for path in Path(directory).iterdir() if NAME.match(path.name))


def truthy(value):
    return value in (True, 't', 'true')


def applied(database):
    """The names of the migrations the log records as applied; none before the first migration creates the log."""
    if not truthy(database.rows(HAS_LOG)[0][0]):
        return []
    return [row[0] for row in database.rows(APPLIED)]


def script(path, producer):
    """One migration as one transaction: the migration, the partitions it may need now, and the event recording it."""
    sql = path.read_text(encoding='utf-8')
    payload = json.dumps({'migration': path.stem, 'sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest()})
    event = (f"insert into log.event (event_id, type, occurred_at, producer, subject, payload) values "
             f"('{EVENT}:{path.stem}', '{EVENT}', clock_timestamp(), '{producer}', 'migration/{path.stem}', "
             f"'{payload}'::jsonb);")
    return f'{sql.rstrip()}\n{PARTITIONS}\n{event}\n'


def migrate(database, directory, producer):
    """Apply what is missing and keep the partitions ahead; returns the names applied by this call."""
    database.rows(LOCK)
    try:
        done = set(applied(database))
        names = []
        for path in migrations(directory):
            if path.stem not in done:
                database.run(script(path, producer))
                names.append(path.stem)
        database.run(PARTITIONS)
        database.run(GRANTS)
        return names
    finally:
        database.rows(UNLOCK)


def migrate_bundle(database, data, producer):
    """SLOW-PATH-NO-ROLLOUT-WAIT: migrate() from the migrations a code bundle carries (scripts/lib/lambda_package.py
    build_code: migrations/<file>), so the live service applies a head's migrations ahead of that head's tasks."""
    with tempfile.TemporaryDirectory(prefix='tower-migrations-') as directory, zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            folder, _, file = name.partition('/')
            if folder == 'migrations' and NAME.match(file):
                (Path(directory) / file).write_bytes(archive.read(name))
        return migrate(database, directory, producer)
