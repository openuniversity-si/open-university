import { createHash } from "node:crypto";
import pg from "pg";
import { createAdminRateLimiter } from "../../src/platform/security/rate-limit.ts";
import { compileRelease } from "../../src/catalog/domain/compile.ts";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { releaseSha } from "../../src/kernel/sha.ts";
import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import { readCatalogTables } from "../../src/catalog/server/table-io.ts";
import type { PreconditionFailure } from "../../src/catalog/domain/contracts.ts";
import type { AdminPool, PooledClient } from "../../src/catalog/server/mutation.ts";
import type { authorView } from "../../src/catalog/server/authors.ts";
import type { courseDetail, courseView } from "../../src/catalog/server/courses.ts";
import type { Finding } from "../../src/catalog/server/doctor.ts";
import type { lessonView } from "../../src/catalog/server/lessons.ts";
import type { ReleaseDiff, ReleaseSummary } from "../../src/catalog/server/releases.ts";
import type { AdminCatalogDeps } from "../../src/catalog/server/http.ts";
import { OEMBED_CHECKER, type EmbedStatus } from "../../src/playback/ports/oembed.ts";
import { ADMIN_CATALOG_ROUTES } from "../../src/catalog/server/routes.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import type { MediaObjectStore } from "../../src/media/server/storage.ts";
import { StorageError } from "../../src/media/server/r2.ts";
import { MEDIA_PUBLIC_HOST, type AssetInput, type MediaOwner } from "../../src/media/domain/types.ts";
import { REQUIRED_COVERS } from "../../src/catalog/domain/rules/status.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";
import { resetCatalogTables } from "./catalog-reset.ts";

// Integration harness of the admin catalog API: real PG18 (no database mocks), the real route table, and fakes only for
// the network (oEmbed, R2) and Next (revalidation). Every pool statement and transaction boundary is recorded, so tests can
// prove ordering (revalidate after COMMIT, no network inside a transaction) and that no UPDATE touches a release payload.

export const SECRET = "int-test-admin-secret-0123456789";
export const NOW = new Date("2026-10-11T12:00:00.000Z");

export function testDatabaseUrl(): string {
  const url = process.env.TEST_DATABASE_URL;
  if (!url) throw new Error("TEST_DATABASE_URL is required; no database mocks.");
  validateDatabaseUrl(url, "container");
  return url;
}

export interface Recorder {
  /** `BEGIN#3`, `COMMIT#3`, `ROLLBACK#3`, `oembed:<id>`, `invalidate`, `r2:delete:<key>`, `media:<tag>`. */
  readonly events: string[];
  /** Every SQL statement the API sent, pool and transactions alike. */
  readonly statements: string[];
}

function recordingPool(pool: pg.Pool, recorder: Recorder): AdminPool {
  let next = 0;
  return {
    query(sql, values) {
      recorder.statements.push(sql);
      return pool.query<Record<string, unknown>>(sql, values);
    },
    async connect(): Promise<PooledClient> {
      const client = await pool.connect();
      next += 1;
      const id = next;
      return {
        query(sql, values) {
          recorder.statements.push(sql);
          if (/^(BEGIN|COMMIT|ROLLBACK)$/.test(sql)) recorder.events.push(`${sql}#${String(id)}`);
          return client.query<Record<string, unknown>>(sql, values);
        },
        release: (destroy) => { client.release(destroy); },
      };
    },
  };
}

export interface FakeStore extends MediaObjectStore {
  readonly deleted: string[];
  /** Keys whose delete fails (until removed from the set). */
  readonly failing: Set<string>;
}
export function fakeStore(recorder: Recorder): FakeStore {
  const deleted: string[] = [];
  const failing = new Set<string>();
  const stored = new Map<string, Buffer>();
  return {
    deleted, failing,
    publicUrl: (pathname) => `https://${MEDIA_PUBLIC_HOST}/${pathname}`,
    head: (pathname) => Promise.resolve(stored.has(pathname) ? { size: stored.get(pathname)?.length ?? 0 } : null),
    get: (pathname) => Promise.resolve(stored.get(pathname) ?? null),
    put: (pathname, bytes) => { if (stored.has(pathname)) return Promise.resolve("exists"); stored.set(pathname, Buffer.from(bytes)); return Promise.resolve("created"); },
    delete(pathname) {
      recorder.events.push(`r2:delete:${pathname}`);
      if (failing.has(pathname)) return Promise.reject(new StorageError("R2 DELETE failed with HTTP 503."));
      deleted.push(pathname);
      return Promise.resolve();
    },
  };
}

export interface Harness {
  readonly pool: pg.Pool;
  readonly recorder: Recorder;
  readonly store: FakeStore;
  /** youtubeId → status for the fake oEmbed (default ok, titled `Video <id>`). */
  readonly embeds: Map<string, EmbedStatus>;
  readonly logs: string[];
  readonly deps: AdminCatalogDeps;
  /** Fresh deps over the same pool with overrides (another limiter, no secret, …). */
  depsWith(overrides: Partial<AdminCatalogDeps>): AdminCatalogDeps;
  close(): Promise<void>;
}

export function createHarness(): Harness {
  const pool = new pg.Pool({ connectionString: testDatabaseUrl(), max: 8 });
  const recorder: Recorder = { events: [], statements: [] };
  const store = fakeStore(recorder);
  const embeds = new Map<string, EmbedStatus>();
  const logs: string[] = [];
  let uuid = 0;
  const base: AdminCatalogDeps = {
    secret: SECRET,
    limiter: createAdminRateLimiter({ requests: 1_000_000, failures: 1_000_000 }),
    pool: () => recordingPool(pool, recorder),
    invalidateCatalog: () => { recorder.events.push("invalidate"); },
    invalidateMedia: (plan) => { recorder.events.push(...plan.tags.map((tag) => `media:${tag}`)); },
    oembedChecker: OEMBED_CHECKER,
    oembed: (youtubeId) => {
      recorder.events.push(`oembed:${youtubeId}`);
      const status = embeds.get(youtubeId) ?? "ok";
      return Promise.resolve(status === "ok" ? { status, title: `Video ${youtubeId}` } : { status });
    },
    store: () => store,
    now: () => NOW,
    uuid: () => { uuid += 1; return `00000000-0000-4000-8000-${String(uuid).padStart(12, "0")}`; },
    log: (line) => { logs.push(JSON.stringify(line)); },
  };
  return {
    pool, recorder, store, embeds, logs, deps: base,
    depsWith: (overrides) => ({ ...base, ...overrides }),
    close: () => pool.end(),
  };
}

export interface CallOptions {
  readonly body?: unknown;
  /** Raw body text (overrides `body`). */
  readonly raw?: string;
  readonly key?: string;
  readonly actor?: string;
  readonly requestId?: string;
  /** `null`: no Authorization header; a string: that Bearer token. */
  readonly token?: string | null;
  readonly ip?: string;
  readonly headers?: Record<string, string>;
  readonly deps?: AdminCatalogDeps;
}
export interface CallResult<T> {
  readonly status: number;
  readonly body: { ok: boolean; data?: unknown; error?: { code: string; message: string; details?: unknown }; requestId: string };
  readonly headers: Headers;
  /** `body.data` as the caller expects it (the API's own view types below); a mismatch fails the assertions. */
  readonly data: T;
}

// Response shapes, from the service's own types where it exports them.
export type CourseView = ReturnType<typeof courseView>;
export type CourseDetail = Awaited<ReturnType<typeof courseDetail>>;
export type LessonView = ReturnType<typeof lessonView>;
export type AuthorView = ReturnType<typeof authorView>;
export interface PublicationData { readonly release: ReleaseSummary & { readonly created: boolean }; readonly diff: ReleaseDiff; readonly noop?: true; readonly previous?: number | null }
export interface DoctorData {
  readonly ok: boolean;
  readonly activeRelease: { number: number; sha: string } | null;
  readonly findings: Finding[];
  readonly operational: {
    readonly activeReleaseNumber: number;
    readonly projectionCount: number;
    readonly projectionDriftCount: number;
    readonly pool: { readonly total: number; readonly idle: number; readonly waiting: number };
    readonly lastPublishDurationMs: number | null;
    readonly scope: "process";
  };
}
export interface FailedDetails { readonly failed: PreconditionFailure[] }
export interface DeleteReportData { readonly dryRun: boolean; readonly report: { readonly blockedBy: { rule: string; message: string }[]; readonly r2Candidates: string[]; readonly r2Objects: string[]; readonly keptBytes: string[] } & Record<string, unknown> }
export interface ReleaseData { readonly release: { readonly number: number; readonly sha: string; readonly payload: PublicCatalog; readonly isActive: boolean } }
export interface LessonData { readonly lesson: LessonView; readonly courseRevision: number }
export interface HomeData {
  readonly revision: number;
  readonly featuredCourseId: string | null;
  readonly rows: { id: string; kind: string; title: string | null; authorId: string | null; visible: boolean; position: number; courseIds: string[]; cover?: PublicCatalog["home"]["rows"][number]["cover"] | null }[];
}
export interface AuditData { readonly entries: { action: string; actor: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null; releaseNumber: number | null }[] }
export type Data = Record<string, unknown>;

/** Resolves `METHOD /path?query` against ADMIN_CATALOG_ROUTES (the same table route.ts files export) and runs it. */
export async function call<T = Data>(harness: Harness, method: string, target: string, options: CallOptions = {}): Promise<CallResult<T>> {
  const [pathname = "", search = ""] = target.split("?");
  const route = ADMIN_CATALOG_ROUTES.find((entry) => entry.method === method && new RegExp(`^${entry.path.replace(/:\w+/g, "[^/]+")}$`).test(pathname));
  if (!route) throw new Error(`No admin catalog route for ${method} ${pathname}.`);
  const names = [...route.path.matchAll(/:(\w+)/g)].map((match) => match[1] ?? "");
  const values = new RegExp(`^${route.path.replace(/:\w+/g, "([^/]+)")}$`).exec(pathname)?.slice(1) ?? [];
  const params = Object.fromEntries(names.map((name, index) => [name, decodeURIComponent(values[index] ?? "")]));
  const headers = new Headers({ "x-forwarded-for": options.ip ?? "192.0.2.10", ...options.headers });
  if (options.token !== null) headers.set("authorization", `Bearer ${options.token ?? SECRET}`);
  if (options.key !== undefined) headers.set("idempotency-key", options.key);
  if (options.actor !== undefined) headers.set("x-tower-actor", options.actor);
  if (options.requestId !== undefined) headers.set("x-request-id", options.requestId);
  const body = options.raw ?? (options.body === undefined ? undefined : JSON.stringify(options.body));
  if (body !== undefined) headers.set("content-type", "application/json");
  const request = new Request(`https://tower.test/api/admin/catalog${pathname}${search ? `?${search}` : ""}`, { method, headers, ...(body === undefined ? {} : { body }) });
  const response = await route.run(request, params, options.deps ?? harness.deps);
  const parsed = await response.json() as CallResult<T>["body"];
  return { status: response.status, body: parsed, headers: response.headers, data: (parsed.data ?? {}) as T };
}

// ---- Seed ----

const sha40 = (seed: string) => createHash("sha1").update(seed).digest("hex");
export function coverInput(owner: MediaOwner, ownerId: string, kind: AssetInput["kind"], seed = "1"): AssetInput {
  const pathname = `covers/${ownerId}/${kind}/${sha40(`${ownerId}/${kind}/${seed}`)}.jpg`;
  return {
    ownerId, kind, variant: "default", url: `https://${MEDIA_PUBLIC_HOST}/${pathname}`, pathname, width: 540, height: 960,
    sha256: createHash("sha256").update(pathname).digest("hex"), alt: `${kind} of ${ownerId}`, transform: null, designStatus: "approved" as const,
  };
}

/** Text that fits every slot (level is the tightest, 16 characters). */
export function slotText(field: string, tag: string): string {
  const max = (TEXT_FIELDS.course as Record<string, { maxChars: number }>)[field]?.maxChars ?? 64;
  return `${field.slice(0, 6)} ${tag}`.slice(0, Math.min(max, 16));
}

export interface Seed {
  /** Lecturers (kind person). */
  readonly authors: [string, string];
  /** The institution offering both courses and owning the "picks" University row (D-024). */
  readonly institution: string;
  readonly courses: { readonly alpha: string; readonly beta: string };
  readonly lessons: { readonly alpha: string[]; readonly beta: string[] };
  /** Each course's one edition (Fall 2025). */
  readonly editions: { readonly alpha: string; readonly beta: string };
  readonly license: string;
  readonly source: string;
}

let videoCounter = 0;
/** An 11-character YouTube id never used before in this process. */
export function newVideoId(): string {
  videoCounter += 1;
  return `vid${String(videoCounter).padStart(8, "0")}`;
}

/** The course's newest edition (position 1), created as "Fall 2025" when the course has none (ADR-21). */
export async function defaultEdition(db: pg.ClientBase | pg.Pool, courseId: string): Promise<string> {
  const { rows: [existing] } = await db.query<{ id: string }>("SELECT id FROM course_editions WHERE course_id = $1 AND position = 1", [courseId]);
  if (existing) return existing.id;
  const { rows: [created] } = await db.query<{ id: string }>("INSERT INTO course_editions (course_id, slug, label, term, year, position) VALUES ($1, 'fall-2025', 'Fall 2025', 'fall', 2025, 1) RETURNING id", [courseId]);
  return created?.id ?? "";
}

/** Inserts a lesson with an ok YouTube video and an approved displayTitle at the end of an edition (default: the course's newest). */
export async function seedLesson(db: pg.ClientBase | pg.Pool, courseId: string, options: { approved?: boolean; checkedAt?: Date; youtubeId?: string; editionId?: string; part?: "lectures" | "labs" } = {}): Promise<{ id: string; youtubeId: string }> {
  const editionId = options.editionId ?? await defaultEdition(db, courseId);
  const { rows } = await db.query<{ n: number }>("SELECT count(*)::int AS n FROM lessons WHERE edition_id = $1", [editionId]);
  const { rows: [all] } = await db.query<{ n: number }>("SELECT count(*)::int AS n FROM lessons WHERE course_id = $1", [courseId]);
  const position = (rows[0]?.n ?? 0) + 1;
  const youtubeId = options.youtubeId ?? newVideoId();
  const { rows: [lesson] } = await db.query<{ id: string }>(`INSERT INTO lessons (course_id, edition_id, part, slug, position, youtube_title, duration_seconds) VALUES ($1, $2, $3, $4, $5, $6, 900) RETURNING id`,
    [courseId, editionId, options.part ?? "lectures", `lesson-${String((all?.n ?? 0) + 1)}`, position, `Lecture ${String(position)}`]);
  const id = lesson?.id ?? "";
  await db.query("INSERT INTO lesson_videos (lesson_id, provider, external_id, status, checked_at, checked_by) VALUES ($1, 'youtube', $2, 'ok', $3, 'oembed')", [id, youtubeId, (options.checkedAt ?? NOW).toISOString()]);
  await approvedText(db, "lesson", id, "displayTitle", `Lecture ${String(position)}`, options.approved ?? true);
  return { id, youtubeId };
}

export async function approvedText(db: pg.ClientBase | pg.Pool, kind: string, id: string, field: string, text: string, approve = true): Promise<void> {
  await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence, status, approved_by, approved_at, approved_sha256)
    VALUES ($1, $2, $3, $4, 'manual', 'seed', 'high', $5, $6, $7, CASE WHEN $5 = 'approved' THEN catalog_text_sha256($4) END)
    ON CONFLICT (entity_kind, entity_id, field, locale) DO UPDATE SET text = EXCLUDED.text, status = EXCLUDED.status, approved_by = EXCLUDED.approved_by,
      approved_at = EXCLUDED.approved_at, approved_sha256 = EXCLUDED.approved_sha256`,
  [kind, id, field, text, approve ? "approved" : "draft", approve ? "Seed" : null, approve ? NOW.toISOString() : null]);
}

/** Every course text approved and the four required covers active: what review and publish need besides lessons. */
export async function makeCourseReady(db: pg.Pool, courseId: string, tag: string): Promise<void> {
  await Promise.all(Object.keys(TEXT_FIELDS.course).map((field) => approvedText(db, "course", courseId, field, slotText(field, tag))));
  await Promise.all(REQUIRED_COVERS.map((kind) => swapMedia(db, "course", coverInput("course", courseId, kind))));
}

/**
 * Empties the catalog and seeds two published courses (alpha featured), each ready, in a curated Home row, plus a
 * continue row, and activates release 1 compiled from those tables.
 */
export async function seedCatalog(harness: Harness): Promise<Seed> {
  const url = testDatabaseUrl();
  await runMigrations(url, false);
  await resetCatalogTables(url);
  await harness.pool.query("TRUNCATE lesson_progress");
  harness.recorder.events.length = 0;
  harness.recorder.statements.length = 0;
  harness.logs.length = 0;
  harness.store.deleted.length = 0;
  harness.store.failing.clear();
  harness.embeds.clear();
  const client = await harness.pool.connect();
  try {
    await client.query("INSERT INTO licenses (code, name, url, requires_attribution) VALUES ('youtube-standard', 'Standard YouTube License', 'https://www.youtube.com/t/terms', false)");
    await client.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('src-test', 'institution-site', 'Test courses', 'Test University', 'https://example.org/courses')");
    const authors = (await client.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ('ann-one', 'Ann One', 'AO', 'person'), ('bob-two', 'Bob Two', 'BT', 'person') RETURNING id")).rows.map((row) => row.id);
    const institution = (await client.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ('picks-university', 'Picks University', 'PU', 'institution') RETURNING id")).rows[0]?.id ?? "";
    const course = async (slug: string, featured: boolean) => (await client.query<{ id: string }>(`INSERT INTO courses (slug, author_id, institution_id, title, status, featured, source_id, license_code, canonical_url, rights_status, published_at, area_id, cover_from, shared_with)
      VALUES ($1, $2, $7, $3, 'published', $4, 'src-test', 'youtube-standard', $5, 'accepted-risk', $6, (SELECT a.id FROM subject_areas a WHERE NOT EXISTS (SELECT 1 FROM subject_subareas s WHERE s.area_id = a.id) ORDER BY a.position LIMIT 1), 'own', '{}') RETURNING id`, [slug, authors[0], slug, featured, `https://example.org/${slug}`, NOW.toISOString(), institution])).rows[0]?.id ?? "";
    const alpha = await course("alpha", true);
    const beta = await course("beta", false);
    const lessons = { alpha: [] as string[], beta: [] as string[] };
    for (let index = 0; index < 3; index += 1) lessons.alpha.push((await seedLesson(client, alpha)).id);
    for (let index = 0; index < 2; index += 1) lessons.beta.push((await seedLesson(client, beta)).id);
    await Promise.all([makeCourseReady(harness.pool, alpha, "alpha"), makeCourseReady(harness.pool, beta, "beta")]);
    const picksSha = "a".repeat(64);
    const picksCover = { url: `https://media.openuniversity.si/m/${picksSha}.webp`, width: 1080, height: 1920, sha256: picksSha, alt: "Picks", credit: "Test", sourceUrl: "https://example.org/picks", license: "test", note: null };
    await client.query("INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height) VALUES ($1, 'webp', 'image/webp', 100, 1080, 1920) ON CONFLICT (sha256) DO NOTHING", [picksCover.sha256]);
    for (const [ownerId, kind] of [[institution, "poster_9x16"], ["picks", "university_cover_9x16"]] as const) {
      await swapMedia(harness.pool, "institution", { ownerId, kind, variant: "default", url: picksCover.url, pathname: `m/${picksSha}.webp`, width: 1080, height: 1920, sha256: picksSha, mediaSha256: picksSha, alt: "Picks", transform: null, designStatus: "approved" });
    }
    await client.query("INSERT INTO home_rows (id, kind, institution_id, title, position, cover) VALUES ('continue', 'continue', NULL, NULL, 1, NULL), ('picks', 'curated', $2, 'Picks', 2, $1::jsonb)", [JSON.stringify(picksCover), institution]);
    await client.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('picks', $1, 1), ('picks', $2, 2)", [alpha, beta]);
    const payload = compileRelease(await readCatalogTables(client), { number: 1, publishedAt: NOW.toISOString() });
    await client.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by, is_active, activated_at)
      VALUES (1, $1, $2::jsonb, $3, '{}'::jsonb, 'seed', 'test', true, now())`, [payload.schemaVersion, JSON.stringify(payload), releaseSha(payload)]);
    const editions = { alpha: await defaultEdition(client, alpha), beta: await defaultEdition(client, beta) };
    return { authors: [authors[0] ?? "", authors[1] ?? ""], institution, courses: { alpha, beta }, lessons, editions, license: "youtube-standard", source: "src-test" };
  } finally {
    client.release();
  }
}

/** A draft course of author 1 with `lessons` lessons, ready for review when `ready`. */
export async function seedDraftCourse(harness: Harness, seed: Seed, slug: string, options: { lessons?: number; ready?: boolean } = {}): Promise<{ id: string; edition: string; lessons: string[] }> {
  const client = await harness.pool.connect();
  try {
    const { rows: [row] } = await client.query<{ id: string }>(`INSERT INTO courses (slug, author_id, institution_id, title, source_id, license_code, canonical_url, rights_status, area_id, cover_from, shared_with)
      VALUES ($1, $2, $4, $1, 'src-test', 'youtube-standard', $3, 'cleared', (SELECT a.id FROM subject_areas a WHERE NOT EXISTS (SELECT 1 FROM subject_subareas s WHERE s.area_id = a.id) ORDER BY a.position LIMIT 1), 'own', '{}') RETURNING id`, [slug, seed.authors[0], `https://example.org/${slug}`, seed.institution]);
    const id = row?.id ?? "";
    const lessons: string[] = [];
    for (let index = 0; index < (options.lessons ?? 2); index += 1) lessons.push((await seedLesson(client, id)).id);
    if (options.ready !== false) await makeCourseReady(harness.pool, id, slug.slice(0, 8));
    return { id, edition: await defaultEdition(client, id), lessons };
  } finally {
    client.release();
  }
}

export async function revisionOf(harness: Harness, table: "courses" | "course_editions" | "lessons" | "authors" | "content_sources", id: string): Promise<number> {
  const { rows } = await harness.pool.query<{ revision: number }>(`SELECT revision FROM ${table} WHERE id = $1`, [id]);
  return Number(rows[0]?.revision);
}

export async function activeRelease(harness: Harness): Promise<{ number: number; sha: string }> {
  const { rows } = await harness.pool.query<{ number: number; payload_sha256: string }>("SELECT number, payload_sha256 FROM catalog_releases WHERE is_active");
  return { number: Number(rows[0]?.number), sha: String(rows[0]?.payload_sha256) };
}

export async function auditRows(harness: Harness, filter: { requestId?: string; action?: string; entity?: string } = {}): Promise<{ action: string; entity_kind: string; entity_id: string; before: unknown; after: unknown; actor: string; request_id: string; release_number: number | null }[]> {
  const where: string[] = [];
  const values: unknown[] = [];
  if (filter.requestId !== undefined) { values.push(filter.requestId); where.push(`request_id = $${String(values.length)}`); }
  if (filter.action !== undefined) { values.push(filter.action); where.push(`action = $${String(values.length)}`); }
  if (filter.entity !== undefined) { values.push(filter.entity); where.push(`entity_kind || ':' || entity_id = $${String(values.length)}`); }
  const { rows } = await harness.pool.query(`SELECT action, entity_kind, entity_id, before, after, actor, request_id, release_number FROM catalog_audit ${where.length ? `WHERE ${where.join(" AND ")}` : ""} ORDER BY id`, values);
  return rows as Awaited<ReturnType<typeof auditRows>>;
}

/** Everything a mutation could touch, for "nothing changed" comparisons (dry-runs, rollbacks). */
export async function catalogFingerprint(harness: Harness): Promise<string> {
  const tables = await readCatalogTables(harness.pool);
  const extra = await harness.pool.query<Record<string, unknown>>(`SELECT
    (SELECT json_agg(json_build_object('n', number, 'a', is_active) ORDER BY number) FROM catalog_releases) AS releases,
    (SELECT count(*) FROM catalog_audit) AS audit, (SELECT count(*) FROM admin_idempotency) AS idempotency,
    (SELECT count(*) FROM r2_pending_deletions) AS pending, (SELECT count(*) FROM catalog_imports) AS imports,
    (SELECT json_agg(id ORDER BY id) FROM catalog_media) AS catalog_media,
    (SELECT count(*) FROM lesson_progress) AS progress, (SELECT revision FROM catalog_home) AS home,
    (SELECT json_agg(json_build_object('id', id, 'r', revision) ORDER BY id) FROM (SELECT id, revision FROM courses UNION ALL SELECT id, revision FROM lessons UNION ALL SELECT id, revision FROM authors UNION ALL SELECT id, revision FROM content_sources) r) AS revisions`);
  return JSON.stringify({ tables, extra: extra.rows[0] });
}

/** A synthetic progress row for `lessonId` (and its user), the way the player stores one. */
export async function seedProgress(harness: Harness, lessonId: string, courseId: string): Promise<void> {
  const user = `user-${lessonId}`;
  await harness.pool.query(`INSERT INTO "user" (id, name, email, email_verified, created_at, updated_at) VALUES ($1, 'Test', $2, true, now(), now()) ON CONFLICT DO NOTHING`, [user, `${user}@example.invalid`]);
  await harness.pool.query("INSERT INTO lesson_progress (user_id, lesson_id, course_id, position_seconds, duration_seconds, updated_at) VALUES ($1, $2, $3, 30, 900, now())", [user, lessonId, courseId]);
}

/** Events between a BEGIN#n and its COMMIT#n/ROLLBACK#n that match `test` (network work must never be among them). */
export function insideTransactions(events: readonly string[], test: (event: string) => boolean): string[] {
  const open = new Set<string>();
  const found: string[] = [];
  for (const event of events) {
    const boundary = /^(BEGIN|COMMIT|ROLLBACK)#(\d+)$/.exec(event);
    if (boundary) { if (boundary[1] === "BEGIN") open.add(boundary[2] ?? ""); else open.delete(boundary[2] ?? ""); continue; }
    if (open.size > 0 && test(event)) found.push(event);
  }
  return found;
}
