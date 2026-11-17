import type { QueryResultRow } from "pg";
import type { CoverOwner } from "../../kernel/cover-kinds.ts";

/**
 * The shared database contract; accepts pg pools/clients and small in-memory adapters.
 * The row type sits on the interface, not the method: a generic method is not assignable from pg.Pool or a test double.
 */
export interface Queryable<R extends QueryResultRow = Record<string, unknown>> {
  query(sql: string, values?: unknown[]): Promise<{ rows: R[]; rowCount?: number | null }>;
}
export interface PooledClient extends Queryable { release(destroy?: boolean | Error): void }
export interface DbPool extends Queryable { connect(): Promise<PooledClient> }
export type MediaLock =
  | { readonly scope: "media-maintenance"; readonly mode: "shared" | "exclusive" }
  | { readonly scope: "media-owner"; readonly owner: CoverOwner; readonly ownerId: string };
export type AdvisoryLock =
  | { readonly scope: "xact"; readonly key: string }
  | { readonly scope: "xact-hashtext"; readonly key: string }
  | MediaLock;
export interface UnitOfWork extends Queryable {
  acquireLock(lock: AdvisoryLock): Promise<void>;
  onAfterCommit(effect: () => Promise<void> | void): void;
}

/** One connection and one transaction. Effects run after release, never in the rollback path. */
export async function withUnitOfWork<T>(pool: DbPool, work: (uow: UnitOfWork) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  const effects: (() => Promise<void> | void)[] = [];
  let broken = false;
  let result: T;
  try {
    try { await client.query("BEGIN"); } catch (error) { broken = true; throw error; }
    try {
      const uow: UnitOfWork = {
        query: (sql, values) => client.query(sql, values),
        async acquireLock(lock) {
          if (lock.scope === "xact") await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [lock.key]);
          else if (lock.scope === "media-maintenance") {
            const fn = lock.mode === "exclusive" ? "pg_advisory_xact_lock" : "pg_advisory_xact_lock_shared";
            await client.query(`SELECT ${fn}(742020, 0)`);
          } else if (lock.scope === "media-owner") {
            await client.query("SELECT pg_advisory_xact_lock(742020, CASE WHEN hashtext($1) = 0 THEN 1 ELSE hashtext($1) END)", [`${lock.owner}:${lock.ownerId}`]);
          } else if (lock.key === "catalog:release") await client.query("SELECT pg_advisory_xact_lock(hashtext('catalog:release'))");
          else await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [lock.key]);
        },
        onAfterCommit(effect) { effects.push(effect); },
      };
      result = await work(uow);
      await client.query("COMMIT");
    } catch (error) {
      try { await client.query("ROLLBACK"); } catch { broken = true; }
      throw error;
    }
  } finally { client.release(broken); }
  for (const effect of effects) await effect();
  return result;
}
