import { createRequire } from "node:module";
import type * as Dns from "node:dns";
import "../../src/media/server/public-hosts.ts";
import { mediaPublicHost } from "../../src/media/domain/types.ts";

const nodeRequire = createRequire(import.meta.url);
type Env = Readonly<Record<string, string | undefined>>;
const localEndpoint = /^http:\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+$/;
const DNS_TIMEOUT_MS = 5_000;

type LookupCallback = (err: NodeJS.ErrnoException | null, address: string | Dns.LookupAddress[], family?: number) => void;
type LookupResult = [NodeJS.ErrnoException | null, string | Dns.LookupAddress[], number | undefined];
interface LookupWaiter { callback: LookupCallback; timer: NodeJS.Timeout }
interface PendingLookup { waiters: LookupWaiter[] }

/**
 * Hosts this migration resolves more than once. Only the R2 API host and the public media host are cached.
 * Every other name, including the database host, is passed straight to Node's resolver.
 */
export function migrationDnsHosts(env: Env): string[] {
  const hosts = new Set<string>();
  if (env.R2_ENDPOINT) {
    if (localEndpoint.test(env.R2_ENDPOINT)) hosts.add(new URL(env.R2_ENDPOINT).hostname);
  } else if (/^[a-f0-9]{32}$/.test(env.R2_ACCOUNT_ID ?? "")) hosts.add(`${env.R2_ACCOUNT_ID ?? ""}.r2.cloudflarestorage.com`);
  try { hosts.add(mediaPublicHost(env)); } catch { /* The media client reports an invalid public-host override. */ }
  return [...hosts];
}

function cacheKey(hostname: string, options: Dns.LookupOptions): string {
  return JSON.stringify([hostname, options.family ?? null, options.hints ?? null, options.all === true, options.order ?? null]);
}

/** One in-flight lookup per host and option set. A late answer is kept after a waiter has already timed out. */
export function createCachedLookup(hosts: readonly string[], lookup: (hostname: string, options: Dns.LookupOptions, callback: LookupCallback) => void, timeoutMs = DNS_TIMEOUT_MS) {
  const allowed = new Set(hosts);
  const cache = new Map<string, LookupResult>();
  const pending = new Map<string, PendingLookup>();
  return (hostname: string, options: Dns.LookupOptions, callback: LookupCallback): void => {
    if (!allowed.has(hostname)) {
      lookup(hostname, options, callback);
      return;
    }
    const key = cacheKey(hostname, options);
    const hit = cache.get(key);
    if (hit) {
      queueMicrotask(() => { callback(hit[0], hit[1], hit[2]); });
      return;
    }
    const waiter: LookupWaiter = {
      callback,
      timer: setTimeout(() => {
        const current = pending.get(key);
        if (!current) return;
        const index = current.waiters.indexOf(waiter);
        if (index < 0) return;
        current.waiters.splice(index, 1);
        const error = Object.assign(new Error("DNS lookup timed out"), { code: "ETIMEDOUT" });
        callback(error, "");
      }, timeoutMs),
    };
    const existing = pending.get(key);
    if (existing) {
      existing.waiters.push(waiter);
      return;
    }
    pending.set(key, { waiters: [waiter] });
    lookup(hostname, options, (err, address, family) => {
      const current = pending.get(key);
      pending.delete(key);
      if (!err) cache.set(key, [null, address, family]);
      if (!current) return;
      for (const waiting of current.waiters) {
        clearTimeout(waiting.timer);
        if (err) waiting.callback(err, "");
        else waiting.callback(null, address, family);
      }
    });
  };
}

/**
 * Installs the cache on Node's shared resolver for this process only. `fetch` in the migration reaches it;
 * the site server never loads this module. Returns a function that restores the previous lookup.
 */
let restoreInstalled: (() => void) | undefined;

export function installMigrationDnsCache(hosts: readonly string[], timeoutMs = DNS_TIMEOUT_MS): () => void {
  if (hosts.length === 0) return () => undefined;
  if (restoreInstalled) return restoreInstalled;
  const dns = nodeRequire("node:dns") as typeof Dns;
  const real = dns.lookup;
  const cached = createCachedLookup(hosts, (hostname, options, callback) => { real(hostname, options, callback); }, timeoutMs);
  const wrapped = (hostname: string, options: Dns.LookupOptions | number | LookupCallback, callback?: LookupCallback): void => {
    if (typeof options === "function") {
      cached(hostname, {}, options);
      return;
    }
    if (typeof options === "number") {
      if (!callback) throw new Error("DNS lookup is missing a callback.");
      cached(hostname, { family: options }, callback);
      return;
    }
    if (!callback) throw new Error("DNS lookup is missing a callback.");
    cached(hostname, options, callback);
  };
  dns.lookup = wrapped as typeof dns.lookup;
  restoreInstalled = () => {
    if (dns.lookup === (wrapped as typeof dns.lookup)) dns.lookup = real;
    restoreInstalled = undefined;
  };
  return restoreInstalled;
}
