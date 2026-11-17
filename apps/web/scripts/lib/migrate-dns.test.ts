import { createRequire } from "node:module";
import type * as Dns from "node:dns";
import { describe, expect, it } from "vitest";
import { createCachedLookup, installMigrationDnsCache, migrationDnsHosts } from "./migrate-dns.ts";

const nodeRequire = createRequire(import.meta.url);
type LookupCallback = (err: NodeJS.ErrnoException | null, address: string | Dns.LookupAddress[], family?: number) => void;

function once(lookup: (hostname: string, options: Dns.LookupOptions, callback: LookupCallback) => void, hostname: string, options: Dns.LookupOptions = {}): Promise<string | Dns.LookupAddress[]> {
  return new Promise((resolve, reject) => {
    lookup(hostname, options, (err, address) => { if (err) reject(err); else resolve(address); });
  });
}

describe("migration DNS cache", () => {
  it("names the R2 endpoint host and the public media host", () => {
    const account = "a".repeat(32);
    expect(migrationDnsHosts({ R2_ACCOUNT_ID: account })).toEqual([`${account}.r2.cloudflarestorage.com`, "media.openuniversity.si"]);
    expect(migrationDnsHosts({ R2_ENDPOINT: "http://127.0.0.1:9", R2_ACCOUNT_ID: account })).toEqual(["127.0.0.1", "media.openuniversity.si"]);
    expect(migrationDnsHosts({ R2_ENDPOINT: "https://evil.example" })).toEqual(["media.openuniversity.si"]);
  });
  it("resolves an allowed host once and leaves every other host on the original lookup", async () => {
    let calls = 0;
    let finish: LookupCallback = () => undefined;
    const lookup = (hostname: string, _options: Dns.LookupOptions, callback: LookupCallback) => {
      calls += 1;
      if (hostname === "r2.example") finish = callback;
      else callback(null, "198.51.100.2", 4);
    };
    const cached = createCachedLookup(["r2.example"], lookup, 1000);
    const pending = Promise.all([once(cached, "r2.example", { all: true }), once(cached, "r2.example", { all: true })]);
    expect(calls).toBe(1);
    finish(null, [{ address: "203.0.113.8", family: 4 }]);
    await expect(pending).resolves.toEqual([[{ address: "203.0.113.8", family: 4 }], [{ address: "203.0.113.8", family: 4 }]]);
    await expect(once(cached, "r2.example", { all: true })).resolves.toEqual([{ address: "203.0.113.8", family: 4 }]);
    expect(calls).toBe(1);
    await expect(once(cached, "db.example.invalid")).resolves.toBe("198.51.100.2");
    await expect(once(cached, "db.example.invalid")).resolves.toBe("198.51.100.2");
    expect(calls).toBe(3);
  });
  it("stops waiting on a hung lookup and keeps a late answer for the next attempt", async () => {
    let calls = 0;
    let finish: LookupCallback = () => undefined;
    const cached = createCachedLookup(["slow.example"], (_hostname, _options, callback) => { calls += 1; finish = callback; }, 20);
    await expect(once(cached, "slow.example")).rejects.toThrow("DNS lookup timed out");
    finish(null, "203.0.113.9", 4);
    await expect(once(cached, "slow.example")).resolves.toBe("203.0.113.9");
    expect(calls).toBe(1);
  });
  it("installs the cache on node:dns and restores the previous lookup", async () => {
    const dns = nodeRequire("node:dns") as typeof Dns;
    const original = dns.lookup;
    let calls = 0;
    dns.lookup = ((hostname: string, options: Dns.LookupOptions | LookupCallback, callback?: LookupCallback) => {
      calls += 1;
      const done = typeof options === "function" ? options : callback;
      done?.(null, "203.0.113.4", 4);
    }) as typeof dns.lookup;
    const restore = installMigrationDnsCache(["cache.example"]);
    try {
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "cache.example")).resolves.toBe("203.0.113.4");
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "cache.example")).resolves.toBe("203.0.113.4");
      expect(calls).toBe(1);
    } finally {
      restore();
      dns.lookup = original;
    }
  });
  it("keeps the first installation when asked again", async () => {
    const dns = nodeRequire("node:dns") as typeof Dns;
    const original = dns.lookup;
    let calls = 0;
    dns.lookup = ((hostname: string, options: Dns.LookupOptions | LookupCallback, callback?: LookupCallback) => {
      calls += 1;
      const done = typeof options === "function" ? options : callback;
      done?.(null, hostname, 4);
    }) as typeof dns.lookup;
    const first = installMigrationDnsCache(["cache.example"]);
    const second = installMigrationDnsCache(["other.example"]);
    try {
      expect(second).toBe(first);
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "cache.example")).resolves.toBe("cache.example");
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "cache.example")).resolves.toBe("cache.example");
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "other.example")).resolves.toBe("other.example");
      await expect(once((host, options, callback) => { dns.lookup(host, options, callback); }, "other.example")).resolves.toBe("other.example");
      expect(calls).toBe(3);
    } finally {
      first();
      dns.lookup = original;
    }
  });
});
