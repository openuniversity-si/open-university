import type { Queryable } from "../db/uow.ts";

export interface AdminRateLimiter {
  allow(ip: string): boolean;
  fail(ip: string): void;
  retryAfter(): number;
  /** Zero means admitted; otherwise seconds until the next fixed minute. Keys are digests, never secrets. */
  authenticated(key: string): Promise<number>;
}

/** Failed/anonymous authentication is bounded locally; valid Bearers never spend this IP allowance. */
export function createAdminRateLimiter(limits: { requests: number; failures: number; authenticated?: number } = { requests: 30, failures: 10, authenticated: 600 }, windowMs = 60_000, now = () => Date.now()): AdminRateLimiter {
  const windows = new Map<string, { minute: number; requests: number; failures: number }>();
  const current = (key: string) => {
    const minute = Math.floor(now() / windowMs);
    let entry = windows.get(key);
    if (!entry || entry.minute !== minute) {
      if (windows.size > 10_000) windows.clear();
      entry = { minute, requests: 0, failures: 0 };
      windows.set(key, entry);
    }
    return entry;
  };
  const retryAfter = () => Math.max(1, Math.ceil((windowMs - now() % windowMs) / 1000));
  return {
    allow(ip) { const entry = current(`ip:${ip}`); entry.requests += 1; return entry.requests <= limits.requests && entry.failures < limits.failures; },
    fail(ip) { current(`ip:${ip}`).failures += 1; },
    retryAfter,
    authenticated(key) { const entry = current(`secret:${key}`); entry.requests += 1; return Promise.resolve(entry.requests <= (limits.authenticated ?? 600) ? 0 : retryAfter()); },
  };
}

/** One atomic statement using the database clock: all instances share 600 admissions per secret per minute.
 * A single row per secret is reused across windows, so the table does not grow with traffic or minutes.
 */
export async function consumeAuthenticated(db: Queryable, key: string, limit = 600): Promise<number> {
  const { rows } = await db.query(`WITH clock AS (
    SELECT floor(extract(epoch FROM statement_timestamp()) / 60)::bigint AS minute,
      greatest(1, ceil(60 - mod(extract(epoch FROM statement_timestamp()), 60)))::int AS retry_after
  ), admitted AS (
    INSERT INTO admin_rate_limits (secret_hash, minute, requests)
    SELECT $1, minute, 1 FROM clock
    ON CONFLICT (secret_hash) DO UPDATE SET minute = greatest(admin_rate_limits.minute, EXCLUDED.minute),
      requests = CASE WHEN admin_rate_limits.minute < EXCLUDED.minute THEN 1
        WHEN admin_rate_limits.minute = EXCLUDED.minute THEN least(admin_rate_limits.requests + 1, $2 + 1)
        ELSE admin_rate_limits.requests END
    RETURNING requests, minute
  ) SELECT admitted.requests, admitted.minute = clock.minute AS current_window, clock.retry_after FROM admitted CROSS JOIN clock`, [key, limit]);
  if (!rows[0]) throw new Error("Admin limiter did not return a counter.");
  return rows[0].current_window === true && Number(rows[0].requests) <= limit ? 0 : Number(rows[0].retry_after);
}

export const adminRateLimiter: AdminRateLimiter = {
  ...createAdminRateLimiter(),
  async authenticated(key) {
    const { appPool } = await import("../db/pool.ts");
    return consumeAuthenticated(appPool(), key);
  },
};
