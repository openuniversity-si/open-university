import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }) }));
vi.mock("next/cache", () => ({ unstable_cache: (read: () => unknown) => read }));
import { releaseFixture } from "../../../test/fixtures/release.ts";
import generated from "../domain/generated/release.json" with { type: "json" };
import { bakedReleaseSchema } from "../domain/baked.ts";
import { normalizeBakedRelease } from "../domain/fallback.ts";
import { cachedReleaseReader, DATA_CACHE_ENTRY_LIMIT_BYTES, readActiveRelease, readActiveSha, readReleaseBySha, releaseMemory, resolveCatalog } from "./read.ts";
import { releaseSha } from "../../kernel/sha.ts";

const release = releaseFixture();
const sha = releaseSha(release);

describe("getCatalog: active release, baked fallback (ADR-17)", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("serves the database release when it answers", async () => {
    const state = await resolveCatalog(() => Promise.resolve({ release, sha }), { APP_DATABASE_URL: "postgres://db" });
    expect(state).toEqual({ catalog: release, sha, source: "database" });
  });

  it("falls back to the baked release with one CATALOG_FALLBACK log when the database is down", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const state = await resolveCatalog(() => Promise.reject(new Error("connect ECONNREFUSED secret-host")), { APP_DATABASE_URL: "postgres://db" });
    expect(state.source).toBe("fallback");
    const baked = normalizeBakedRelease(generated);
    expect(state.catalog).toEqual(baked.release);
    expect(state.sha).toBe(baked.sha);
    expect(log.mock.calls).toEqual([[JSON.stringify({ event: "CATALOG_FALLBACK" })]]);
  });

  it("prerenders from the baked release, silently, in a build without a database", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const read = vi.fn(() => Promise.resolve({ release, sha }));
    const state = await resolveCatalog(read, { NEXT_PHASE: "phase-production-build" });
    expect(state.source).toBe("fallback");
    expect(read).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });

  it("reads and validates the single active row", async () => {
    const query = vi.fn(() => Promise.resolve({ rows: [{ payload: release, payload_sha256: sha }] }));
    await expect(readActiveRelease({ query })).resolves.toEqual({ release, sha });
    expect(query).toHaveBeenCalledWith("SELECT payload, payload_sha256 FROM catalog_releases WHERE is_active");
    await expect(readActiveRelease({ query: () => Promise.resolve({ rows: [] }) })).rejects.toThrow("No active catalog release.");
    await expect(readActiveRelease({ query: () => Promise.resolve({ rows: [{ payload: { ...release, courses: [] }, payload_sha256: sha }] }) })).rejects.toThrow();
  });
});

describe("baked release (catalog:bake)", () => {
  it("is a valid release with its SHA-256", () => {
    const stored = bakedReleaseSchema.parse(generated);
    expect(["database", "fixture"]).toContain(stored.source);
    expect(releaseSha(stored.release)).toBe(stored.sha);
    // Served normalized to the current version (a baked v1 release reads as one edition per course, ADR-21).
    const baked = normalizeBakedRelease(generated);
    expect(baked.sha).toBe(stored.sha);
    expect(baked.release.schemaVersion).toBe(2);
    expect(baked.release.courses.every((course) => course.editions.length > 0)).toBe(true);
  });
});

describe("catalog cache stays under the Data Cache limit (entries over 2 MB are refused)", () => {
  // A release the size of production's (3.8 MB at 311 courses), padded from the fixture.
  const big = { ...release, courses: release.courses.map((course) => ({ ...course, about: `${course.about ?? ""}${"x".repeat(4_000_000)}` })) };

  it("caches only the SHA: the cached entry is far below 2 MB even for a 3.8 MB+ payload", async () => {
    const query = vi.fn(() => Promise.resolve({ rows: [{ payload: big, payload_sha256: sha }] }));
    const entry = await readActiveSha({ query });
    expect(JSON.stringify(big).length).toBeGreaterThan(DATA_CACHE_ENTRY_LIMIT_BYTES);
    expect(Buffer.byteLength(JSON.stringify(entry))).toBeLessThan(DATA_CACHE_ENTRY_LIMIT_BYTES);
    expect(query).toHaveBeenCalledWith("SELECT payload_sha256 FROM catalog_releases WHERE is_active");
  });

  it("fails if the release payload itself would be the cached entry", () => {
    // Guard for a regression to caching readActiveRelease: production's payload size is over the limit.
    expect(Buffer.byteLength(JSON.stringify({ release: big, sha }))).toBeGreaterThan(DATA_CACHE_ENTRY_LIMIT_BYTES);
  });

  it("reads one release by SHA, validated", async () => {
    const query = vi.fn(() => Promise.resolve({ rows: [{ payload: release, payload_sha256: sha }] }));
    await expect(readReleaseBySha({ query }, sha)).resolves.toEqual({ release, sha });
    expect(query.mock.calls[0]).toEqual(["SELECT payload, payload_sha256 FROM catalog_releases WHERE payload_sha256 = $1 ORDER BY number DESC LIMIT 1", [sha]]);
    await expect(readReleaseBySha({ query: () => Promise.resolve({ rows: [] }) }, sha)).rejects.toThrow("No catalog release with that SHA.");
  });

  it("reads the payload once per SHA per instance, again when the active SHA changes", async () => {
    let active = "a";
    const load = vi.fn((key: string) => Promise.resolve({ release, sha: key }));
    const read = cachedReleaseReader(() => Promise.resolve(active), load);
    await read(); await read(); await read();
    expect(load).toHaveBeenCalledTimes(1);
    active = "b";
    await expect(read()).resolves.toEqual({ release, sha: "b" });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("drops a failed read so the next request retries, and keeps at most two releases", async () => {
    let fail = true;
    const load = vi.fn((key: string) => (fail ? Promise.reject(new Error("down")) : Promise.resolve({ release, sha: key })));
    const memory = releaseMemory(load);
    await expect(memory("a")).rejects.toThrow("down");
    fail = false;
    await expect(memory("a")).resolves.toMatchObject({ sha: "a" });
    await memory("b"); await memory("c"); await memory("a");
    expect(load.mock.calls.map(([key]) => key)).toEqual(["a", "a", "b", "c", "a"]);
  });
});
