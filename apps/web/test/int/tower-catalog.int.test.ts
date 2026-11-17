import type { PublicCatalog } from "../../src/catalog/domain/release.ts";
import sharp from "sharp";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
// /api/health reads getCatalogState; this stand-in reads the active release of the test database uncached (as after an
// activation), like catalog-admin-flow.int.test.ts.
const state = vi.hoisted(() => ({ pool: null as null | { query(sql: string): Promise<{ rows: Record<string, unknown>[] }> } }));
vi.mock("@tower/catalog", async () => {
  const read = await import("../../src/catalog/server/read.ts");
  return { getCatalogState: () => read.resolveCatalog(() => read.readActiveRelease(state.pool as NonNullable<typeof state.pool>), {}) };
});
import { GET as health } from "../../src/app/api/health/route.ts";
import { ADMIN_CATALOG_ROUTES } from "../../src/catalog/server/routes.ts";
import { TEXT_FIELDS } from "../../src/catalog/domain/fields.ts";
import { readActiveRelease } from "../../src/catalog/server/read.ts";
import { readCatalogTables } from "../../src/catalog/server/table-io.ts";
import { swapMedia } from "../../src/media/server/repository.ts";
import type { MediaKind } from "../../src/media/domain/types.ts";
import { fetchTransport } from "../../scripts/lib/catalog-cli/client.ts";
import { snapshotFiles } from "../../scripts/lib/catalog-export.ts";
import type { Runner } from "../../scripts/lib/catalog-cli/context.ts";
import { main } from "../../scripts/lib/catalog-cli/main.ts";
import { activeRelease, auditRows, call, coverInput, createHarness, newVideoId, SECRET, seedCatalog, slotText, type Harness } from "../fixtures/admin-catalog.ts";

// Contract test CLI ↔ API on PG18: tower-catalog's real client and fetch transport (Bearer included) in front of the
// real route table and handlers (ADMIN_CATALOG_ROUTES with the test deps), driving one course from import to purge.
const ORIGIN = "https://tower0int.lambda-url.us-east-1.on.aws";
const BASE = "/api/admin/catalog";

describe("tower-catalog against the admin API on PG18", () => {
  let h: Harness;
  const media: string[] = [];
  beforeAll(async () => { h = createHarness(); state.pool = h.pool; await seedCatalog(h); });
  afterAll(async () => { await h.close(); });

  /** fetch for the CLI: admin routes run in process; /api/health is the real route; /c/<slug> is 200 when the active release has it. */
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : input);
    if (url.pathname === "/api/health") return health(new Request(url));
    if (url.pathname.startsWith("/c/")) {
      const { release } = await readActiveRelease(h.pool);
      return new Response("", { status: release.courses.some((course) => `/c/${course.slug}` === url.pathname) ? 200 : 404 });
    }
    if (url.pathname.startsWith("/api/admin/media")) {
      const pathname = url.pathname.slice("/api/admin/media".length) || "/";
      if ((init?.method ?? "GET") === "POST" && pathname === "/attach" && typeof init?.body === "string") {
        const body = JSON.parse(init.body) as { owner: "course" | "lesson"; ownerId: string; kind: MediaKind };
        media.push(`${body.owner}:${body.ownerId}:${body.kind}`);
        await swapMedia(h.pool, body.owner, coverInput(body.owner, body.ownerId, body.kind));
      }
      const requestId = new Headers(init?.headers).get("x-request-id") ?? "media-int";
      const hashes = pathname === "/check" && typeof init?.body === "string" ? (JSON.parse(init.body) as { sha256: string[] }).sha256 : [];
      const data = pathname === "/check" ? { missing: [], objects: hashes.map((sha256) => ({ sha256 })) } : { sha256: hashes[0] ?? "a".repeat(64), width: 8, height: 8, version: 1 };
      return new Response(JSON.stringify({ ok: true, data, requestId }), { status: 200, headers: { "content-type": "application/json", "x-request-id": requestId } });
    }
    const pathname = url.pathname.slice(BASE.length);
    const route = ADMIN_CATALOG_ROUTES.find((entry) => entry.method === (init?.method ?? "GET") && new RegExp(`^${entry.path.replace(/:\w+/g, "[^/]+")}$`).test(pathname));
    if (!route) return new Response("not found", { status: 404 });
    const names = [...route.path.matchAll(/:(\w+)/g)].map((match) => match[1] ?? "");
    const values = new RegExp(`^${route.path.replace(/:\w+/g, "([^/]+)")}$`).exec(pathname)?.slice(1) ?? [];
    const headers = new Headers(init?.headers);
    headers.set("x-forwarded-for", "192.0.2.50");
    return route.run(new Request(url, { method: init?.method ?? "GET", headers, ...(init?.body === undefined ? {} : { body: init.body as string }) }), Object.fromEntries(names.map((name, index) => [name, decodeURIComponent(values[index] ?? "")])), h.deps);
  }) as typeof fetch;

  /** tower-media put, faked: the cover row it would write (no bytes, no network). */
  const run: Runner = async (command, args) => {
    if (!command.endsWith("tower-media")) return { code: 127, stdout: "", stderr: "unexpected" };
    const owner = args.includes("--course") ? "course" : "lesson";
    const id = args[args.indexOf(owner === "course" ? "--course" : "--lesson") + 1] ?? "";
    const kind = args[args.indexOf("--kind") + 1] as MediaKind;
    media.push(`${owner}:${id}:${kind}`);
    await swapMedia(h.pool, owner, coverInput(owner, id, kind));
    return { code: 0, stdout: "", stderr: "" };
  };

  let uuid = 0;
  async function cli(...argv: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
    let stdout = "";
    let stderr = "";
    const code = await main([...argv, "--target", "preview"], {
      io: { stdout: (text) => { stdout += text; }, stderr: (text) => { stderr += text; }, prompt: null },
      env: { TOWER_MEDIA_URL_PREVIEW: ORIGIN }, hostname: "int-box",
      uuid: () => { uuid += 1; return `11111111-0000-4000-8000-${String(uuid).padStart(12, "0")}`; },
      now: () => new Date("2026-10-11T12:00:00.000Z"), sleep: () => Promise.resolve(), oembed: () => Promise.resolve({ status: "ok" }), run,
      appRoot: "/nonexistent", home: "/tmp",
      transport: (target) => fetchTransport({ secrets: { prod: SECRET, preview: SECRET } }, target, fetchImpl), secrets: () => [SECRET],
    });
    expect(`${stdout}${stderr}`).not.toContain(SECRET);
    return { code, stdout, stderr };
  }
  const ok = async (...argv: string[]) => {
    const result = await cli(...argv);
    expect(result.code, `${argv.join(" ")}\n${result.stderr}`).toBe(0);
    return result;
  };
  const parse = (result: { stdout: string }): unknown => JSON.parse(result.stdout);
  const write = (name: string, value: unknown) => { const path = join(mkdtempSync(join(tmpdir(), "tc-int-")), name); writeFileSync(path, JSON.stringify(value)); return path; };

  it("takes a course from import to purge, replays repeated commands and leaves the doctor clean", async () => {
    const before = await activeRelease(h);
    expect(before.number).toBe(1);

    // Author: the same command twice is one mutation and one audit row (the second answer is the stored one).
    const authorArgs = ["author", "create", "--slug", "p5-author", "--name", "P5 Author", "--monogram", "PA", "--json", "--kind", "person"];
    const author = (parse(await ok(...authorArgs)) as { data: { author: { id: string } } }).data.author.id;
    const again = await ok(...authorArgs);
    expect(again.stderr).toContain("Replayed the stored answer");
    expect((parse(again) as { data: { author: { id: string } } }).data.author.id).toBe(author);
    expect(await auditRows(h, { action: "author.create", entity: `author:${author}` })).toHaveLength(1);

    // Import: three extracted items, one excluded on the command line; repeating it reuses the stored import and draft.
    const videos = [newVideoId(), newVideoId(), newVideoId(), newVideoId()];
    const items = write("items.json", { playlistTitle: "P5 lectures", items: videos.map((id, index) => ({ id, title: `P5 Lecture ${String(index + 1)} | Test`, duration: 1500 + index, playlistIndex: index + 1 })) });
    const importArgs = ["import", "https://www.youtube.com/playlist?list=PLp5smoke0001", "--slug", "p5", "--author", author, "--items", items, "--exclude", videos[3] ?? "",
      "--source-id", "src-test", "--license-code", "youtube-standard", "--canonical-url", "https://example.org/p5", "--json"];
    const imported = (parse(await ok(...importArgs)) as { data: { import: { report: { accepted: unknown[] } }; draft: { course: { id: string }; lessons: { id: string }[] } } }).data;
    expect(imported.import.report.accepted).toHaveLength(4);
    const course = imported.draft.course.id;
    const lessons = imported.draft.lessons.map((lesson) => lesson.id);
    expect(lessons).toHaveLength(3);
    const repeat = await ok(...importArgs);
    expect((parse(repeat) as { data: { draft: { course: { id: string } } } }).data.draft.course.id).toBe(course);
    expect((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_imports WHERE playlist_id = 'PLp5smoke0001'")).rows[0]?.n).toBe(1);

    // Copy: the draft-copy pack's template, filled within the slots, written as draft in one batch.
    const pack = (parse(await ok("draft-copy", course, "--json")) as { data: { template: { entityKind: string; entityId: string; field: string; text: string }[] } }).data;
    const filled = pack.template.map((item, index) => ({ ...item, text: item.entityKind === "course" ? slotText(item.field, "p5") : `P5 lesson ${String(index)}` }));
    expect(filled.filter((item) => item.entityKind === "course").map((item) => item.field)).toEqual(Object.keys(TEXT_FIELDS.course));
    await ok("texts", "put", course, "--file", write("texts.json", filled));
    expect((await cli("status", course, "review")).code).toBe(4);

    // Covers through the tower-media wrapper (faked), then review.
    const covers = mkdtempSync(join(tmpdir(), "tc-covers-"));
    const tiny = await sharp({ create: { width: 64, height: 36, channels: 3, background: "#334455" } }).jpeg().toBuffer();
    for (const name of ["poster.jpg", "hero-desktop.jpg", "hero-present.jpg", "hero-mobile.jpg", "still.jpg"]) writeFileSync(join(covers, name), tiny);
    const uploaded = await ok("covers", course, "--dir", covers);
    // Six uploads: poster, heroes, still, and the 1200×630 link preview rendered from hero-desktop (`hero_desktop_16x9/og`). Order is completion order of the parallel puts.
    expect([...media].sort()).toEqual(["hero_desktop_16x9", "hero_desktop_16x9", "hero_mobile_9x16", "hero_present", "poster_9x16", "still_16x9"].map((kind) => `course:${course}:${kind}`));
    expect(uploaded.stdout).toContain(`Nothing missing for review: tower-catalog status ${course} review.`);
    await ok("status", course, "review");
    const review = await ok("review", course);
    expect(review.stdout).toContain("Preconditions for review: all met");
    expect(review.stdout).toContain("texts.approved");

    // Approval of exactly what was read, rights, Home row, preview link.
    await ok("approve", course, "--by", "Daniel", "--yes");
    expect((await ok("approve", course, "--by", "Daniel", "--yes")).stdout).toContain("Nothing to approve");
    await ok("course", "set", course, "--rights-status", "cleared", "--rights-notes", "P5 smoke", "--area-id", "computer-science", "--subarea-id", "programming");
    // D-024: the course's author is its lecturer; the University row belongs to an institution.
    const p5University = (parse(await ok("author", "create", "--slug", "p5-university", "--name", "P5 University", "--monogram", "PU", "--json", "--kind", "institution")) as { data: { author: { id: string } } }).data.author.id;
    const home = (parse(await ok("home", "get", "--json")) as { data: { featuredCourseId: string; rows: { id: string; kind: string; title: string | null; courseIds: string[]; cover?: PublicCatalog["home"]["rows"][number]["cover"] }[] } }).data;
    await ok("home", "set", "--yes", "--file", write("home.json", { featuredCourseId: home.featuredCourseId, rows: [...home.rows.map((row) => ({ id: row.id, kind: row.kind, ...(row.title ? { title: row.title } : {}), courseIds: row.courseIds })), { id: "p5-row", kind: "curated", institutionId: p5University, title: "P5", cover: home.rows.find((row) => row.id === "picks")?.cover, courseIds: [course] }] }));
    expect((await ok("preview-url", course, "--ttl-minutes", "5")).stdout).toMatch(new RegExp(`^${ORIGIN}/api/catalog/preview\\?token=[^&]+&to=%2Fc%2Fp5\\n$`));

    // Publish: release 2, verified on /api/health and /c/p5.
    const published = await ok("publish", course, "--note", "P5 publish", "--yes");
    expect(published.stdout).toContain("Published: release #3");
    expect(published.stdout).toContain("/api/health serves it with 1 course(s).");
    expect(await activeRelease(h)).toMatchObject({ number: 3 });
    expect((parse(await ok("release", "list", "--json")) as { data: { releases: { number: number; isActive: boolean }[] } }).data.releases.map((release) => [release.number, release.isActive])).toEqual([[3, true], [2, false], [1, false]]);
    expect((await ok("release", "diff")).stdout).toContain("no change");
    expect((await ok("release", "diff", "1", "3")).stdout).toContain(`courses added: ${course}`);

    // Reorder the complete permutation (a move), then unpublish, archive and purge.
    await ok("lesson", "reorder", course, "--move", lessons[2] ?? "", "--to", "1");
    expect((await h.pool.query<{ id: string }>("SELECT id FROM lessons WHERE course_id = $1 ORDER BY position", [course])).rows.map((row) => row.id)).toEqual([lessons[2], lessons[0], lessons[1]]);
    expect((await cli("lesson", "reorder", course, "--ids", `${lessons[0] ?? ""},${lessons[0] ?? ""}`)).code).toBe(2);
    expect((await ok("unpublish", course, "--note", "P5 down", "--yes")).stdout).toContain("Unpublished: release #4");
    const dry = await ok("course", "delete", course, "--mode", "purge");
    expect(dry.stdout).toContain("Nothing changed. Re-run with --confirm");
    await ok("course", "delete", course, "--mode", "archive", "--confirm", "--yes");
    await ok("course", "delete", course, "--mode", "purge", "--confirm", "--yes");
    expect((await h.pool.query<{ n: number }>("SELECT count(*)::int AS n FROM courses WHERE id = $1", [course])).rows[0]?.n).toBe(0);
    const cleanup = (parse(await ok("home", "get", "--json")) as { data: { featuredCourseId: string; rows: { id: string; kind: string; title: string | null; courseIds: string[] }[] } }).data;
    await ok("home", "set", "--yes", "--file", write("home-cleanup.json", { featuredCourseId: cleanup.featuredCourseId, rows: cleanup.rows.filter((row) => row.id !== "p5-row").map((row) => ({ id: row.id, kind: row.kind, ...(row.title ? { title: row.title } : {}), courseIds: row.courseIds })) }));
    await ok("author", "delete", author, "--confirm", "--yes");

    // The site is back to the seeded catalog, and every change carries the CLI's actor.
    const { release: live } = await readActiveRelease(h.pool);
    expect(live.courses.map((entry) => entry.slug)).toEqual(["alpha", "beta"]);
    expect((await auditRows(h, { entity: `course:${course}` })).every((row) => row.actor === "cli:tower-catalog@int-box")).toBe(true);
    const doctor = await cli("doctor");
    expect(doctor.code, doctor.stdout).toBe(0);
  });

  it("exports through GET /tables exactly what the database holds, and snapshot writes it stably", async () => {
    const exported = await call<{ activeRelease: { number: number; sha: string }; tables: unknown }>(h, "GET", "/tables");
    expect(exported.data.tables).toEqual(await readCatalogTables(h.pool));
    expect(exported.data.activeRelease).toEqual(await activeRelease(h));
    const dir = mkdtempSync(join(tmpdir(), "tc-snapshot-"));
    expect((await ok("snapshot", "--dir", dir)).stdout).toContain("14 file(s) changed");
    expect((await ok("snapshot", "--dir", dir)).stdout).toContain(": no change.");
    const expected = snapshotFiles((await readActiveRelease(h.pool)).release, await readCatalogTables(h.pool));
    for (const [name, text] of expected) expect(readFileSync(join(dir, name), "utf8"), name).toBe(text);
  });

  it("maps the API's errors to exit codes with the full precondition list", async () => {
    const authorId = String((await h.pool.query<{ id: string }>("SELECT id FROM authors ORDER BY id LIMIT 1")).rows[0]?.id);
    const created = (parse(await ok("course", "create", "--slug", "p5-errors", "--author-id", authorId, "--title", "Errors", "--cover-from", "own", "--json")) as { data: { course: { id: string } } }).data.course.id;
    const blocked = await cli("status", created, "review");
    expect(blocked.code).toBe(4);
    expect(blocked.stderr).toContain("Unmet preconditions (");
    expect(blocked.stderr).toContain("- lessons.visible");
    expect((await cli("course", "create", "--slug", "p5-errors", "--author-id", authorId, "--title", "Again", "--cover-from", "own")).code).toBe(3);
    expect((await cli("course", "create", "--slug", "p5-unknown", "--author-id", "author-99999", "--title", "Nobody", "--cover-from", "own")).code).toBe(5);
    expect((await cli("course", "get", "course-99999")).code).toBe(1);
    await ok("course", "delete", created, "--mode", "purge", "--confirm", "--yes");
  });
});
