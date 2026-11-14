-- DB-HOST-VITALS (docs/operations/aws.md 22.9): the database's host says its own memory, swap, load and CPU times.
-- Live 12/11 the host froze for 0.3 to 1.3 s at each landing (statements of 1 ms running with no wait event, a BEGIN
-- for 127 ms): whether the db.t4g.micro is short of memory was a metric of the AWS account only (FreeableMemory,
-- SwapUsage), which no session reads. pg_proctab (an extension RDS for PostgreSQL offers; the owner's step creates it,
-- tower_infra.dbinit) reads the host's /proc through SQL: pg_memusage() (kB: memused, memfree, memshared, membuffers,
-- memcached, swapused, swapfree, swapcached), pg_loadavg() (load1, load5, load15, last_pid) and pg_cputime() (jiffies:
-- user, nice, system, idle, iowait). This function is the one name the engine calls (tower_infra.vitals): null while the
-- extension is not there, its rows as they come when it is, {error} when a function fails; it never raises, so the
-- statement that calls it never aborts the measure's transaction. Additive.
create or replace function work.host_vitals() returns jsonb language plpgsql as $$
declare said jsonb;
begin
  if to_regproc('pg_memusage') is null or to_regproc('pg_loadavg') is null or to_regproc('pg_cputime') is null then
    return null;
  end if;
  execute $q$select jsonb_build_object('mem', (select to_jsonb(m) from pg_memusage() m),
                                       'load', (select to_jsonb(l) from pg_loadavg() l),
                                       'cpu', (select to_jsonb(c) from pg_cputime() c))$q$ into said;
  return said;
exception when others then
  return jsonb_build_object('error', sqlerrm);
end $$;
