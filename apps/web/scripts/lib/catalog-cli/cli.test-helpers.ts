import { createHash } from "node:crypto";
import { syntheticCatalog, syntheticTables } from "../../../src/catalog/testing/synthetic.ts";
import { fileURLToPath } from "node:url";
import { sha256Hex } from "../../../src/kernel/canonical.ts";
import type { CatalogTables } from "../../../src/catalog/domain/tables.ts";
import { fetchTransport, type Transport, type WireRequest } from "./client.ts";
import { main, type MainDeps } from "./main.ts";
import type { CourseDetail } from "./responses.ts";
import { cliRoute, ROUTE_KEYS, type RouteKey } from "./routes.ts";
import type { Credentials } from "./target.ts";

// Test doubles for tower-catalog: a fake admin API behind the real fetchTransport (so the Bearer path is exercised),
// a scripted terminal, and captured stdout/stderr. No network.

export const SENTINEL = "sentinel-SECRET-7f3a9c-never-print";
export const ORIGIN = "https://tower0test.lambda-url.us-east-1.on.aws";
export const ENV = { TOWER_MEDIA_URL_PREVIEW: ORIGIN, TOWER_MEDIA_URL_PROD: "https://openuniversity.si", TOWER_MEDIA_URL_STAGING: "https://tower0staging.lambda-url.us-east-1.on.aws" };
export const NOW = new Date("2026-10-11T12:00:00.000Z");
const appRoot = fileURLToPath(new URL("../../../", import.meta.url));

export interface Recorded { readonly key: string; readonly method: string; readonly path: string; readonly query: Record<string, string>; readonly body: unknown; readonly headers: Record<string, string>; readonly fileBytes?: Uint8Array }
export type Reply = { status?: number; data?: unknown; error?: { code: string; message: string; details?: unknown }; headers?: Record<string, string>; raw?: string } | "network";
export type Handler = (request: Recorded, call: number) => Reply;

/** `METHOD /path` → route key, by the CLI table's own patterns. */
export function routeOf(method: string, pathname: string): RouteKey | null {
  return ROUTE_KEYS.find((key) => { const route = cliRoute(key); return route.method === method && new RegExp(`^${route.path.replace(/:\w+/g, "[^/]+")}$`).test(pathname); }) ?? null;
}

// ---- Fixture data (shapes from the service types) ----
const text = (value: string, approved = false) => ({
  text: value, status: approved ? "approved" : "draft", sha256: sha256Hex(value), approvedSha256: approved ? sha256Hex(value) : null, source: "manual", sourceRef: "test", confidence: "high", approvedBy: approved ? "Seed" : null, approvedAt: approved ? NOW.toISOString() : null,
});
export function courseDetail(overrides: { revision?: number; subtitle?: string; status?: string } = {}): CourseDetail {
  return {
    course: {
      id: "course-6", slug: "freud", authorId: "author-3", title: "Freud", languageLabel: "English", lessonNoun: "Lecture", status: overrides.status ?? "review", featured: false,
      sourceId: "src-test", licenseCode: "youtube-standard", attributionText: null, canonicalUrl: "https://example.org/freud", rightsStatus: "cleared", rightsNotes: "Official channel",
      rightsCheckedBy: "Daniel", rightsCheckedAt: NOW.toISOString(), areaId: null, subareaId: null, coverFrom: "own", publishedAt: null, revision: overrides.revision ?? 7,
    },
    texts: { displayTitle: text("Freud", true), subtitle: text(overrides.subtitle ?? "On dreams"), level: text("Introductory") },
    editions: [{
      id: "edition-6", slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025, position: 1, resolution: null, language: null, variant: null, sourcePlaylistIds: ["PLabc0000001"], revision: 2,
      counts: { lessons: 3, visibleLessons: 2, parts: { lectures: 3, labs: 0 }, durationSeconds: 4506 }, pending: [],
    }],
    lessons: [1, 2, 3].map((position) => ({
      id: `lesson-${String(210 + position)}`, editionId: "edition-6", part: "lectures", slug: `lecture-${String(position)}`, position, kind: "lecture", youtubeTitle: `Lecture ${String(position)} | Freud`, durationSeconds: 1500 + position,
      visible: position !== 3, licenseCode: null, attributionText: null, revision: 2,
      videos: [{ provider: "youtube", externalId: `vid0000000${String(position)}`, status: "ok", checkedAt: NOW.toISOString(), checkedBy: "oembed" }],
      texts: { displayTitle: text(`Lecture ${String(position)}`, position === 1) }, covers: position === 1 ? [{ kind: "cover_16x9", variant: "default", version: 1, url: "https://media.test/c.jpg" }] : [],
    })),
    covers: [{ kind: "poster_9x16", variant: "default", version: 2, url: "https://media.test/p.jpg", width: 540, height: 960, sha256: "a".repeat(64) }],
    rights: { licenseCode: "youtube-standard", license: null, sourceId: "src-test", source: null, canonicalUrl: "https://example.org/freud", attributionText: null, rightsStatus: "cleared", rightsNotes: "Official channel", rightsCheckedBy: "Daniel", rightsCheckedAt: NOW.toISOString() },
    homeRows: ["picks"],
    preconditions: { review: [{ rule: "covers.active", entity: "course:course-6", message: "Cover hero_present is missing." }], published: [{ rule: "covers.active", entity: "course:course-6", message: "Cover hero_present is missing." }, { rule: "texts.approved", entity: "course:course-6", message: "subtitle is not approved." }] },
  };
}

/** courseDetail with two editions: Spring 2026 (new, lesson-214 as a lab) opens first, Fall 2025 keeps lessons 211–213. */
export function twoEditions(): CourseDetail {
  const detail = courseDetail();
  const [fall] = detail.editions;
  const [first] = detail.lessons;
  if (!fall || !first) throw new Error("courseDetail lost its edition or lessons.");
  return {
    ...detail,
    editions: [
      { ...fall, id: "edition-7", slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026, position: 1, sourcePlaylistIds: [], counts: { lessons: 1, visibleLessons: 1, parts: { lectures: 0, labs: 1 }, durationSeconds: 900 } },
      { ...fall, position: 2 },
    ],
    lessons: [{ ...first, id: "lesson-214", editionId: "edition-7", part: "labs", slug: "lab-1", position: 1, durationSeconds: 900 }, ...detail.lessons],
  };
}

const diff = { authors: { added: [], removed: [], changed: [] }, courses: { added: ["course-6"], removed: [], changed: [] }, lessons: { added: ["lesson-211"], removed: [], changed: [] }, texts: { changed: [] }, home: { changed: true }, redirects: { added: [], removed: [] }, empty: false };
const releases = [
  { number: 3, sha: "c".repeat(64), counts: {}, note: "Publish", createdBy: "cli:tower-catalog@box", createdAt: NOW.toISOString(), isActive: true, activatedAt: NOW.toISOString() },
  { number: 2, sha: "b".repeat(64), counts: {}, note: "Before", createdBy: "cli:tower-catalog@box", createdAt: NOW.toISOString(), isActive: false, activatedAt: NOW.toISOString() },
];
/** Routes that activate a release when they succeed (the fake moves `active` like the API does). */
const ACTIVATING = new Set<RouteKey>(["POST /courses/:id/publish", "POST /courses/publish-batch", "POST /courses/:id/unpublish", "PUT /home", "POST /releases/:n/activate"]);
const payload = syntheticCatalog;
export const snapshotTables = syntheticTables();

/**
 * snapshotTables (the 5 legacy courses) plus one imported course, course-30 `cmu-db` (3 lessons with raw YouTube titles,
 * lesson-301 already on the rule): what `lesson reslug` reads.
 */
export function importedTables(): CatalogTables {
  const lesson = (n: number, slug: string, title: string) => ({
    id: `lesson-${String(300 + n)}`, course_id: "course-30", edition_id: "edition-30", part: "lectures", slug, position: n, kind: "lecture", youtube_title: title,
    duration_seconds: 3000, visible: true, license_code: null, attribution_text: null,
  });
  const lessons = [
    lesson(0, "01-relational-model-algebra-cmu-intro-to-database-systems", "F2024 #01 - Relational Model & Algebra (CMU Intro to Database Systems)"),
    lesson(1, "lecture-02-modern-sql", "F2024 #02 - Modern SQL (CMU Intro to Database Systems)"),
    lesson(2, "fall-2024-storage", "F2024 #03 - Database Storage: Files & Pages (CMU Intro to Database Systems)"),
  ].map((row) => ({ ...row, position: row.position + 1 }));
  const approved = (id: string, value: string) => ({ ...snapshotTables.catalog_texts[0], entity_kind: "lesson", entity_id: id, field: "displayTitle", text: value } as CatalogTables["catalog_texts"][number]);
  return {
    ...snapshotTables,
    authors: [...snapshotTables.authors, { id: "author-30", slug: "andy-pavlo", name: "Andy Pavlo", monogram: "AP", role: "Lecturer", kind: "person", cover: null }],
    courses: [...snapshotTables.courses, { ...snapshotTables.courses[0], id: "course-30", slug: "cmu-db", author_id: "author-30", title: "Intro to Database Systems (CMU 15-445)", legacy: null } as CatalogTables["courses"][number]],
    course_editions: [...snapshotTables.course_editions, { id: "edition-30", course_id: "course-30", slug: "fall-2024", label: "Fall 2024", term: "fall", year: 2024, position: 1, resolution: null, source_playlist_ids: ["PLcmu"], variant_kind: null, variant_label: null }],
    lessons: [...snapshotTables.lessons, ...lessons],
    catalog_texts: [...snapshotTables.catalog_texts, ...lessons.map((row) => approved(row.id, row.youtube_title))],
  };
}

/** A plausible answer for every route (tests override what they examine). */
export interface FakeState { active: number }
export const defaults: Record<RouteKey, (request: Recorded, state: FakeState) => unknown> = {
  "GET /courses": () => ({ courses: [{ id: "course-6", slug: "freud", title: "Freud", authorId: "author-3", status: "review", featured: false, revision: 7, publishedAt: null, counts: { editions: 1, lessons: 3, visibleLessons: 2, texts: 5, draftTexts: 3 }, pending: { target: "published", failed: [] } }] }),
  "POST /courses": (request) => ({ course: { ...courseDetail().course, ...(request.body as object), id: "course-9", status: "draft", revision: 1 } }),
  "GET /courses/:id": () => courseDetail(),
  "PATCH /courses/:id": () => ({ course: { ...courseDetail().course, revision: 8 } }),
  "DELETE /courses/:id": (request) => (request.query.confirm === "true" ? { dryRun: false, purged: true, report: {}, bytes: { deleted: [], pending: [] } } : { dryRun: true, report: { lessons: ["lesson-211"], blockedBy: [] } }),
  "POST /courses/:id/status": (request) => ({ course: { ...courseDetail().course, status: (request.body as { to: string }).to, revision: 8 } }),
  "POST /courses/:id/publish": () => ({ release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "POST /courses/publish-batch": (request) => ({ release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff, previous: 3, courses: ((request.body as { courses: { id: string }[] }).courses).map((course) => ({ id: course.id, from: "review" })) }),
  "POST /courses/:id/unpublish": () => ({ release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "GET /courses/:id/editions": () => ({ courseId: "course-6", editions: courseDetail().editions.map((edition) => ({ ...edition, courseId: "course-6" })) }),
  "POST /courses/:id/editions": (request) => ({ edition: { ...(request.body as object), id: "edition-9", courseId: "course-6", term: null, position: 2, resolution: null, sourcePlaylistIds: [], revision: 1 }, order: ["edition-6", "edition-9"], courseRevision: 8 }),
  "PUT /courses/:id/editions/order": (request) => ({ editionIds: (request.body as { editionIds: string[] }).editionIds, revision: 8 }),
  "PATCH /editions/:id": () => ({ edition: { ...courseDetail().editions[0], courseId: "course-6", revision: 3 }, courseRevision: 8 }),
  "DELETE /editions/:id": (request) => (request.query.confirm === "true" ? { dryRun: false, deleted: true, report: {} } : { dryRun: true, report: { lessons: [], blockedBy: [] } }),
  "PUT /editions/:id/lessons/order": (request) => ({ editionId: request.path.split("/")[2], lessonIds: (request.body as { lessonIds: string[] }).lessonIds, revision: 8 }),
  "POST /courses/:id/lessons": () => ({ lesson: { id: "lesson-214", courseId: "course-6", editionId: "edition-6", part: "lectures", slug: "lecture-4", position: 4, kind: "lecture", youtubeTitle: "Lecture 4", durationSeconds: 900, visible: true, licenseCode: null, attributionText: null, revision: 1 }, youtubeId: "vid00000004", courseRevision: 8 }),
  "PUT /courses/:id/lessons/order": (request) => ({ lessonIds: (request.body as { lessonIds: string[] }).lessonIds, revision: 8 }),
  "PUT /lessons/slugs": (request) => {
    const body = request.body as { courseId: string; changes: { lessonId: string; slug: string }[]; dryRun?: boolean };
    const plan = { changes: body.changes.map((change) => ({ lessonId: change.lessonId, before: "old", after: change.slug })), created: body.changes.map((change) => ({ from: `/c/x/old-${change.lessonId}`, to: `/c/x/${change.slug}` })), flattened: [], removed: [], reused: [] };
    return body.dryRun ? { dryRun: true, courseId: body.courseId, plan, noop: false } : { courseId: body.courseId, courseRevision: 8, plan, lessons: body.changes.map((change) => ({ id: change.lessonId, slug: change.slug, revision: 3 })) };
  },
  "PATCH /lessons/:id": () => ({ lesson: { id: "lesson-211", revision: 3 }, courseRevision: 8 }),
  "DELETE /lessons/:id": (request) => (request.query.confirm === "true" ? { dryRun: false, deleted: true, report: {} } : { dryRun: true, report: { texts: 1 } }),
  "GET /authors": () => ({ authors: [{ id: "author-3", slug: "freud", name: "Sigmund Freud", monogram: "SF", role: "Author", kind: "person", revision: 4, courses: 1, homeRows: 0 }] }),
  "POST /authors": (request) => ({ author: { id: "author-9", ...(request.body as object), role: "Author", kind: "person", revision: 1 } }),
  "PATCH /authors/:id": () => ({ author: { id: "author-3", slug: "freud", name: "S. Freud", monogram: "SF", role: "Author", kind: "person", revision: 5 } }),
  "DELETE /authors/:id": (request) => (request.query.confirm === "true" ? { dryRun: false, deleted: true } : { dryRun: true, report: { dependents: [], texts: 0, blockedBy: [] } }),
  "GET /texts": (request) => ({ entity: request.query.entity, fields: [{ field: "displayTitle", maxChars: 40, requiredForReview: true, requiredForPublish: true, text: "Genesis", status: "approved", sha256: sha256Hex("Genesis"), approvedSha256: sha256Hex("Genesis"), issues: [] }, { field: "about", maxChars: 170, requiredForReview: true, requiredForPublish: false, text: null, status: null, issues: [] }] }),
  "PUT /texts": (request) => ({ items: (request.body as { entityKind: string; entityId: string; field: string; text: string }[]).map((item) => ({ entity: `${item.entityKind}:${item.entityId}`, field: item.field, sha256: sha256Hex(item.text), status: "draft", changed: true })) }),
  "POST /texts/approve": (request) => ({ items: (request.body as { items: unknown[] }).items, approvedBy: (request.body as { approvedBy: string }).approvedBy }),
  "POST /texts/revoke": (request) => ({ items: (request.body as { items: unknown[] }).items }),
  "GET /home": () => ({ revision: 5, featuredCourseId: "course-1", rows: [{ id: "continue", kind: "continue", title: null, authorId: null, visible: true, position: 1, courseIds: [] }, { id: "picks", kind: "curated", title: "Picks", authorId: null, visible: true, position: 2, courseIds: ["course-1"] }] }),
  "PUT /home": (request) => ({ home: { ...(request.body as object), revision: 6 }, release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "GET /areas": () => ({ areas: [{ id: "psychology", title: "Psychology", position: 13, uses: 1, published: 1 }] }),
  "POST /areas": (request) => ({ area: { position: 31, ...(request.body as object) } }),
  "PATCH /areas/:id": (request) => ({ area: { id: request.path.split("/")[2], title: (request.body as { title: string }).title, position: 13 }, release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "POST /areas/:id/move": (request) => ({ area: { id: request.path.split("/")[2], title: "Psychology", position: (request.body as { position: number }).position }, areas: [], release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "GET /subareas": () => ({ subareas: [{ id: "mechanical-engineering", areaId: "engineering", title: "Mechanical Engineering", position: 1, uses: 1, published: 1 }] }),
  "POST /subareas": (request) => ({ subarea: { position: 17, ...(request.body as object) } }),
  "POST /courses/classify": (request) => ({ changed: ((request.body as { items: { id: string; areaId?: string; subareaId?: string | null }[] }).items).map((item) => ({ id: item.id, before: { areaId: null, subareaId: null }, after: { areaId: item.areaId ?? null, subareaId: item.subareaId ?? null } })), unchanged: 0 }),
  "POST /media/references": (request) => ({ used: ((request.body as { keys: string[] }).keys).filter((key) => key.includes("shared")) }),
  "GET /licenses": () => ({ licenses: [{ code: "youtube-standard", name: "Standard YouTube License", url: null, requiresAttribution: false, nonCommercial: false, embedOnly: true, uses: 5 }] }),
  "POST /licenses": (request) => ({ license: { ...(request.body as object), uses: 0 } }),
  "GET /sources": () => ({ sources: [{ id: "src-test", kind: "institution-site", title: "Test", publisher: "Test U", url: "https://example.org", revision: 2, uses: 1 }] }),
  "POST /sources": (request) => ({ source: { ...(request.body as object), revision: 1, uses: 0 } }),
  "PATCH /sources/:id": () => ({ source: { id: "src-test", kind: "institution-site", title: "Renamed", publisher: "Test U", url: "https://example.org", revision: 3, uses: 1 } }),
  "POST /imports": () => ({ import: { id: "import-PLabc-202610111200", playlistId: "PLabc", status: "received", report: { playlist: { id: "PLabc", title: "Freud lectures", channelId: null, channel: null }, accepted: [{ id: "vid00000001", position: 1, title: "Lecture 1", suggestedTitle: "Lecture 1", suggestedSlug: "lecture-1", suggestedKind: "lecture", durationSeconds: 1500 }], excluded: [{ id: "vid00000002", reason: "private" }, { id: "vid00000003", reason: "in-course", courseId: "course-2" }], warnings: [{ id: "vid00000001", reason: "short" }] } } }),
  "POST /imports/:id/draft": () => ({ import: { id: "import-PLabc-202610111200", status: "drafted", courseId: "course-9", editionId: "edition-9" }, course: { ...courseDetail().course, id: "course-9", slug: "freud-2" },
    edition: { id: "edition-9", courseId: "course-9", slug: "2026", label: "2026", term: null, year: 2026, position: 1, resolution: null, sourcePlaylistIds: ["PLabc"], revision: 1 }, lessons: [{ id: "lesson-300", position: 1 }] }),
  "GET /releases": (_request, state) => ({ releases: [4, 3, 2].filter((number) => number <= Math.max(3, state.active)).map((number) => ({ ...releases[1], number, sha: String(number).repeat(64).slice(0, 64), isActive: number === state.active })) }),
  "GET /releases/:n": (request) => ({ release: { number: Number(request.path.split("/").pop()), sha: "c".repeat(64), payload, isActive: true, note: "x", createdBy: "x", createdAt: NOW.toISOString(), activatedAt: NOW.toISOString() } }),
  "POST /releases": (request) => (request.query.dryRun === "true" ? { valid: true, errors: [], unchanged: false, diff, counts: {} } : { release: { number: 4, sha: "d".repeat(64), counts: {}, created: true }, diff }),
  "POST /releases/:n/activate": (request) => ({ release: { number: Number(request.path.split("/")[2]), sha: "b".repeat(64) }, previous: 3 }),
  "GET /redirects": () => ({ redirects: [{ from: "/c/old", to: "/c/freud", live: true }] }),
  "POST /redirects": (request) => ({ redirect: request.body }),
  "DELETE /redirects": (request) => ({ dryRun: request.query.confirm !== "true", redirect: { from: request.query.from, to: "/c/freud" }, ...(request.query.confirm === "true" ? { deleted: true } : {}) }),
  "POST /preview-token": () => ({ url: "/api/catalog/preview?token=v1.preview-token-abc&to=%2Fc%2Ffreud", to: "/c/freud", courseId: "course-6", expiresAt: NOW.toISOString() }),
  "GET /audit": (request) => ({ entity: request.query.entity, entries: [{ id: 1, at: NOW.toISOString(), actor: "cli:tower-catalog@box", requestId: "r-1", action: "course.update", before: { title: "A" }, after: { title: "B" }, releaseNumber: null }] }),
  "GET /tables": () => ({ activeRelease: { number: 1, sha: "c".repeat(64) }, tables: snapshotTables }),
  "GET /doctor": () => ({ ok: true, activeRelease: { number: 3, sha: "c".repeat(64) }, findings: [{ code: "redirects.dormant", severity: "info", count: 1, sample: ["/c/old"], message: "Dormant redirect." }] }),
  "POST /batches/apply": () => ({ status: "committed", batchHash: "b".repeat(64), draft: false, plan: { course: { create: 1 } }, courses: ["usp-mecanica"], release: { number: 2, created: true } }),
  "POST /bundles/validate": () => ({ hash: "ab".repeat(32), version: 1 }),
  "POST /bundles/diff": () => ({ empty: true, course: { changed: [] }, lessons: { added: [], omitted: [], changed: [] }, texts: { changed: [] }, home: { changed: false } }),
  "POST /bundles/apply": (request) => ({ courseId: (request.body as { bundle?: { course?: { id?: string } } } | undefined)?.bundle?.course?.id ?? "course-live", hash: "ab".repeat(32), applied: true }),
  "POST /bundles/ship": () => ({ status: "committed", batchHash: "ab".repeat(32), draft: true, courses: ["course-live"], release: null, phases: { validateMs: 1, writeMs: 1, releaseMs: 0, totalMs: 2 } }),
  "POST /bundles/export": (request) => ({ bundle: (request.body as { bundle?: unknown } | undefined)?.bundle ?? {} }),
  "POST /jobs/claim": () => ({ status: "acquired", jobId: "job-1", token: 1, stage: "VALIDATED", expiresAt: NOW.toISOString() }),
  "POST /jobs/:id/renew": (request) => ({ jobId: "job-1", token: (request.body as { token?: number } | undefined)?.token ?? 1, expiresAt: NOW.toISOString(), leaseMs: 60_000 }),
  "POST /jobs/:id/advance": (request) => ({ jobId: "job-1", stage: (request.body as { checkpoint?: { stage?: string } } | undefined)?.checkpoint?.stage ?? "VALIDATED" }),
  "POST /jobs/:id/complete": (request) => ({ jobId: "job-1", stage: (request.body as { stage?: string } | undefined)?.stage ?? "VERIFIED" }),
  "POST /lifecycle/inventory": () => ({ environment: "preview", complete: true, references: [] }),
  "POST /lifecycle/gc": () => ({ keys: [], cursor: null, complete: true }),
  "POST /lifecycle/preview-reset": () => ({ dryRun: true, snapshotId: null, verified: false }),
};

export interface FakeApi {
  readonly transport: Transport;
  readonly state: FakeState;
  readonly requests: Recorded[];
  /** Admin requests only, as `METHOD /path?query`. */
  readonly calls: () => string[];
  /** Mutating admin requests actually sent (not server dry-runs). */
  readonly mutations: () => string[];
}

/** The admin API on fetch: every request is recorded with its headers; `handlers` override the defaults per route. */
function mediaReply(method: string, pathname: string, body: unknown): unknown {
  const json = body as { sha256?: string | string[]; ownerId?: string; kind?: string; variant?: string; apply?: boolean } | undefined;
  const hash = Array.isArray(json?.sha256) ? json.sha256[0] ?? "a".repeat(64) : typeof json?.sha256 === "string" ? json.sha256 : "a".repeat(64);
  const url = `https://media.test/m/${hash}.webp`;
  if (method === "GET") return { versions: [{ version: 2, active: true, ownerId: "course-6", kind: "hero_desktop_16x9", variant: "default", width: 32, height: 18, url, sha256: hash }], assets: [{ version: 1, ownerId: "course-6", kind: "poster_9x16", variant: "default", width: 8, height: 8, url, sha256: hash }] };
  if (pathname === "/check") return { missing: Array.isArray(json?.sha256) ? json.sha256 : [], objects: [] };
  if (pathname === "/objects" || pathname === "/attach" || pathname === "/rollback") return { sha256: hash, width: 8, height: 8, version: 1, ownerId: json?.ownerId, kind: json?.kind, variant: json?.variant ?? "default" };
  if (method === "DELETE") return json?.apply ? { deleted: [{ version: 1, variant: "default" }], bytes: { deleted: [], kept: [] }, activeAfter: null } : { plan: [{ version: 1, key: "m/example.webp", active: false, willDeleteBytes: false }], activeAfter: { version: 2 } };
  return { apply: json?.apply === true, count: 0, bytesDeleted: 0 };
}

export function fakeApi(handlers: Partial<Record<string, Handler>> = {}, credentials: Credentials = { secrets: { prod: SENTINEL, preview: SENTINEL } }, target: "preview" | "prod" | "staging" = "preview"): FakeApi {
  const requests: Recorded[] = [];
  const counts = new Map<string, number>();
  const state: FakeState = { active: 3 };
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : input);
    const headers = Object.fromEntries(new Headers(init?.headers).entries());
    const form = init?.body instanceof FormData ? init.body : undefined;
    const file = form?.get("file");
    const fileBytes = file instanceof Blob ? new Uint8Array(await file.arrayBuffer()) : undefined;
    const body = form ? Object.fromEntries([...form.entries()].map(([name, value]) => [name, typeof value === "string" ? value : value.name])) : typeof init?.body === "string" ? JSON.parse(init.body) as unknown : undefined;
    if (url.pathname.startsWith("/api/admin/media")) {
      const pathname = url.pathname.slice("/api/admin/media".length) || "/";
      const method = init?.method ?? "GET";
      const key = `media:${method} ${pathname}`;
      const recorded: Recorded = { key, method, path: `${url.pathname}${url.search}`, query: Object.fromEntries(url.searchParams), body, headers, ...(fileBytes ? { fileBytes } : {}) };
      requests.push(recorded);
      const handler = handlers[key];
      const reply: Reply = handler ? handler(recorded, (counts.get(key) ?? 0) + 1) : { data: mediaReply(method, pathname, body) };
      counts.set(key, (counts.get(key) ?? 0) + 1);
      if (reply === "network") return Promise.reject(new TypeError(`fetch failed: Bearer ${headers.authorization ?? ""}`));
      const requestId = headers["x-request-id"] ?? "no-id";
      const status = reply.status ?? (reply.error ? 400 : 200);
      const text = reply.raw ?? JSON.stringify(reply.error ? { ok: false, error: reply.error, requestId } : { ok: true, data: reply.data, requestId });
      return Promise.resolve(new Response(text, { status, headers: { "content-type": "application/json", "x-request-id": requestId, ...reply.headers } }));
    }
    const admin = url.pathname.startsWith("/api/admin/catalog");
    const pathname = admin ? url.pathname.slice("/api/admin/catalog".length) : url.pathname;
    const key = admin ? routeOf(init?.method ?? "GET", pathname) : "public";
    if (key === null) return Promise.reject(new Error(`No route for ${init?.method ?? "GET"} ${pathname}`));
    const recorded: Recorded = { key, method: init?.method ?? "GET", path: `${pathname}${url.search}`, query: Object.fromEntries(url.searchParams), body, headers };
    requests.push(recorded);
    const call = (counts.get(key) ?? 0) + 1;
    counts.set(key, call);
    const handler = handlers[key];
    const reply: Reply = handler ? handler(recorded, call) : key === "public"
      ? { raw: pathname === "/api/health" ? JSON.stringify({ status: "ok", catalog: { release: state.active, sha: "x".repeat(64), source: "database" }, courses: url.searchParams.getAll("course").map((slug) => ({ slug, present: true })) }) : "<html></html>" }
      : { data: defaults[key](recorded, state) };
    const ok = reply !== "network" && (reply.status ?? (reply.error ? 400 : 200)) < 300;
    if (ok && key !== "public" && (ACTIVATING.has(key) || (key === "POST /releases" && recorded.query.dryRun !== "true"))) {
      state.active = key === "POST /releases/:n/activate" ? Number(pathname.split("/")[2]) : 4;
    }
    if (reply === "network") return Promise.reject(new TypeError(`fetch failed: Bearer ${headers.authorization ?? ""}`));
    const requestId = headers["x-request-id"] ?? "no-id";
    const status = reply.status ?? (reply.error ? 400 : 200);
    const text = reply.raw ?? JSON.stringify(reply.error ? { ok: false, error: reply.error, requestId } : { ok: true, data: reply.data, requestId });
    return Promise.resolve(new Response(text, { status, headers: { "content-type": "application/json", "x-request-id": requestId, ...reply.headers } }));
  }) as typeof fetch;
  const adminCalls = () => requests.filter((request) => request.key !== "public");
  return {
    transport: fetchTransport(credentials, target, fetchImpl),
    state,
    requests,
    calls: () => adminCalls().map((request) => `${request.method} ${request.path}`),
    mutations: () => adminCalls().filter((request) => request.key !== "public" && !request.key.startsWith("media:") && cliRoute(request.key as RouteKey).mutates && !(request.method === "DELETE" && request.query.confirm !== "true") && request.query.dryRun !== "true").map((request) => `${request.method} ${request.path}`),
  };
}

export interface RunResult { readonly code: number; readonly stdout: string; readonly stderr: string; readonly prompts: string[] }

/** Runs one tower-catalog command line in process. `answers` = a terminal answering in order; omitted = no TTY. */
export async function runCli(argv: readonly string[], options: { api?: FakeApi; answers?: string[]; env?: Record<string, string>; deps?: Partial<MainDeps> } = {}): Promise<RunResult> {
  const api = options.api ?? fakeApi();
  let stdout = "";
  let stderr = "";
  const prompts: string[] = [];
  const answers = options.answers ? [...options.answers] : null;
  let uuid = 0;
  const code = await main(argv, {
    io: {
      stdout: (chunk) => { stdout += chunk; },
      stderr: (chunk) => { stderr += chunk; },
      prompt: answers === null ? null : (question) => { prompts.push(question); return Promise.resolve(answers.shift() ?? ""); },
    },
    env: { ...ENV, ...options.env },
    hostname: "Test-Box.local",
    uuid: () => { uuid += 1; return `00000000-0000-4000-8000-${String(uuid).padStart(12, "0")}`; },
    now: () => NOW,
    sleep: () => Promise.resolve(),
    oembed: (id) => Promise.resolve({ status: id.endsWith("2") ? "unavailable" : "ok" }),
    run: () => Promise.resolve({ code: 0, stdout: "", stderr: "" }),
    appRoot,
    home: "/tmp/tower-home",
    transport: () => api.transport,
    secrets: () => [SENTINEL],
    ...options.deps,
  });
  return { code, stdout, stderr, prompts };
}

export const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");
export type { WireRequest };
