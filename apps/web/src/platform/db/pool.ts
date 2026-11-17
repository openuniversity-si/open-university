import "server-only";
import pg from "pg";
import { LIMITS } from "../../kernel/limits.ts";
import { getDatabaseEnv } from "./database-env.ts";

/** The pool the session adapter receives. Callers do not import the driver. */
export type AppPool = pg.Pool;

// One pool per process, shared by every runtime consumer, including Better Auth.
let pool: AppPool | undefined;
export function appPool(): AppPool {
  if (pool) return pool;
  const { databaseUrl, maxPoolSize } = getDatabaseEnv();
  pool = new pg.Pool({ connectionString: databaseUrl, max: maxPoolSize, idleTimeoutMillis: LIMITS.dbIdleMs, connectionTimeoutMillis: LIMITS.dbConnectMs, statement_timeout: LIMITS.dbStatementMs });
  return pool;
}

/** Process-local pressure. The connection itself stays inside this module. */
export function poolPressure(): Readonly<{ total: number; idle: number; waiting: number }> {
  if (!pool) return { total: 0, idle: 0, waiting: 0 };
  return { total: pool.totalCount, idle: pool.idleCount, waiting: pool.waitingCount };
}
