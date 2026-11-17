import { createBulkR2Store as createConfiguredBulkR2Store } from "../../src/media/server/r2-bulk.ts";
import { mapLimited as mapWithBudget } from "../../src/media/server/r2-budget.ts";
import { StorageError, type R2Access } from "../../src/media/server/r2.ts";
import type { MediaObjectStore } from "../../src/media/server/storage.ts";
import { installMigrationDnsCache, migrationDnsHosts } from "./migrate-dns.ts";

type Env = Readonly<Record<string, string | undefined>>;

/**
 * Bulk R2 path (E2 migration now; later bundle and release jobs). The site's request path stays in
 * `src/media/server/r2.ts`: one call, its own timeout and retry, no DNS patch and no extra dependency.
 * This module is loaded only by scripts. It resolves the R2 host once and caps parallel requests.
 */
export function r2Concurrency(env: Env): number {
  const raw = env.R2_CONCURRENCY?.trim() ?? "";
  if (raw === "") return 4;
  const value = Number(raw);
  if (!/^[1-9]\d*$/.test(raw) || !Number.isSafeInteger(value) || value > 16) throw new StorageError("R2_CONCURRENCY must be an integer from 1 to 16.");
  return value;
}

/**
 * `R2_CONCURRENCY` workers (default 4). A slow connect stalls one slot. The first failure stops new work;
 * in-flight work drains before the error propagates. Results keep input order.
 */
export async function mapLimited<T, R>(items: readonly T[], work: (item: T) => Promise<R>, env: Env = process.env): Promise<R[]> {
  return mapWithBudget(items, work, { concurrency: r2Concurrency(env), attempts: 5, attemptTimeoutMs: 15_000, totalTimeoutMs: 60_000 });
}

/** Same store as the site, plus the bulk DNS cache for this process. Safe to call more than once. */
export function createBulkR2Store(env: Env, access: R2Access): MediaObjectStore {
  installMigrationDnsCache(migrationDnsHosts(env));
  return createConfiguredBulkR2Store(env, access);
}
