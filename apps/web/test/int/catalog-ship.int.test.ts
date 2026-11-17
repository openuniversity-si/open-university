import sharp from "sharp";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { mediaHandlers } from "../../src/admin/deps.ts";
import { adminAuthorization, dispatchAdminRequest } from "../../src/admin/http-dispatcher.ts";
import { ADMIN_CATALOG_ROUTES } from "../../src/catalog/server/routes.ts";
import { catalogCourseOf, catalogOwners } from "../../src/catalog/server/media-owners.ts";
import type { MediaKind } from "../../src/media/domain/types.ts";
import { fetchTransport } from "../../scripts/lib/catalog-cli/client.ts";
import { main } from "../../scripts/lib/catalog-cli/main.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { createHarness, SECRET, testDatabaseUrl, type Harness } from "../fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";

const ORIGIN = "https://tower0int.lambda-url.us-east-1.on.aws";
const BASE = "/api/admin/catalog";
const FIELDS = ["displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile", "description", "descriptionMobile", "about", "level", "format"] as const;
const COVERS: { kind: MediaKind; file: string; width: number; height: number }[] = [
  { kind: "poster_9x16", file: "poster.jpg", width: 32, height: 48 },
  { kind: "hero_desktop_16x9", file: "hero-desktop.jpg", width: 64, height: 36 },
  { kind: "hero_present", file: "hero-present.jpg", width: 64, height: 40 },
  { kind: "hero_mobile_9x16", file: "hero-mobile.jpg", width: 36, height: 64 },
];

function video(index: number): string {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  return `zyxwvutsr${alphabet[Math.floor(index / 36)] ?? "a"}${alphabet[index % 36] ?? "a"}`;
}

async function writeCourse(dir: string, id: string, color: string, videoIndex: number): Promise<void> {
  const covers = join(dir, id);
  mkdirSync(covers, { recursive: true });
  const listed = [];
  for (const [offset, cover] of COVERS.entries()) {
    writeFileSync(join(covers, cover.file), await sharp({ create: { width: cover.width, height: cover.height, channels: 3, background: color } }).modulate({ brightness: 1 + offset / 20 }).jpeg().toBuffer());
    listed.push({ kind: cover.kind, path: `${id}/${cover.file}` });
  }
  const lessonId = `${id}-lesson`;
  const texts = [
    ...FIELDS.map((field) => ({ entityKind: "course", entityId: id, field, text: field === "level" ? "Introductory" : field.slice(0, 12), approved: true, approvedBy: "Daniel", approvedAt: "2026-10-11T12:00:00.000Z" })),
    { entityKind: "lesson", entityId: lessonId, field: "displayTitle", text: "Lecture 1", approved: true, approvedBy: "Daniel", approvedAt: "2026-10-11T12:00:00.000Z" },
  ];
  writeFileSync(join(dir, `${id}.json`), JSON.stringify({
    version: 1,
    author: { id: "inst-ship", slug: "inst-ship", name: "Ship University", monogram: "SU", kind: "institution" },
    course: {
      id, slug: id, title: "Contracts", authorId: "inst-ship", languageLabel: "English",
      areaId: "computer-science", subareaId: "programming", licenseCode: "cc-by", sourceId: "src-ship",
      attributionText: "Open University", canonicalUrl: `https://example.org/${id}`, rightsStatus: "cleared", coverFrom: "own", sharedWith: [],
    },
    editions: [{ id: `${id}-edition`, slug: "original", label: "Original", position: 1, year: 2020, language: "English" }],
    lessons: [{ id: lessonId, editionId: `${id}-edition`, slug: "lecture-1", title: "Lecture 1", position: 1, youtubeId: video(videoIndex), durationSeconds: 60 }],
    texts, covers: listed,
  }));
}

describe("tower-catalog ship against Postgres", () => {
  let h: Harness;
  beforeAll(async () => {
    const url = testDatabaseUrl();
    await runMigrations(url, false);
    await resetCatalogTables(url);
    h = createHarness();
    await h.pool.query("INSERT INTO licenses (code, name, requires_attribution) VALUES ('cc-by', 'CC BY', true)");
    await h.pool.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('src-ship', 'institution-site', 'Ship', 'Open University', 'https://example.org/ship')");
    await h.pool.query("INSERT INTO authors (id, slug, name, monogram, kind) VALUES ('inst-ship', 'inst-ship', 'Ship University', 'SU', 'institution')");
  });
  afterAll(async () => { await h.close(); });

  const seen: string[] = [];
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const recorded = new URL(input instanceof Request ? input.url : String(input));
    seen.push(`${init?.method ?? "GET"} ${recorded.pathname}`);
    const url = new URL(input instanceof Request ? input.url : String(input));
    const headers = new Headers(init?.headers);
    headers.set("x-forwarded-for", "192.0.2.60");
    if (url.pathname.startsWith("/api/admin/media")) {
      const request = new Request(url, { method: init?.method ?? "GET", headers, ...(init?.body === undefined ? {} : { body: init.body as BodyInit }) });
      return dispatchAdminRequest(request, {
        handlers: mediaHandlers({
          secret: SECRET, limiter: h.deps.limiter, db: () => h.pool, store: () => h.store, invalidate: () => undefined,
          courseOf: catalogCourseOf(() => h.pool), owners: catalogOwners,
        }),
        authorize: (request) => adminAuthorization(request, { secret: SECRET, limiter: h.deps.limiter }),
      });
    }
    const pathname = url.pathname.slice(BASE.length);
    const route = ADMIN_CATALOG_ROUTES.find((entry) => entry.method === (init?.method ?? "GET") && new RegExp(`^${entry.path.replace(/:\w+/g, "[^/]+")}$`).test(pathname));
    if (!route) return new Response("not found", { status: 404 });
    const names = [...route.path.matchAll(/:(\w+)/g)].map((match) => match[1] ?? "");
    const values = new RegExp(`^${route.path.replace(/:\w+/g, "([^/]+)")}$`).exec(pathname)?.slice(1) ?? [];
    return route.run(new Request(url, { method: init?.method ?? "GET", headers, ...(init?.body === undefined ? {} : { body: init.body as string }) }), Object.fromEntries(names.map((name, index) => [name, decodeURIComponent(values[index] ?? "")])), h.deps);
  }) as typeof fetch;

  async function ship(dir: string): Promise<{ code: number; stdout: string; stderr: string }> {
    let stdout = "";
    let stderr = "";
    let uuid = 0;
    const code = await main(["ship", dir, "--to", "preview", "--yes", "--target", "preview"], {
      io: { stdout: (text) => { stdout += text; }, stderr: (text) => { stderr += text; }, prompt: null },
      env: { TOWER_MEDIA_URL_PREVIEW: ORIGIN }, hostname: "int-box",
      uuid: () => { uuid += 1; return `22222222-0000-4000-8000-${String(uuid).padStart(12, "0")}`; },
      now: () => new Date("2026-10-11T12:00:00.000Z"), sleep: () => Promise.resolve(), oembed: () => Promise.resolve({ status: "ok" }),
      run: () => Promise.resolve({ code: 0, stdout: "", stderr: "" }), appRoot: "/nonexistent", home: "/tmp",
      transport: () => fetchTransport({ secrets: { prod: SECRET, preview: SECRET } }, "preview", fetchImpl), secrets: () => [SECRET],
    });
    return { code, stdout, stderr };
  }

  it("publishes the draft, stores covers at m/<sha256>, lands metadata, and repeats as a no-op", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-db-"));
    await writeCourse(dir, "course-ship-a", "#112233", 1);
    await writeCourse(dir, "course-ship-b", "#334455", 2);
    const first = await ship(dir);
    expect(first.code, `${first.stdout}\n${first.stderr}`).toBe(0);
    expect(first.stdout).not.toContain(SECRET);
    const courses = (await h.pool.query<{ id: string; status: string; language_label: string; area_id: string; subarea_id: string; license_code: string; source_id: string; attribution_text: string; canonical_url: string; rights_status: string }>(
      "SELECT id, status, language_label, area_id, subarea_id, license_code, source_id, attribution_text, canonical_url, rights_status FROM courses ORDER BY id",
    )).rows;
    expect(courses).toEqual([
      { id: "course-ship-a", status: "published", language_label: "English", area_id: "computer-science", subarea_id: "programming", license_code: "cc-by", source_id: "src-ship", attribution_text: "Open University", canonical_url: "https://example.org/course-ship-a", rights_status: "cleared" },
      { id: "course-ship-b", status: "published", language_label: "English", area_id: "computer-science", subarea_id: "programming", license_code: "cc-by", source_id: "src-ship", attribution_text: "Open University", canonical_url: "https://example.org/course-ship-b", rights_status: "cleared" },
    ]);
    const applies = Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_audit WHERE action = 'course.publish.apply'")).rows[0]?.n);
    expect(applies).toBe(1);
    expect(Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n)).toBe(1);
    expect(first.stdout).toContain("committed");
    expect(first.stdout).not.toMatch(/\d+ms/);
    const allowed = new Set(["POST /api/admin/media/check", "POST /api/admin/media/objects", "POST /api/admin/catalog/batches/apply"]);
    expect(seen.every((call) => allowed.has(call)), seen.join("\n")).toBe(true);
    expect(seen).toContain("POST /api/admin/catalog/batches/apply");
    const objects = (await h.pool.query<{ sha256: string; ext: string; pathname: string }>(
      "SELECT o.sha256, o.ext, a.pathname FROM catalog_media a JOIN media_objects o ON o.sha256 = a.media_sha256 WHERE a.owner_kind = 'course' AND a.is_active ORDER BY a.owner_id, a.kind",
    )).rows;
    expect(objects).toHaveLength(8);
    for (const object of objects) {
      expect(object.pathname).toBe(`m/${object.sha256}.${object.ext}`);
      expect(await h.store.head(object.pathname)).not.toBeNull();
    }
    const releases = Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n);
    const stored = Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM media_objects")).rows[0]?.n);
    const second = await ship(dir);
    expect(second.code, `${second.stdout}\n${second.stderr}`).toBe(0);
    expect(second.stdout).not.toMatch(/\d+ms/);
    expect(Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n)).toBe(releases);
    expect(Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_audit WHERE action = 'course.publish.apply'")).rows[0]?.n)).toBe(applies);
    expect(Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM media_objects")).rows[0]?.n)).toBe(stored);
    expect(Number((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM courses WHERE status = 'published'")).rows[0]?.n)).toBe(2);
  });
});
