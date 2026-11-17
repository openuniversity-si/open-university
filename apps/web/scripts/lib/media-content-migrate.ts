import { createHash } from "node:crypto";
import "../../src/media/server/public-hosts.ts";
import { mediaPublicHost } from "../../src/media/domain/types.ts";
import { objectDescriptor, inspectObject, objectKey, type MediaObject } from "../../src/media/server/objects.ts";
import { inTransaction, type MediaDatabase, type MediaPool } from "../../src/media/server/repository.ts";
import { mediaContentType, type MediaObjectStore } from "../../src/media/server/storage.ts";
import { StorageError } from "../../src/media/server/r2.ts";
import { mapLimited } from "./r2-bulk.ts";

export interface ContentReference {
  table: string; id: string; field: "asset" | "cover" | "og" | "release";
  sha256: string; url: string; pathname: string; width: number; height: number;
  previous: string | null;
}
export interface ContentPlan {
  version: 1; references: ContentReference[]; objects: MediaObject[];
  /** Source descriptor snapshot, for a guarded resume/backfill. No credentials. */
  sourceSha256: string;
}
function batches<T, R>(items: readonly T[], work: (item: T) => Promise<R>): Promise<R[]> {
  return mapLimited(items, work);
}
const assetTables = ["catalog_media"] as const;
export async function contentReferences(db: MediaDatabase): Promise<ContentReference[]> {
  const references: ContentReference[] = [];
  for (const table of assetTables) {
    const result = await db.query(`SELECT id, owner_kind, sha256, url, pathname, width, height, media_sha256 FROM ${table} ORDER BY id`);
    references.push(...result.rows.map((row) => ({ table, id: String(row.id), field: "asset" as const, sha256: String(row.sha256), url: String(row.url),
      pathname: String(row.pathname), width: Number(row.width), height: Number(row.height), previous: row.media_sha256 as string | null })));
  }
  const addCover = (table: string, id: string, value: unknown, previous: unknown, ogPrevious: unknown, release = false) => {
    if (!value || typeof value !== "object") return;
    const cover = value as Record<string, unknown>;
    if (typeof cover.url !== "string" || typeof cover.sha256 !== "string") throw new StorageError("Incomplete legacy cover descriptor.");
    references.push({ table, id, field: release ? "release" : "cover", sha256: cover.sha256, url: cover.url, pathname: new URL(cover.url).pathname.slice(1),
      width: Number(cover.width), height: Number(cover.height), previous: (previous ?? null) as string | null });
    if (cover.og) {
      addCover(table, id, cover.og, ogPrevious, null, release);
      const last = references.at(-1);
      if (!release && last) last.field = "og";
    }
  };
  for (const table of ["authors", "home_rows"]) {
    const rows = (await db.query(`SELECT id, cover FROM ${table} WHERE cover IS NOT NULL ORDER BY id`)).rows;
    for (const row of rows) addCover(table, String(row.id), row.cover, null, null);
  }
  // Older releases remain immutable and may still reference earlier author/university covers.
  for (const row of (await db.query(`SELECT number, jsonb_build_object('authors',
      (SELECT coalesce(jsonb_agg(jsonb_build_object('id',v->>'id','cover',v->'cover')), '[]'::jsonb) FROM jsonb_array_elements(payload->'authors') v WHERE v->'cover' IS NOT NULL),
      'home',jsonb_build_object('rows', (SELECT coalesce(jsonb_agg(jsonb_build_object('id',v->>'id','cover',v->'cover')), '[]'::jsonb) FROM jsonb_array_elements(payload->'home'->'rows') v WHERE v->'cover' IS NOT NULL))) AS payload FROM catalog_releases ORDER BY number`)).rows) {
    const payload = row.payload as { authors?: { id: string; cover?: unknown }[]; home?: { rows?: { id: string; cover?: unknown }[] } };
    for (const author of payload.authors ?? []) if (author.cover) addCover("catalog_releases", `${String(row.number)}:author:${author.id}`, author.cover, null, null, true);
    for (const home of payload.home?.rows ?? []) if (home.cover) addCover("catalog_releases", `${String(row.number)}:row:${home.id}`, home.cover, null, null, true);
  }
  return references;
}
export function referenceSnapshot(refs: readonly ContentReference[]): string {
  return createHash("sha256").update(JSON.stringify(refs.map((ref) => ({ ...ref, previous: null })))).digest("hex");
}
const referenceKey = (ref: ContentReference) => `${ref.table}\0${ref.id}\0${ref.field}`;
/** `covers/<owner>/<kind>/<file>` — the kind segment is how a sample proves each required shape. */
function referenceShape(ref: ContentReference): "course-cover" | "lesson-cover" | "hero" | "other" {
  const kind = ref.pathname.split("/")[2] ?? "";
  if (kind === "poster_9x16") return "course-cover";
  if (kind === "cover_16x9" || kind === "cover_9x16") return "lesson-cover";
  if (kind.startsWith("hero_")) return "hero";
  return "other";
}
/**
 * Stable sample for the DB gate. Distinct contents are ordered by sha256. The result always includes
 * the first course poster, lesson cover and hero in that order, then fills from the start of the same
 * order until `limit` contents (or every content, when fewer exist). Every reference of a chosen hash is kept.
 */
export function selectContentSample(references: readonly ContentReference[], limit: number): ContentReference[] {
  if (!Number.isSafeInteger(limit) || limit < 1) throw new StorageError("--sample must be a positive integer.");
  if (limit < 3) throw new StorageError("--sample must be at least 3 so every required kind fits.");
  const byHash = new Map<string, ContentReference[]>();
  for (const ref of references) {
    const group = byHash.get(ref.sha256);
    if (group) group.push(ref);
    else byHash.set(ref.sha256, [ref]);
  }
  const hashes = [...byHash.keys()].sort((a, b) => a.localeCompare(b));
  const hasShape = (hash: string, shape: "course-cover" | "lesson-cover" | "hero") =>
    (byHash.get(hash) ?? []).some((ref) => referenceShape(ref) === shape);
  const picked = new Set<string>();
  for (const shape of ["course-cover", "lesson-cover", "hero"] as const) {
    const hash = hashes.find((candidate) => hasShape(candidate, shape));
    if (!hash) throw new StorageError(`Sample needs one ${shape}.`);
    picked.add(hash);
  }
  for (const hash of hashes) {
    if (picked.size >= limit) break;
    picked.add(hash);
  }
  return references.filter((ref) => picked.has(ref.sha256));
}
/**
 * A sample apply must not point an unsampled row at different bytes. A null pointer (not migrated yet)
 * and a pointer already equal to that row's own content (a clone of a migrated database) are both valid.
 */
export function assertSampleScope(references: readonly ContentReference[], selected: readonly ContentReference[]) {
  const hashes = new Set(selected.map((ref) => ref.sha256));
  if (references.some((ref) => !hashes.has(ref.sha256) && ref.previous != null && ref.previous !== ref.sha256)) {
    throw new StorageError("Sample apply changed a reference outside the sample.");
  }
}
export function contentBatches<T extends { sha256: string }>(objects: readonly T[], batchSize: number): T[][] {
  if (!Number.isSafeInteger(batchSize) || batchSize < 1) throw new StorageError("--batch-size must be a positive integer.");
  const sorted = [...objects].sort((a, b) => a.sha256.localeCompare(b.sha256));
  const batches: T[][] = [];
  for (let index = 0; index < sorted.length; index += batchSize) batches.push(sorted.slice(index, index + batchSize));
  return batches;
}
/** Dry-run verifies registered bytes or legacy metadata. No storage or database writes. */
export async function planContentMigration(db: MediaDatabase, store: MediaObjectStore): Promise<ContentPlan> {
  const inventory = await readInventory(db);
  return planFromReferences(inventory.refs, store, inventory.objects);
}
/** The R2 part of planning; needs no database connection (the CLI closes it before minutes of storage I/O). */
export async function planFromReferences(references: ContentReference[], store: MediaObjectStore, registered: readonly MediaObject[] = []): Promise<ContentPlan> {
  const objects: MediaObject[] = [];
  const distinct = new Map<string, ContentReference>();
  for (const ref of references) {
    const existing = distinct.get(ref.sha256);
    const ext = ref.pathname.split(".").at(-1) ?? "";
    objectKey(ref.sha256, ext);
    if (existing && (existing.width !== ref.width || existing.height !== ref.height || existing.pathname.split(".").at(-1) !== ext)) throw new StorageError(`Conflicting legacy descriptors: ${ref.table}/${ref.id}/${ref.field} sha256=${ref.sha256} pathname=${ref.pathname}`);
    distinct.set(ref.sha256, ref);
  }
  await batches([...distinct.values()], async (ref) => {
    const object = registered.find((object) => object.sha256 === ref.sha256);
    if (object) {
      const key = objectKey(object.sha256, object.ext);
      const bytes = await store.get(key);
      if (!bytes) throw new StorageError(`Missing migrated content: ${ref.table}/${ref.id}/${ref.field} pathname=${key}`);
      const actual = await inspectObject(bytes, object.sha256, object.ext).catch((error: unknown) => {
        if (error instanceof StorageError) throw new StorageError(`${error.message} reference=${ref.table}/${ref.id}/${ref.field} pathname=${key}`);
        throw error;
      });
      if (Object.keys(actual).some((field) => actual[field as keyof MediaObject] !== object[field as keyof MediaObject]) || actual.width !== ref.width || actual.height !== ref.height || actual.ext !== ref.pathname.split(".").at(-1)) throw new StorageError(`Migrated content metadata mismatch: ${ref.table}/${ref.id}/${ref.field} pathname=${key}`);
      objects.push(actual);
      return;
    }
    // Size is the store's authoritative length: S3 HeadObject, or one ranged GET on the public host.
    const head = await store.head(ref.pathname);
    if (!head || head.size <= 0) throw new StorageError(`Missing legacy media source: ${ref.table}/${ref.id}/${ref.field} sha256=${ref.sha256} pathname=${ref.pathname}`);
    objects.push({ sha256: ref.sha256, ext: ref.pathname.split(".").at(-1) as MediaObject["ext"], bytes: head.size, width: ref.width, height: ref.height, contentType: mediaContentType(ref.pathname) });
  });
  return { version: 1, references, objects: objects.sort((a, b) => a.sha256.localeCompare(b.sha256)), sourceSha256: referenceSnapshot(references) };
}
/**
 * Byte length of a public object. A 206 uses the Content-Range total, never the one-byte
 * Content-Length of the slice. A 200 (the server ignored Range) uses Content-Length.
 * The body is cancelled: existence and size do not download the object.
 */
function publicObjectSize(response: Response): number | null {
  const raw = response.status === 206
    ? /^bytes \d+-\d+\/(\d+)$/.exec(response.headers.get("content-range") ?? "")?.[1]
    : response.status === 200 ? response.headers.get("content-length") ?? undefined : undefined;
  if (raw == null || !/^\d+$/.test(raw)) return null;
  const size = Number(raw);
  return Number.isSafeInteger(size) ? size : null;
}
/**
 * Public media needs no bucket credentials. Mutations fail closed; the gate only reuses verified bytes.
 * Existence and size are a `GET` with `Range: bytes=0-0` against the public host. Cloudflare does not
 * cache HEAD on that host, so this store never sends one. A checksum uses `get` (the full body).
 */
export function publicContentStore(request: typeof fetch = fetch): MediaObjectStore {
  const url = (key: string) => {
    if (!key || key.startsWith("/") || key.split("/").some((part) => !part || part === "." || part === "..") || /[?#%]/.test(key)) throw new StorageError("Invalid public media key.");
    return `https://${mediaPublicHost(process.env)}/${key}`;
  };
  return {
    publicUrl: url,
    async head(key) {
      const response = await request(url(key), { headers: { Range: "bytes=0-0" }, redirect: "error", signal: AbortSignal.timeout(30_000) });
      try {
        if (response.status === 404) return null;
        const size = publicObjectSize(response);
        if (response.status !== 206 && response.status !== 200) throw new StorageError(`Public media GET status=${String(response.status)} pathname=${key}`);
        if (size == null) throw new StorageError(`Public media range has no object length pathname=${key}`);
        return { size };
      } finally {
        await response.body?.cancel();
      }
    },
    async get(key) {
      const response = await request(url(key), { redirect: "error", signal: AbortSignal.timeout(30_000) });
      if (response.status === 404) return null;
      if (response.status !== 200) throw new StorageError(`Public media GET status=${String(response.status)} pathname=${key}`);
      return Buffer.from(await response.arrayBuffer());
    },
    put(key) { return Promise.reject(new StorageError(`Read-only public storage cannot create pathname=${key}; run the sanctioned migration with R2 write access first.`)); },
    delete(key) { return Promise.reject(new StorageError(`Read-only public storage cannot delete pathname=${key}`)); },
  };
}
/**
 * Read-only diagnosis through tower-media migrate-content; identities contain no connection details.
 * Presence and size use `store.head`: on the public host that is one ranged GET, on R2 it is HeadObject.
 */
export async function auditContentSources(inventory: Awaited<ReturnType<typeof readInventory>>, store: MediaObjectStore) {
  const paths = [...new Set(inventory.refs.map((ref) => ref.pathname))];
  const missing = (await batches(paths, async (pathname) => {
    const head = await store.head(pathname);
    if (head && head.size > 0) return [];
    const refs = inventory.refs.filter((ref) => ref.pathname === pathname);
    const ref = refs[0] as ContentReference;
    const object = inventory.objects.find((object) => object.sha256 === ref.sha256);
    const contentKey = object ? objectKey(object.sha256, object.ext) : null;
    const contentHead = contentKey ? await store.head(contentKey) : null;
    return [{ pathname, references: refs.map(({ table, id, field, sha256, previous }) => ({ table, id, field, sha256, previous })),
      contentKey, contentPresent: Boolean(contentHead && object && contentHead.size === object.bytes) }];
  })).flat();
  return { references: inventory.refs.length, registryObjects: inventory.objects.length,
    migratedReferences: inventory.refs.filter((ref) => ref.previous === ref.sha256).length,
    legacyPaths: paths.length, missingLegacyPaths: missing.length, missing };
}
/** Resume always verifies destination bytes, including objects copied by an interrupted earlier run. */
export async function copyContent(plan: ContentPlan, store: MediaObjectStore, progress: (counts: { verified: number; copied: number }) => void = () => {}) {
  let copied = 0;
  let verified = 0;
  const sources = new Map(plan.references.map((ref) => [ref.sha256, ref]));
  await batches(plan.objects, async (object) => {
    const key = objectKey(object.sha256, object.ext);
    const source = sources.get(object.sha256);
    if (!source) throw new StorageError("No source for planned object.");
    // Existence is store.head (ranged public GET, or S3 HeadObject). The checksum below is a full GET.
    if (await store.head(key)) {
      // Existing content is verified below; legacy bytes are no longer a prerequisite.
    } else if (store.copy) {
      if (source.pathname !== key && await store.copy(source.pathname, key) === "created") copied++;
    } else {
      const bytes = await store.get(source.pathname);
      if (!bytes) throw new StorageError(`Missing legacy source: ${source.table}/${source.id}/${source.field} pathname=${source.pathname}`);
      await inspectObject(bytes, object.sha256, object.ext);
      if (await store.put(key, bytes) === "created") copied++;
    }
    const bytes = await store.get(key);
    if (!bytes) throw new StorageError(`Missing copied object: ${source.table}/${source.id}/${source.field} pathname=${key}`);
    const actual = await inspectObject(bytes, object.sha256, object.ext);
    if (["bytes", "width", "height", "contentType"].some((field) => actual[field as keyof MediaObject] !== object[field as keyof MediaObject])) throw new StorageError(`Copied object metadata mismatch: ${source.table}/${source.id}/${source.field} pathname=${key}`);
    verified++;
    progress({ verified, copied });
  });
  return { verified, copied };
}
/** All object registrations and catalog_media backfills for `hashes` commit together. */
export async function backfillContent(pool: MediaPool, plan: ContentPlan, hashes: readonly string[] = plan.objects.map((object) => object.sha256)): Promise<number> {
  const selected = new Set(hashes);
  const objects = plan.objects.filter((object) => selected.has(object.sha256));
  return inTransaction(pool, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtextextended('media:content-migration',0))");
    // Prevent an old deployment changing descriptors between validation and backfill.
    await tx.query("LOCK TABLE catalog_media,authors,home_rows,catalog_releases IN SHARE ROW EXCLUSIVE MODE");
    const wanted = new Set(plan.references.map(referenceKey));
    const relevant = (await contentReferences(tx)).filter((ref) => wanted.has(referenceKey(ref)));
    if (relevant.length !== plan.references.length || referenceSnapshot(relevant) !== plan.sourceSha256) throw new StorageError("Source descriptors changed; make a fresh plan.");
    const payload = JSON.stringify(objects);
    await tx.query(`INSERT INTO media_objects (sha256,ext,content_type,bytes,width,height)
      SELECT sha256,ext,"contentType",bytes,width,height FROM jsonb_to_recordset($1::jsonb) AS x(sha256 text,ext text,"contentType" text,bytes bigint,width int,height int)
      ON CONFLICT (sha256) DO NOTHING`, [payload]);
    const conflicts = await tx.query(`SELECT o.sha256 FROM media_objects o JOIN jsonb_to_recordset($1::jsonb) AS x(sha256 text,ext text,"contentType" text,bytes bigint,width int,height int) USING (sha256)
      WHERE (o.ext,o.content_type,o.bytes,o.width,o.height) IS DISTINCT FROM (x.ext,x."contentType",x.bytes,x.width,x.height)`, [payload]);
    if (conflicts.rows.length) throw new StorageError("Registry metadata conflicts with migration.");
    const list = objects.map((object) => object.sha256);
    let updated = 0;
    for (const table of assetTables) {
      const result = await tx.query(`UPDATE ${table} SET media_sha256=sha256 WHERE sha256 = ANY($1::text[]) AND media_sha256 IS DISTINCT FROM sha256 RETURNING id`, [list]);
      updated += result.rows.length;
    }
    return updated;
  });
}
/** Rollback of the catalog_media backfill: clear `media_sha256` in one transaction. The row url stays; `media_objects` rows and `m/` bytes stay. */
export async function rollbackContent(pool: MediaPool, hashes?: readonly string[]): Promise<number> {
  return inTransaction(pool, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtextextended('media:content-migration',0))");
    const scoped = hashes != null;
    const list = hashes ?? [];
    let cleared = 0;
    for (const table of assetTables) {
      const result = scoped
        ? await tx.query(`UPDATE ${table} SET media_sha256=NULL WHERE media_sha256 = ANY($1::text[]) RETURNING id`, [list])
        : await tx.query(`UPDATE ${table} SET media_sha256=NULL WHERE media_sha256 IS NOT NULL RETURNING id`);
      cleared += result.rows.length;
    }
    return cleared;
  });
}
export interface BatchReport { index: number; total: number; copied: number; skipped: number; failed: number }
/**
 * Copies and verifies one sha256-ordered batch, then calls `backfill` for that batch only.
 * A failure logs the batch and stops; later batches are not started. Objects already stored count as skipped.
 */
export async function applyContentBatches(plan: ContentPlan, store: MediaObjectStore, options: {
  batchSize: number; completed?: Iterable<string>;
  backfill: (hashes: readonly string[]) => Promise<number>;
  onBatch: (report: BatchReport) => void;
  persist?: (completed: readonly string[]) => Promise<void>;
}): Promise<{ verified: number; copied: number; skipped: number; updated: number; completed: string[] }> {
  const completed = new Set(options.completed ?? []);
  const batches = contentBatches(plan.objects, options.batchSize);
  let copied = 0;
  let skipped = 0;
  let verified = 0;
  let updated = 0;
  for (const [index, batch] of batches.entries()) {
    const pending = batch.filter((object) => !completed.has(object.sha256));
    const hashes = new Set(pending.map((object) => object.sha256));
    let progress = { verified: 0, copied: 0 };
    try {
      if (pending.length) {
        progress = await copyContent({ ...plan, objects: pending, references: plan.references.filter((ref) => hashes.has(ref.sha256)) }, store, (counts) => { progress = counts; });
      }
      updated += await options.backfill(batch.map((object) => object.sha256));
      for (const object of batch) completed.add(object.sha256);
      const report = { index: index + 1, total: batches.length, copied: progress.copied, skipped: batch.length - progress.copied, failed: 0 };
      copied += report.copied;
      skipped += report.skipped;
      verified += pending.length;
      await options.persist?.([...completed]);
      options.onBatch(report);
    } catch (error) {
      options.onBatch({ index: index + 1, total: batches.length, copied: progress.copied, skipped: Math.max(0, progress.verified - progress.copied), failed: 1 });
      throw error;
    }
  }
  return { verified, copied, skipped, updated, completed: [...completed] };
}
export const contentSummary = (plan: ContentPlan) => ({ references: plan.references.length, distinct: plan.objects.length,
  referencedBytes: plan.objects.reduce((sum, object) => sum + object.bytes, 0), maxClassAWrites: plan.objects.length });

/** Public GET per distinct active image; every row must have a registry object. */
export async function verifyContent(db: MediaDatabase, request: typeof fetch = fetch) {
  return verifyInventory(await readInventory(db), request);
}
export async function readInventory(db: MediaDatabase) {
  return { refs: await contentReferences(db), objects: (await db.query('SELECT sha256,ext,content_type AS "contentType",bytes::float8 AS bytes,width,height FROM media_objects')).rows as MediaObject[] };
}
/** Public HEAD/GET. A timeout or reset has no response, so it is retried; an HTTP answer is not. */
export async function publicFetch(request: typeof fetch, url: string, method: "GET"): Promise<Response> {
  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      return await request(url, { method, redirect: "error", signal: AbortSignal.timeout(30_000) });
    } catch {
      if (attempt === 5) break;
      await new Promise((resolve) => setTimeout(resolve, 50 * attempt));
    }
  }
  throw new StorageError(`Public media ${method} failed before a response.`);
}
/**
 * The HTTP part of verification; needs no database connection.
 *
 * Compare the public GET, which is the object readers receive. On this host Cloudflare
 * does not cache HEAD (`cf-cache-status: DYNAMIC` on every probe) while GET is the
 * edge-cached object (`HIT`, with an age). A HEAD status, content-length or content-type
 * is therefore a different response from the cached bytes, and verify does not read it.
 * The GET's content-type and body length have to match the registry; `inspectObject`
 * then checks SHA-256, format and dimensions.
 */
export async function verifyInventory({ refs, objects }: Awaited<ReturnType<typeof readInventory>>, request: typeof fetch = fetch) {
  const referenced = new Set(refs.map((ref) => ref.sha256));
  const byHash = new Map(objects.filter((object) => referenced.has(object.sha256)).map((object) => [object.sha256, object]));
  const active = refs.filter((ref) => ref.field !== "release");
  for (const ref of active) {
    const pointed = ref.field === "asset" ? ref.previous === ref.sha256 : true;
    if (!pointed || !byHash.has(ref.sha256)) throw new StorageError(`Media reference has no registered object: ${ref.table}/${ref.id}/${ref.field} sha256=${ref.sha256} pathname=${ref.pathname}`);
  }
  let verified = 0;
  await batches([...new Set(refs.map((ref) => ref.sha256))], async (hash) => {
    const object = byHash.get(hash);
    if (!object) throw new StorageError(`Release media missing from registry: sha256=${hash}`);
    const pathname = objectKey(object.sha256, object.ext);
    const response = await publicFetch(request, objectDescriptor(object).url, "GET");
    const type = response.headers.get("content-type")?.split(";")[0] ?? "";
    if (response.status !== 200 || type !== object.contentType) throw new StorageError(`Public media GET mismatch: sha256=${hash} pathname=${pathname} status=${String(response.status)} content-type=${type}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length !== object.bytes) throw new StorageError(`Public media GET mismatch: sha256=${hash} pathname=${pathname} status=200 content-type=${type} bytes=${String(bytes.length)}`);
    await inspectObject(bytes, object.sha256, object.ext);
    verified++;
  });
  return { references: active.length, distinct: byHash.size, verified, percent: 100, referencedBytes: [...byHash.values()].reduce((sum, object) => sum + object.bytes, 0) };
}
