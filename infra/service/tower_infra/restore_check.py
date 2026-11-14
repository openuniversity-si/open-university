"""RESTORE-DRILL (architecture review, finding 25): what a database of the engine holds, read only.

tower-data keeps seven days of automatic backups and nothing had ever been restored from them: a backup that was never
restored is a hope. The rehearsal restores it into a temporary instance of the same class (the account's owner does
that, and deletes it after), and this is the reading that says the restored database is the engine's: one statement,
in a read-only session, as the owner (the init container's credentials, TOWER_DB_OWNER and its password, which only
that container receives), on the database TOWER_DB_HOST names. The same reading of production, at the same moment, is
what it is compared with: the restored one holds no more than production, the same migrations, and its newest event
is as old as the restore point.

    python -m tower_infra restore-check     one line of JSON on stdout: facts(db)

It writes nothing and changes nothing; a database that refuses a read-only session is not read. Standard library only.
"""
import json

from . import migrations

READ_ONLY = 'set default_transaction_read_only = on'
FACTS = (
    "select jsonb_build_object("
    "'database', current_database(), 'server', current_setting('server_version'), "
    "'read_only', current_setting('default_transaction_read_only'), "
    "'at', round(extract(epoch from clock_timestamp())::numeric, 3), "
    "'size_bytes', pg_database_size(current_database()), "
    f"'migrations', (select count(*) from log.event where type = '{migrations.EVENT}'), "
    f"'newest_migration', (select payload->>'migration' from log.event where type = '{migrations.EVENT}' "
    "order by occurred_at desc limit 1), "
    "'tenants', (select count(*) from work.tenant), 'jobs', (select count(*) from work.job), "
    "'runs', (select count(*) from work.run), 'settings', (select count(*) from work.config_value), "
    "'events', (select count(*) from log.event), "
    "'newest_event_at', (select round(extract(epoch from max(occurred_at))::numeric, 3) from log.event), "
    "'newest_job_at', (select round(extract(epoch from uuid_extract_timestamp(id))::numeric, 3) from work.job "
    "order by id desc limit 1), "
    "'jobs_open', (select count(*) from work.job where state in ('queued', 'running', 'waiting')), "
    "'pointers', (select jsonb_object_agg(key, value) from work.config_value where key like 'deploy.live_%')"
    ")::text")


def facts(db):
    """What the database holds: its name and server, its size, the migrations it has and the newest, how many tenants,
    jobs, runs, settings and events, the newest event's and job's time, the jobs still open and the deploy's pointers."""
    db.rows(READ_ONLY)
    return json.loads(db.rows(FACTS)[0][0])


def compared(restored, production):
    """Whether a restored database's facts are the engine's backup of production's: [why not, ...], empty when they are.
    The restored one is of the same database and server, has every migration production has (a restore point before
    the newest migration has fewer, never others), holds no more of anything than production, and holds something."""
    why = []
    for name in ('database', 'server'):
        if restored.get(name) != production.get(name):
            why.append(f'{name}: {restored.get(name)!r} is not production\'s {production.get(name)!r}')
    for name in ('migrations', 'tenants', 'jobs', 'runs', 'events'):
        if not isinstance(restored.get(name), int) or restored[name] <= 0:
            why.append(f'{name}: the restored database has none')
        elif restored[name] > production.get(name, 0):
            why.append(f'{name}: {restored[name]} restored, {production.get(name)} in production')
    if (restored.get('newest_event_at') or 0) > (production.get('newest_event_at') or 0):
        why.append('newest_event_at: the restored database is ahead of production')
    return why
