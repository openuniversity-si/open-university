import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import "../../src/media/server/public-hosts.ts";
import { mediaPublicHosts, mediaUrlSchemaFor } from "../../src/media/domain/types.ts";
import { inTransaction, type MediaDatabase, type MediaPool } from "../../src/media/server/repository.ts";
import { MediaToolError } from "./media-cli.ts";
import type { MediaObjectStore } from "./media-storage.ts";

export const MEDIA_TABLES = ["catalog_media"] as const;
export interface MediaRow { readonly table: (typeof MEDIA_TABLES)[number]; readonly id: string; readonly url: string; readonly pathname: string; readonly sha256: string; readonly width: number; readonly height: number }
export interface UrlMapEntry { readonly table: MediaRow["table"]; readonly id: string; readonly oldUrl: string; readonly newUrl: string }
export interface UrlMap { readonly host: string; readonly entries: readonly UrlMapEntry[] }

/** Every version row (active and old): old versions must stay restorable by `media:rollback`. */
export async function listAllMediaRows(db: MediaDatabase): Promise<MediaRow[]> {
  const rows: MediaRow[] = [];
  const result = await db.query(`SELECT id, url, pathname, sha256, width, height FROM catalog_media ORDER BY id`);
  for (const row of result.rows) rows.push({ table: "catalog_media", id: String(row.id), url: String(row.url), pathname: String(row.pathname), sha256: String(row.sha256), width: Number(row.width), height: Number(row.height) });
  return rows;
}

/** Index local files by the sha256 of their bytes (sha-named caches and original sources alike). */
export async function indexLocalFiles(directories: readonly string[]): Promise<Map<string, string>> {
  const index = new Map<string, string>();
  async function walk(directory: string): Promise<void> {
    let entries;
    try { entries = await readdir(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(file);
      else if (entry.isFile() && !entry.name.endsWith(".json") && !entry.name.endsWith(".partial") && (await stat(file)).size <= 64 * 1024 * 1024) {
        // sha-named cache files: trust the name only after hashing.
        const digest = createHash("sha256").update(await readFile(file)).digest("hex");
        if (!index.has(digest)) index.set(digest, file);
      }
    }
  }
  for (const directory of directories) await walk(path.resolve(directory));
  return index;
}

export function rewriteHost(url: string, host: string) {
  const parsed = new URL(url);
  parsed.hostname = host;
  return parsed.href;
}

export interface MigrationPlan { readonly rows: number; readonly objects: readonly { readonly pathname: string; readonly sha256: string; readonly file: string }[]; readonly rewrites: readonly UrlMapEntry[]; readonly missing: readonly string[] }

/** Pure planning: which objects to copy (one per pathname) and which rows change host. No I/O beyond the given index. */
export function planMigration(rows: readonly MediaRow[], local: ReadonlyMap<string, string>, host: string): MigrationPlan {
  const objects = new Map<string, { pathname: string; sha256: string; file: string }>();
  const missing = new Set<string>();
  const rewrites: UrlMapEntry[] = [];
  for (const row of rows) {
    if (new URL(row.url).pathname !== `/${row.pathname}`) throw new MediaToolError(`Row ${row.table}/${row.id}: URL and pathname disagree.`);
    const file = local.get(row.sha256);
    if (!file) missing.add(row.sha256);
    else {
      const previous = objects.get(row.pathname);
      if (previous && previous.sha256 !== row.sha256) throw new MediaToolError(`Pathname ${row.pathname} maps to two different sha256 values.`);
      objects.set(row.pathname, { pathname: row.pathname, sha256: row.sha256, file });
    }
    if (new URL(row.url).hostname !== host) {
      const newUrl = rewriteHost(row.url, host);
      mediaUrlSchemaFor(mediaPublicHosts(process.env)).parse(newUrl);
      rewrites.push({ table: row.table, id: row.id, oldUrl: row.url, newUrl });
    }
  }
  return { rows: rows.length, objects: [...objects.values()].sort((a, b) => a.pathname.localeCompare(b.pathname)), rewrites, missing: [...missing].sort() };
}

/** Host-only plan for rows whose objects are already in the target bucket (no local bytes needed): every row not on `host` moves to it, nothing else changes. */
export function planHostRewrite(rows: readonly MediaRow[], host: string): { readonly rewrites: readonly UrlMapEntry[]; readonly pathnames: readonly string[] } {
  const rewrites: UrlMapEntry[] = [];
  for (const row of rows) {
    if (new URL(row.url).pathname !== `/${row.pathname}`) throw new MediaToolError(`Row ${row.table}/${row.id}: URL and pathname disagree.`);
    if (new URL(row.url).hostname === host) continue;
    const newUrl = rewriteHost(row.url, host);
    mediaUrlSchemaFor(mediaPublicHosts(process.env)).parse(newUrl);
    rewrites.push({ table: row.table, id: row.id, oldUrl: row.url, newUrl });
  }
  return { rewrites, pathnames: [...new Set(rows.map((row) => row.pathname))].sort() };
}

/** Upload each object once; existing keys are verified by size and (single-part) MD5 ETag, never overwritten. */
export async function copyObjects(plan: MigrationPlan, store: MediaObjectStore, rows: readonly MediaRow[]) {
  const counts = { uploaded: 0, present: 0 };
  for (const object of plan.objects) {
    const bytes = await readFile(object.file);
    const row = rows.find((candidate) => candidate.pathname === object.pathname);
    const metadata = await sharp(bytes).metadata();
    if (createHash("sha256").update(bytes).digest("hex") !== object.sha256 || metadata.width !== row?.width || metadata.height !== row.height) throw new MediaToolError(`Local bytes for ${object.pathname} do not match the database.`);
    const md5 = createHash("md5").update(bytes).digest("hex");
    let existing = await store.head(object.pathname);
    if (!existing) {
      const result = await store.put(object.pathname, bytes);
      if (result === "created") counts.uploaded++;
      existing = await store.head(object.pathname);
    } else counts.present++;
    if (existing?.size !== bytes.length || (existing.etag && /^[a-f0-9]{32}$/.test(existing.etag) && existing.etag !== md5)) throw new MediaToolError(`Stored object ${object.pathname} differs from local bytes; refusing to continue.`);
  }
  return counts;
}

/** Host-only URL rewrite in one transaction; every row must still hold the expected URL. */
export async function applyUrlMap(pool: MediaPool, entries: readonly UrlMapEntry[], direction: "forward" | "revert") {
  if (entries.length === 0) return 0;
  await inTransaction(pool, async (db) => {
    for (const entry of entries) {
      const [from, to] = direction === "forward" ? [entry.oldUrl, entry.newUrl] : [entry.newUrl, entry.oldUrl];
      const table = MEDIA_TABLES.find((name) => name === (entry.table as string));
      if (!table) throw new MediaToolError("Unknown media table in URL map.");
      const result = await db.query(`UPDATE ${table} SET url=$1 WHERE id=$2 AND url=$3 RETURNING id`, [to, entry.id, from]);
      if (result.rows.length !== 1) throw new MediaToolError(`Row ${table}/${entry.id} no longer holds the expected URL; nothing was changed.`);
    }
  });
  return entries.length;
}

/** Keep the first-seen old URL per row so re-runs never lose the original Blob URLs. */
export function mergeUrlMaps(previous: UrlMap | null, next: UrlMap): UrlMap {
  if (!previous) return next;
  if (previous.host !== next.host) throw new MediaToolError("An existing URL map targets a different host; revert it first or pass another --map.");
  const byKey = new Map(previous.entries.map((entry) => [`${entry.table}/${entry.id}`, entry]));
  for (const entry of next.entries) if (!byKey.has(`${entry.table}/${entry.id}`)) byKey.set(`${entry.table}/${entry.id}`, entry);
  return { host: next.host, entries: [...byKey.values()] };
}
