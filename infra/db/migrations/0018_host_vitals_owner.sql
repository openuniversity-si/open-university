-- DB-HOST-VITALS, the owner's function (docs/operations/aws.md 22.9). Live 12/11 04:52 UTC, the first rollout after
-- migration 0017: the owner's step created pg_proctab and work.host_vitals() answered {error: permission denied for
-- function pg_memusage}: RDS keeps the extension's functions from PUBLIC, and the service's login is not the owner.
-- The owner's step (tower_infra.dbinit) now makes public.tower_host(), security definer, for the service's role alone:
-- the three functions' rows as one jsonb, read as the owner. This function calls it when it is there, and the
-- extension's functions directly otherwise (a database that does not keep them from the service). Never raises. Additive.
create or replace function work.host_vitals() returns jsonb language plpgsql as $$
declare said jsonb;
begin
  if to_regprocedure('public.tower_host()') is not null then
    execute 'select public.tower_host()' into said;
    return said;
  end if;
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
