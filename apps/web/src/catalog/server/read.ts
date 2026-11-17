import "server-only";
import { CACHE } from "../../kernel/cache.ts";
import { currentEnv, getBuildEnv } from "../../kernel/env.ts";
import { buildEnvFromHost } from "../../platform/host/env.ts";
import { buildWithoutDatabase } from "../../platform/db/database-env.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import { coverHashes, resolveCatalogCoverObjects } from "../domain/cover-object.ts";
import { readObjects } from "./media-gateway.ts";
import { productionMediaPolicy } from "../../media/domain/types.ts";
import { remember } from "../../platform/freshness/next.ts";
import { cache } from "react";
import { appPool } from "../../platform/db/pool.ts";
import { draftCatalogState } from "./draft.ts";
import generated from "../domain/generated/release.json" with { type: "json" };
import { normalizeBakedRelease } from "../domain/fallback.ts";
import { parseRelease, RELEASE_SCHEMA_VERSION, type PublicCatalog } from "../domain/release.ts";
import { readActivePayloadSha, readActiveReleasePayload, readProjectedRelease, readReleasePayloadBySha } from "./projections-repo.ts";

/** Every cached catalog read carries this tag; activating a release revalidates it (ADR-17). */
export const CATALOG_TAG = "catalog";

export interface CatalogState {
  readonly catalog: PublicCatalog;
  readonly sha: string;
  /** `fallback`: the release baked at build time, because the database read failed (or a CI build has none); `preview`: the draft catalog (ADR-18). */
  readonly source: "database" | "fallback" | "fake" | "preview";
}

export interface CatalogDatabase {
  query(sql: string, params?: readonly unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

/** Next's Data Cache refuses entries over 2 MB; the full release passed that (3.8 MB at 311 courses) and was re-read on every render. */
export const DATA_CACHE_ENTRY_LIMIT_BYTES = CACHE.platformEntryBytes;

/** The active release's SHA only: the tiny value that goes into the Data Cache (the payload never does). */
export async function readActiveSha(db: CatalogDatabase): Promise<string> {
  return readActivePayloadSha(db);
}

/** One release by SHA, validated like the active one. */
async function withCoverObjects(db: CatalogDatabase, release: PublicCatalog): Promise<PublicCatalog> {
  const hashes = coverHashes(release);
  const objects = hashes.length === 0 ? [] : await readObjects(db, hashes);
  return resolveCatalogCoverObjects(objects, release, productionMediaPolicy);
}

/** The same cover-object pass the v2 reader applies, so a stitched page matches the active release. */
export async function presentCatalog(release: PublicCatalog): Promise<PublicCatalog> {
  return withCoverObjects(appPool(), release);
}

export async function readReleaseBySha(db: CatalogDatabase, sha: string): Promise<{ release: PublicCatalog; sha: string }> {
  const row = await readReleasePayloadBySha(db, sha);
  return { release: await withCoverObjects(db, parseRelease(row.payload)), sha: row.sha };
}

/**
 * Parsed releases held in this server instance's memory, keyed by SHA (content-addressed, so never stale). The two most
 * recent are kept; a failed read is dropped so the next request retries.
 */
export function releaseMemory(load: (sha: string) => Promise<{ release: PublicCatalog; sha: string }>, keep = 2) {
  const entries = new Map<string, Promise<{ release: PublicCatalog; sha: string }>>();
  return (sha: string): Promise<{ release: PublicCatalog; sha: string }> => {
    const hit = entries.get(sha);
    if (hit) return hit;
    const pending = load(sha);
    entries.set(sha, pending);
    pending.catch(() => { entries.delete(sha); });
    while (entries.size > keep) { const oldest = entries.keys().next().value; if (oldest === undefined) break; entries.delete(oldest); }
    return pending;
  };
}

/** Composes the cached SHA lookup with the in-memory payload: the database payload is read once per instance per release. */
export function cachedReleaseReader(activeSha: () => Promise<string>, bySha: (sha: string) => Promise<{ release: PublicCatalog; sha: string }>) {
  const memory = releaseMemory(bySha);
  return async (): Promise<{ release: PublicCatalog; sha: string }> => memory(await activeSha());
}

/** The active release, normalized to the current schema version (an activated version 1 release reads as one edition per course, ADR-21). */
export async function readActiveRelease(db: CatalogDatabase): Promise<{ release: PublicCatalog; sha: string }> {
  const row = await readActiveReleasePayload(db);
  return { release: await withCoverObjects(db, parseRelease(row.payload)), sha: row.sha };
}

let bakedCache: ReturnType<typeof normalizeBakedRelease> | undefined;
/** The release baked at build time, normalized once. Served only when the database read fails on a cache miss. */
function bakedRelease(): ReturnType<typeof normalizeBakedRelease> {
  if (bakedCache) return bakedCache;
  return bakedCache = normalizeBakedRelease(generated);
}

/** The active release, or the baked one with a `CATALOG_FALLBACK` log when the database cannot answer. */
export async function resolveCatalog(read: () => Promise<{ release: PublicCatalog; sha: string }>, env: Readonly<Record<string, string | undefined>> = currentEnv()): Promise<CatalogState> {
  const fallback = (): CatalogState => {
    const baked = bakedRelease();
    return { catalog: baked.release, sha: baked.sha, source: "fallback" };
  };
  // CI's production build has no database: it prerenders from the baked snapshot (a hosted build with APP_DATABASE_URL reads the database).
  if (buildWithoutDatabase(env)) return fallback();
  try {
    const { release, sha } = await read();
    return { catalog: release, sha, source: "database" };
  } catch {
    logStructured("error", "CATALOG_FALLBACK");
    return fallback();
  }
}

// No TTL: the SHA is read from the database on a cache miss only (release activation, a new deployment, a cold Data Cache).
// The Data Cache holds the SHA (64 bytes); the payload lives in instance memory (cachedReleaseReader).
const readCachedSha = remember(() => readActiveSha(appPool()), ["catalog-active-sha", String(RELEASE_SCHEMA_VERSION), getBuildEnv(buildEnvFromHost(currentEnv())).commit], {
  tags: [CATALOG_TAG], revalidate: CACHE.untilTagged,
});
const readCached = cachedReleaseReader(readCachedSha, (sha) => readReleaseBySha(appPool(), sha));

/**
 * One read per request (React `cache`) over the tagged Data Cache. When the route passes preview, a valid preview
 * cookie compiles the draft catalog uncached (ADR-18). The route reads draft mode, so a prerender stays static (ADR-16).
 */
export const getCatalogState = cache(async (preview = false, cookie?: string): Promise<CatalogState> => {
  if (preview) {
    const draft = await draftCatalogState(cookie);
    if (draft) return draft;
  }
  return resolveCatalog(readCached);
});

/**
 * Public reads stay on the v2 payload (format 2) until a caller opts into format 3.
 * Format 3 rebuilds that same release from its index. A missing or corrupt projection
 * logs a diagnosis and returns the v2 payload of this release, never another release.
 */
export async function getCatalog(format: 2 | 3 = 2, preview = false, cookie?: string): Promise<PublicCatalog> {
  const state = await getCatalogState(preview, cookie);
  if (format === 2 || state.source !== "database") return state.catalog;
  try {
    return await readProjectedRelease(appPool(), state.catalog.number);
  } catch (error) {
    logStructured("error", "CATALOG_PROJECTION_FALLBACK", { release: state.catalog.number, message: error instanceof Error ? error.message : "corrupt" });
    return state.catalog;
  }
}
