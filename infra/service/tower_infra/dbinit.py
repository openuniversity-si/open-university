"""The database's one owner step before the service starts (P3 F1): the login the service uses, by IAM authentication.

The init container of the task runs it with the owner's password, which only that container receives; the service
container then connects as SERVICE_ROLE with an IAM token and holds no password. The role may create schemas in the
database, so the service applies the migrations and DBOS creates its own schema, and each owns what it creates.
DB-HOST-VITALS: and the extension the host's vitals are read through (HOST_EXTENSION), where the database offers it.
Idempotent: a second run changes nothing. Standard library only.
"""
import re

SERVICE_ROLE = 'tower_service'
# RUNNER-OWN-LOGIN (architecture review, finding 14): the runner's login. It owns nothing and creates nothing: what it may
# do is granted by the service, the owner of the tables (migration 0019, work.grant_runner(), after each migration pass)
RUNNER_ROLE = 'tower_runner'
IAM_ROLE = 'rds_iam'  # the RDS role that makes a login authenticate by IAM token
IDENTIFIER = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')
# DB-HOST-VITALS: the extension that reads the host's memory, swap and load through SQL (work.host_vitals(), migration
# 0017; tower_infra.vitals). Only the owner may create an extension, so this step does, where the engine offers it (RDS
# for PostgreSQL does); a database without it, or one that refuses, starts as before: a notice, never a failed start
HOST_EXTENSION = 'pg_proctab'
# ... and, since RDS keeps the extension's functions from PUBLIC (live 12/11: `permission denied for function
# pg_memusage` for the service's login), the owner's own function over them, security definer, for the service's role
# alone: work.host_vitals() (migration 0018) calls it
# HOST-PROCS (live 12/11 05:19 UTC, the first reading: 943 MB of memory, 604 MB in swap, iowait as large as the user
# time): the function also says who holds the memory (pg_proctab()'s process table: rss in pages and major faults, by what
# each connection is for, its application name; the process's own name for the rest) and the settings that size the
# server's memory, so the cut is made where the memory is
HOST_FUNCTION = 'public.tower_host'


def statements(database_name, service_role=SERVICE_ROLE, runner_role=RUNNER_ROLE):
    """The SQL of the step, for a database and roles whose names are plain identifiers."""
    for name in (database_name, service_role, runner_role):
        if not IDENTIFIER.match(name):
            raise ValueError(f'not a plain identifier: {name!r}')
    return f"""do $init$
begin
  if not exists (select 1 from pg_roles where rolname = '{service_role}') then
    create role {service_role} login;
  end if;
  if not exists (select 1 from pg_roles where rolname = '{runner_role}') then
    create role {runner_role} login;
  end if;
end $init$;
grant {IAM_ROLE} to {service_role};
grant create, connect on database {database_name} to {service_role};
grant {IAM_ROLE} to {runner_role};
grant connect on database {database_name} to {runner_role};
do $host$
begin
  if exists (select 1 from pg_available_extensions where name = '{HOST_EXTENSION}') then
    create extension if not exists {HOST_EXTENSION};
  end if;
  if to_regproc('pg_memusage') is not null and to_regproc('pg_loadavg') is not null
     and to_regproc('pg_cputime') is not null then
    execute $f$create or replace function {HOST_FUNCTION}() returns jsonb language plpgsql security definer
      set search_path = public, pg_catalog as $w$
      declare said jsonb; procs jsonb;
      begin
        said := jsonb_build_object(
          'mem', (select to_jsonb(m) from pg_memusage() m), 'load', (select to_jsonb(l) from pg_loadavg() l),
          'cpu', (select to_jsonb(c) from pg_cputime() c),
          'settings', (select jsonb_object_agg(name, current_setting(name, true)) from unnest(array[
            'shared_buffers', 'jit', 'work_mem', 'max_connections', 'huge_pages']) name));
        begin  -- HOST-PROCS: who holds the memory; a process table that cannot be read is said, the rest stays
          execute 'select jsonb_agg(to_jsonb(p)) from (select coalesce(nullif(a.application_name, ''''), t.comm) as who, '
                  || 'count(*) as n, sum(t.rss) as rss, max(t.rss) as rss_max, sum(t.majflt) as majflt '
                  || 'from pg_proctab() t left join pg_stat_activity a on a.pid = t.pid '
                  || 'group by 1 order by sum(t.rss) desc limit 12) p' into procs;
          said := said || jsonb_build_object('procs', procs);
        exception when others then
          said := said || jsonb_build_object('procs_error', sqlerrm);
        end;
        return said;
      end $w$$f$;
    revoke all on function {HOST_FUNCTION}() from public;
    grant execute on function {HOST_FUNCTION}() to {service_role};
  end if;
exception when others then
  raise notice 'the host''s vitals are not readable ({HOST_EXTENSION}): %', sqlerrm;
end $host$;
"""


def init(database, database_name, service_role=SERVICE_ROLE):
    database.run(statements(database_name, service_role))
