import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { COURSE_LIST_LIMIT, REDIRECT_LIST_LIMIT } from "../src/catalog/domain/contracts.ts";
import { ADMIN_CATALOG_ROUTES } from "../src/catalog/server/routes.ts";
import { sha256Hex } from "../src/kernel/canonical.ts";
import { courseDetail, fakeApi, importedTables, NOW, ORIGIN, runCli, SENTINEL, twoEditions, type Handler } from "./lib/catalog-cli/cli.test-helpers.ts";
import { cliRoute, ROUTE_KEYS, type RouteKey } from "./lib/catalog-cli/routes.ts";
import { COMMANDS, REFUSALS } from "./lib/catalog-cli/registry.ts";
import { actorFor } from "./lib/catalog-cli/main.ts";
import { ALLOWED_HOSTS, parseCredentials, secretFor, targetOrigin } from "./lib/catalog-cli/target.ts";
import { redact, scrub } from "./lib/catalog-cli/redact.ts";
import { idempotencyKey } from "./lib/catalog-cli/client.ts";
import { EXIT } from "./lib/catalog-cli/errors.ts";
import { reviewLines } from "./lib/catalog-cli/render.ts";

const repo = fileURLToPath(new URL("../", import.meta.url));
const wrapper = join(repo, "tooling/tower-catalog");
const tmp = () => mkdtempSync(join(tmpdir(), "tower-catalog-"));
const P = ["--target", "preview"];
const coursePage = `limit=${String(COURSE_LIST_LIMIT)}`;

function sampleShip() {
  return {
    version: 2,
    courses: [{ institutionId: "usp", course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] }, editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }] }],
  };
}

function sampleBundle() {
  return {
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id: "course-live", slug: "contracts", title: "Contracts", authorId: "author-a", coverFrom: "own", sharedWith: [] },
    editions: [{ id: "edition-1", slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons: [{ id: "lesson-1", editionId: "edition-1", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
  };
}

function file(name: string, content: unknown): string {
  const path = join(tmp(), name);
  writeFileSync(path, typeof content === "string" ? content : JSON.stringify(content));
  return path;
}

const textsFile = () => file("texts.json", [
  { entityKind: "course", entityId: "course-6", field: "subtitle", text: "On dreams and slips", source: "llm", sourceRef: "draft-copy", confidence: "medium" },
  { entityKind: "lesson", entityId: "lesson-212", field: "displayTitle", text: "The second lecture", source: "llm", sourceRef: "draft-copy", confidence: "medium" },
]);
const homeFile = () => file("home.json", { featuredCourseId: "course-1", rows: [{ id: "continue", kind: "continue", courseIds: [] }, { id: "picks", kind: "curated", title: "Picks", courseIds: ["course-1", "course-6"] }] });
const itemsFile = () => file("items.json", { playlistTitle: "Freud lectures", items: [{ id: "vid00000001", title: "Lecture 1", duration: 1500 }, { id: "vid00000002", title: "Lecture 2", duration: 1600 }] });
// hero-desktop is a real image: covers renders the link preview (og) from it.
const heroBytes = await sharp({ create: { width: 640, height: 360, channels: 3, background: "#334455" } }).webp().toBuffer();
const heroFile = () => { const path = join(tmp(), "hero.webp"); writeFileSync(path, heroBytes); return path; };
const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAEUlEQVQImWMQVDLGihiGlgQA7s8ZgXTHRXQAAAAASUVORK5CYII=", "base64");
const tinyJpg = Buffer.from("/9j/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAOAAgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AK+AaEP/2Q==", "base64");
const tinyWebp = Buffer.from("UklGRjAAAABXRUJQVlA4ICQAAABwAQCdASoQAAkAAUAmJYwCdAFAAAD+8U2sCStWbpyzOFefAAA=", "base64");
function coversDir(): string {
  const dir = tmp();
  writeFileSync(join(dir, "poster.jpg"), tinyJpg);
  writeFileSync(join(dir, "hero-present.webp"), tinyWebp);
  writeFileSync(join(dir, "hero-mobile.jpg"), tinyJpg);
  writeFileSync(join(dir, "still.png"), tinyPng);
  writeFileSync(join(dir, "hero-desktop.webp"), heroBytes);
  mkdirSync(join(dir, "lessons"));
  writeFileSync(join(dir, "lessons", "02.jpg"), tinyJpg);
  return dir;
}

/** One working command line per command and the admin requests it sends, in order (the command → route table). */
const EXAMPLES: Record<string, { argv: () => string[]; calls: string[]; handlers?: Partial<Record<RouteKey | "public", Handler>> }> = {
  import: { argv: () => ["import", "https://www.youtube.com/playlist?list=PLabc", "--slug", "freud-2", "--author", "new:Sigmund Freud", "--author-kind", "person", "--items", itemsFile(), "--exclude", "vid00000002"], calls: ["POST /imports", "POST /imports/import-PLabc-202610111200/draft"] },
  "draft-copy": { argv: () => ["draft-copy", "course-6"], calls: ["GET /courses/course-6", `GET /courses?status=published&${coursePage}`, "GET /texts?entity=course%3Acourse-1"], handlers: { "GET /courses": () => ({ data: { courses: [{ id: "course-1" }, { id: "course-6" }] } }) } },
  "texts get": { argv: () => ["texts", "get", "course-6"], calls: ["GET /courses/course-6"] },
  "texts put": { argv: () => ["texts", "put", "course-6", "--file", textsFile()], calls: ["GET /courses/course-6", "PUT /texts"] },
  "texts revoke": { argv: () => ["texts", "revoke", "course-6", "--fields", "displayTitle"], calls: ["GET /courses/course-6", "POST /texts/revoke"] },
  review: { argv: () => ["review", "course-6"], calls: ["GET /courses/course-6"] },
  approve: { argv: () => ["approve", "course-6", "--by", "Daniel", "--yes"], calls: ["GET /courses/course-6", "POST /texts/approve"] },
  covers: { argv: () => ["covers", "course-6", "--dir", coversDir()], calls: ["GET /courses/course-6", "GET /courses/course-6"] },
  media: { argv: () => ["media", "list", "--course", "course-6"], calls: ["GET /api/admin/media?owner=course&ownerId=course-6"] },
  "preview-url": { argv: () => ["preview-url", "course-6", "--ttl-minutes", "10"], calls: ["POST /preview-token"] },
  status: { argv: () => ["status", "course-6", "review"], calls: ["GET /courses/course-6", "POST /courses/course-6/status"] },
  publish: { argv: () => ["publish", "course-6", "--note", "Publish Freud", "--yes"], calls: ["GET /courses/course-6", "GET /releases", "POST /releases?dryRun=true", "POST /courses/course-6/publish", "GET /releases"] },
  unpublish: { argv: () => ["unpublish", "course-6", "--note", "Down", "--to", "archived", "--yes"], calls: ["GET /courses/course-6", "GET /releases", "POST /releases?dryRun=true", "POST /courses/course-6/unpublish", "GET /releases"] },
  "course list": { argv: () => ["course", "list", "--status", "review"], calls: [`GET /courses?status=review&${coursePage}`] },
  "course get": { argv: () => ["course", "get", "course-6"], calls: ["GET /courses/course-6"] },
  "course create": { argv: () => ["course", "create", "--slug", "freud-2", "--author-id", "author-3", "--title", "Freud II", "--lesson-noun", "Lecture", "--cover-from", "own"], calls: ["POST /courses"] },
  "course set": { argv: () => ["course", "set", "course-6", "--title", "Freud!", "--rights-status", "cleared", "--unset", "attribution-text"], calls: ["GET /courses/course-6", "PATCH /courses/course-6"] },
  "course delete": { argv: () => ["course", "delete", "course-6", "--mode", "purge", "--confirm", "--yes"], calls: ["DELETE /courses/course-6?mode=purge", "GET /courses/course-6", "DELETE /courses/course-6?mode=purge&confirm=true&expectedRevision=7"] },
  "edition list": { argv: () => ["edition", "list", "freud"], calls: [`GET /courses?${coursePage}`, "GET /courses/course-6/editions"] },
  "edition create": { argv: () => ["edition", "create", "course-6", "--label", "Spring 2026"], calls: ["POST /courses/course-6/editions"] },
  "edition set": { argv: () => ["edition", "set", "course-6", "fall-2025", "--resolution", "1080p"], calls: ["GET /courses/course-6", "GET /courses/course-6", "PATCH /editions/edition-6"] },
  "edition reorder": {
    argv: () => ["edition", "reorder", "course-6", "--ids", "fall-2025,spring-2026"], calls: ["GET /courses/course-6", "PUT /courses/course-6/editions/order"],
    handlers: { "GET /courses/:id": () => ({ data: twoEditions() }) },
  },
  "edition delete": { argv: () => ["edition", "delete", "course-6", "fall-2025", "--with-lessons"], calls: ["GET /courses/course-6", "DELETE /editions/edition-6?mode=with-lessons"] },
  "lesson create": { argv: () => ["lesson", "create", "course-6", "--youtube-id", "vid00000004", "--duration-seconds", "900", "--position", "2", "--part", "labs"], calls: ["GET /courses/course-6", "POST /courses/course-6/lessons"] },
  "lesson set": { argv: () => ["lesson", "set", "course-6", "lesson-213", "--visible", "true"], calls: ["GET /courses/course-6", "PATCH /lessons/lesson-213"] },
  "lesson delete": { argv: () => ["lesson", "delete", "course-6", "lesson-213"], calls: ["DELETE /lessons/lesson-213"] },
  "lesson reslug": {
    argv: () => ["lesson", "reslug", "cmu-db"], calls: ["GET /tables", "GET /courses/course-30", "PUT /lessons/slugs"],
    handlers: { "GET /tables": () => ({ data: { activeRelease: null, tables: importedTables() } }) },
  },
  "lesson reorder": { argv: () => ["lesson", "reorder", "course-6", "--move", "lesson-213", "--to", "1"], calls: ["GET /courses/course-6", "PUT /courses/course-6/lessons/order"] },
  "author list": { argv: () => ["author", "list"], calls: ["GET /authors"] },
  "author create": { argv: () => ["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", "--kind", "person"], calls: ["POST /authors"] },
  "author set": { argv: () => ["author", "set", "author-3", "--name", "S. Freud"], calls: ["GET /authors", "PATCH /authors/author-3"] },
  "author cover": { argv: () => ["author", "cover", "author-3", "--clear", "--yes"], calls: ["GET /authors", "PATCH /authors/author-3"] },
  "home og": { argv: () => ["home", "og"], calls: ["GET /home"] },
  og: { argv: () => ["og", "course-6", "--file", heroFile(), "--yes"], calls: ["GET /courses/course-6"] },
  "author delete": { argv: () => ["author", "delete", "author-3", "--confirm", "--yes"], calls: ["DELETE /authors/author-3", "GET /authors", "DELETE /authors/author-3?confirm=true&expectedRevision=4"] },
  "home get": { argv: () => ["home", "get"], calls: ["GET /home"] },
  "home set": { argv: () => ["home", "set", "--file", homeFile(), "--yes"], calls: ["GET /home", "GET /releases", "PUT /home", "GET /releases"] },
  "release list": { argv: () => ["release", "list"], calls: ["GET /releases"] },
  "release diff": { argv: () => ["release", "diff", "2", "3"], calls: ["GET /releases/2", "GET /releases/3"] },
  "release create": { argv: () => ["release", "create", "--note", "Redirects", "--yes"], calls: ["GET /releases", "POST /releases?dryRun=true", "POST /releases", "GET /releases"] },
  "release activate": { argv: () => ["release", "activate", "2", "--yes"], calls: ["GET /releases", "POST /releases/2/activate", "GET /releases"] },
  doctor: { argv: () => ["doctor"], calls: ["GET /doctor"] },
  "bundle validate": { argv: () => ["bundle", "validate", "--file", file("bundle.json", sampleBundle())], calls: ["POST /bundles/validate"] },
  "bundle diff": { argv: () => ["bundle", "diff", "--file", file("bundle.json", sampleBundle())], calls: ["POST /bundles/diff"] },
  "bundle apply": { argv: () => ["bundle", "apply", "--file", file("bundle.json", sampleBundle()), "--yes"], calls: ["POST /bundles/apply"] },
  "bundle export": { argv: () => ["bundle", "export", "--file", file("bundle.json", sampleBundle()), "--out", join(tmp(), "out.json")], calls: ["POST /bundles/export"] },
  "lifecycle inventory": { argv: () => ["lifecycle", "inventory"], calls: ["POST /lifecycle/inventory", "POST /lifecycle/inventory", "POST /lifecycle/gc"] },
  "lifecycle gc": { argv: () => ["lifecycle", "gc"], calls: ["POST /lifecycle/inventory", "POST /lifecycle/inventory", "POST /lifecycle/gc"] },
  "lifecycle preview-reset": { argv: () => ["lifecycle", "preview-reset"], calls: ["POST /lifecycle/preview-reset"] },
  ship: {
    argv: () => ["ship", file("batch.json", sampleShip()), "--to", "preview", "--draft", "--yes"],
    calls: ["POST /batches/apply"],
  },
  check: { argv: () => ["check", "--embeds", "course-6", "--pause", "0"], calls: ["GET /courses/course-6"] },
  snapshot: { argv: () => ["snapshot", "--dir", tmp()], calls: ["GET /tables", "GET /releases/1"] },
  "audit show": { argv: () => ["audit", "show", "course:course-6", "--limit", "5"], calls: ["GET /audit?entity=course%3Acourse-6&limit=5"] },
  "area list": { argv: () => ["area", "list"], calls: ["GET /areas"] },
  "area create": { argv: () => ["area", "create", "--id", "design", "--title", "Design", "--yes"], calls: ["POST /areas"] },
  "area move": { argv: () => ["area", "move", "psychology", "--position", "1", "--yes"], calls: ["POST /areas/psychology/move"] },
  "area update": { argv: () => ["area", "update", "psychology", "--title", "Psychology & Mind", "--yes"], calls: ["PATCH /areas/psychology"] },
  "subarea list": { argv: () => ["subarea", "list", "--area", "engineering"], calls: ["GET /subareas"] },
  "subarea create": { argv: () => ["subarea", "create", "--id", "nuclear-engineering", "--area-id", "engineering", "--title", "Nuclear Engineering", "--yes"], calls: ["POST /subareas"] },
  "course classify": {
    argv: () => ["course", "classify", "--file", file("classify.csv", "course,area_id,subarea_id\nfreud,psychology,null\n"), "--release", "--note", "Subareas", "--yes"],
    calls: [`GET /courses?${coursePage}`, "POST /courses/classify", "GET /releases", "POST /releases?dryRun=true", "POST /releases", "GET /releases"],
  },
  "license list": { argv: () => ["license", "list"], calls: ["GET /licenses"] },
  "license create": { argv: () => ["license", "create", "--code", "cc-by-4.0", "--name", "CC BY 4.0", "--requires-attribution", "true"], calls: ["POST /licenses"] },
  "source list": { argv: () => ["source", "list"], calls: ["GET /sources"] },
  "source create": { argv: () => ["source", "create", "--id", "yale-oyc", "--kind", "institution-site", "--title", "Open Yale", "--publisher", "Yale", "--url", "https://oyc.yale.edu"], calls: ["POST /sources"] },
  "source set": { argv: () => ["source", "set", "src-test", "--title", "Renamed"], calls: ["GET /sources", "PATCH /sources/src-test"] },
  "redirect list": { argv: () => ["redirect", "list"], calls: [`GET /redirects?limit=${String(REDIRECT_LIST_LIMIT)}`] },
  "redirect add": { argv: () => ["redirect", "add", "--from", "/c/old", "--to", "/c/freud"], calls: ["POST /redirects"] },
  "redirect rm": { argv: () => ["redirect", "rm", "--from", "/c/old"], calls: ["DELETE /redirects?from=%2Fc%2Fold"] },
  "batch apply": { argv: () => ["batch", "apply", "--file", file("batch-v2.json", sampleBatch())], calls: ["POST /batches/apply"] },
};

const sampleBatch = () => ({
  version: 2,
  institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: "a".repeat(64) } }],
  lecturers: [{ id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" }],
  courses: [{
    institutionId: "usp",
    course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] },
    editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }],
    covers: [{ kind: "poster_9x16", sha: "a".repeat(64) }],
  }],
});

describe("tower-catalog route table", () => {
  it("names every admin route with the API's method, path, idempotency, mutation and schema objects, and nothing else", () => {
    expect([...ROUTE_KEYS].sort()).toEqual(ADMIN_CATALOG_ROUTES.map((route) => route.key).sort());
    for (const route of ADMIN_CATALOG_ROUTES) {
      const cli = cliRoute(route.key);
      expect([cli.method, cli.path, cli.idempotency, cli.mutates], route.key).toEqual([route.method, route.path, route.idempotency, route.action !== null]);
      expect(cli.query, `${route.key} query schema`).toBe(route.query);
      expect(cli.body, `${route.key} body schema`).toBe(route.body);
    }
  });

  it("has a command for every route and a route for every command (refusals excepted)", () => {
    const used = new Set(COMMANDS.flatMap((command) => command.routes));
    expect(ROUTE_KEYS.filter((key) => !used.has(key))).toEqual([]);
    expect(COMMANDS.filter((command) => command.routes.length === 0).map((command) => command.name)).toEqual(REFUSALS.map((command) => command.name));
    expect(Object.keys(EXAMPLES).sort()).toEqual(COMMANDS.filter((command) => !REFUSALS.includes(command)).map((command) => command.name).sort());
  });
});

describe("tower-catalog --json: one envelope for every command", () => {
  for (const [name, example] of Object.entries(EXAMPLES)) {
    it(`${name}: stdout is exactly one {ok, data} envelope`, async () => {
      const result = await runCli([...example.argv(), ...P, "--json"], { api: fakeApi(example.handlers) });
      const envelope = JSON.parse(result.stdout) as { ok: boolean; data?: unknown; error?: { code: string } };
      // check reports one unavailable video by design (see the commands table): a failure envelope, exit 1.
      if (name === "check") expect([result.code, envelope.ok, envelope.error?.code, "data" in envelope]).toEqual([EXIT.api, false, "embeds_not_ok", false]);
      else expect([result.code, envelope.ok, "data" in envelope], result.stderr).toEqual([EXIT.ok, true, true]);
    });
  }

  it("course list answers {ok, data: {courses, nextCursor}}, not the raw list", async () => {
    const result = await runCli(["course", "list", "--json", ...P]);
    const envelope = JSON.parse(result.stdout) as { ok: boolean; data: { courses: { id: string }[]; nextCursor: null } };
    expect([envelope.ok, envelope.data.nextCursor, envelope.data.courses.length > 0]).toEqual([true, null, true]);
  });

  it("media list --owners is one request and a structured owners list", async () => {
    const api = fakeApi({
      "media:GET /": () => ({ data: { owners: [{ owner: "subarea", ownerId: "calculus", versions: [] }, { owner: "subarea", ownerId: "programming", versions: [{ version: 1, active: true, ownerId: "programming", kind: "poster_9x16", variant: "default", width: 9, height: 16, url: "https://media.test/m/a.webp" }] }] } }),
    });
    const result = await runCli(["media", "list", "--owners", "subarea:calculus,subarea:programming", "--json", ...P], { api });
    const envelope = JSON.parse(result.stdout) as { ok: boolean; data: { owners: { ownerId: string; versions: unknown[] }[] } };
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(api.calls()).toEqual(["GET /api/admin/media?owners=subarea%3Acalculus%2Csubarea%3Aprogramming"]);
    expect(envelope.data.owners.map((owner) => [owner.ownerId, owner.versions.length])).toEqual([["calculus", 0], ["programming", 1]]);
    const mixed = await runCli(["media", "list", "--owners", "subarea:calculus", "--course", "course-6", ...P]);
    expect(mixed.code).toBe(EXIT.usage);
  });

  it("a command without a result of its own sends its lines; a dry run says so", async () => {
    const lines = JSON.parse((await runCli(["media", "prune-inherited", "--json", ...P])).stdout) as { ok: boolean; data: { lines: string[] } };
    expect([lines.ok, Array.isArray(lines.data.lines)]).toEqual([true, true]);
    const dry = await runCli(["status", "course-6", "review", "--dry-run", "--json", ...P]);
    expect([dry.code, JSON.parse(dry.stdout)]).toEqual([EXIT.ok, { ok: true, data: { lines: [], dryRun: true } }]);
  });

  it("failures without an API envelope answer {ok:false, error:{code, message}} on stdout", async () => {
    const usage = await runCli(["course", "get", "--json", ...P]);
    expect([usage.code, (JSON.parse(usage.stdout) as { error: { code: string } }).error.code]).toEqual([EXIT.usage, "usage"]);
    const unknown = await runCli(["nope", "--json", ...P]);
    expect([unknown.code, JSON.parse(unknown.stdout)]).toEqual([EXIT.usage, { ok: false, error: { code: "usage", message: "unknown command \"nope --json\". Run tower-catalog --help." } }]);
    const network = await runCli(["status", "course-6", "review", "--json", ...P], { api: fakeApi({ "POST /courses/:id/status": () => "network" }) });
    expect([network.code, (JSON.parse(network.stdout) as { ok: boolean; error: { code: string } }).error.code]).toEqual([EXIT.network, "network"]);
  });
});

describe("ship --to implies --target", () => {
  it("--to prod alone ships to prod", async () => {
    const api = fakeApi(EXAMPLES.ship?.handlers, undefined, "prod");
    const targets: string[] = [];
    const result = await runCli(["ship", file("batch.json", sampleShip()), "--to", "prod", "--draft", "--yes"], { api, deps: { transport: (target) => { targets.push(target); return api.transport; } } });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(targets).toEqual(["prod"]);
  });

  it("keeps a consistent --target and refuses a conflicting one before any request", async () => {
    const { shipTarget } = await import("./lib/catalog-cli/commands/ship.ts");
    const { parseArgv, GLOBAL_OPTIONS } = await import("./lib/catalog-cli/args.ts");
    const resolve = (...argv: string[]) => shipTarget(parseArgv(argv, { ...GLOBAL_OPTIONS, to: { type: "string", help: "" } }, { min: 0, max: 0 }, "usage"));
    expect([resolve("--to", "preview"), resolve("--to", "prod"), resolve("--to", "both")]).toEqual(["preview", "prod", "prod"]);
    expect([resolve("--to", "prod", "--target", "prod"), resolve("--to", "both", "--target", "preview"), resolve("--to", "preview", "--target", "staging")]).toEqual(["prod", "preview", "staging"]);
    expect(() => resolve("--to", "prod", "--target", "preview")).toThrow("--target preview conflicts with --to prod; drop --target (--to implies it).");
    expect(() => resolve("--to", "preview", "--target", "prod")).toThrow("conflicts with --to preview");
    const api = fakeApi();
    const refused = await runCli(["ship", file("bundle.json", sampleBundle()), "--to", "preview", "--target", "prod", "--yes"], { api });
    expect([refused.code, api.calls()]).toEqual([EXIT.usage, []]);
  });
});

describe("course list pages", () => {
  it("follows nextCursor until every course is listed", async () => {
    const row = (id: string) => ({ id, slug: id, title: id, authorId: "author-3", status: "review", featured: false, revision: 1, publishedAt: null, areaId: null, subareaId: null, counts: { editions: 1, lessons: 1, visibleLessons: 1, texts: 1, draftTexts: 0 }, pending: { target: "published", failed: [] } });
    const api = fakeApi({
      "GET /courses": (request) => {
        if (request.query.cursor === undefined) return { data: { courses: [row("course-1")], nextCursor: "course-1" } };
        return { data: { courses: [row("course-2")], nextCursor: null } };
      },
    });
    const result = await runCli(["course", "list", ...P], { api });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(api.calls()).toEqual([`GET /courses?${coursePage}`, `GET /courses?${coursePage}&cursor=course-1`]);
    expect(result.stdout).toContain("course-1");
    expect(result.stdout).toContain("course-2");
  });
});

describe("tower-catalog commands", () => {
  it("batch apply --dry-run posts dryRun: true and prints the server report", async () => {
    const api = fakeApi({
      "POST /batches/apply": (request) => {
        const body = request.body as { batchHash: string; dryRun: boolean };
        return { data: { status: body.dryRun ? "dry-run" : "committed", batchHash: body.batchHash, draft: false, plan: {}, courses: ["usp-mecanica"], release: { number: 2, created: true } } };
      },
    });
    const result = await runCli(["batch", "apply", "--file", file("batch-v2.json", sampleBatch()), "--dry-run", ...P], { api });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(api.calls()).toEqual(["POST /batches/apply"]);
    expect(api.requests[0]?.body).toMatchObject({ dryRun: true, chunk: 0, chunks: 1 });
    expect(result.stdout).toContain("dry-run");
  });

  for (const [name, example] of Object.entries(EXAMPLES)) {
    it(`${name}: sends exactly its routes, all of them declared`, async () => {
      const api = fakeApi(example.handlers);
      const result = await runCli([...example.argv(), ...P], { api });
      // check reports one unavailable video (the fake oEmbed answers so for ids ending in 2): exit 1 by design.
      expect(result.stderr, result.stderr).toBe(name === "check" ? "tower-catalog: 1 embed(s) not ok.\n" : result.stderr.replace(/tower-catalog:.*/s, ""));
      expect(result.code).toBe(name === "check" ? EXIT.api : EXIT.ok);
      const observed = api.calls().filter((call) => name === "media" || !call.includes("/api/admin/media"));
      expect(observed).toEqual(example.calls);
      const declared = COMMANDS.find((command) => command.name === name)?.routes ?? [];
      for (const request of api.requests) if (request.key !== "public") expect(declared, `${name} → ${request.key}`).toContain(request.key);
      for (const request of api.requests.filter((entry) => entry.key !== "public")) {
        expect(request.headers.authorization).toBe(`Bearer ${SENTINEL}`);
        expect(request.headers["x-tower-actor"]).toBe("cli:tower-catalog@test-box.local");
        expect(request.headers["x-request-id"]).toMatch(/^[0-9a-f-]{36}$/);
        const route = request.key.startsWith("media:") ? undefined : cliRoute(request.key);
        const keyed = route === undefined ? request.key !== "media:GET /" && request.key !== "media:POST /check" : route.idempotency === "required" || (route.idempotency === "unless-dry-run" && request.query.dryRun !== "true");
        expect(Boolean(request.headers["idempotency-key"])).toBe(keyed);
      }
      expect(`${result.stdout}${result.stderr}`).not.toContain(SENTINEL);
    });
  }

  it("sends the area move and update bodies the API expects, one call each", async () => {
    const moved = fakeApi();
    const move = await runCli(["area", "move", "law", "--position", "3", "--note", "Law up", "--yes", ...P], { api: moved });
    expect(moved.requests.map((request) => [request.key, request.body])).toEqual([["POST /areas/:id/move", { position: 3, note: "Law up" }]]);
    expect(move.stdout).toContain("Moved area law to position 3; release #4 created.");
    const renamed = fakeApi();
    await runCli(["area", "update", "law", "--title", "Legal Studies", "--yes", ...P], { api: renamed });
    expect(renamed.requests.map((request) => [request.key, request.body])).toEqual([["PATCH /areas/:id", { title: "Legal Studies" }]]);
    const missing = await runCli(["area", "move", "law", "--yes", ...P], { api: fakeApi() });
    expect(missing.code).toBe(EXIT.usage);
    const zero = await runCli(["area", "move", "law", "--position", "0", "--yes", ...P], { api: fakeApi() });
    expect(zero.code).toBe(EXIT.usage);
  });

  it("sends the edition bodies the API expects", async () => {
    const created = fakeApi();
    await runCli(["edition", "create", "course-6", "--label", "SP26 Lectures", ...P], { api: created });
    expect(created.requests.at(-1)?.body).toEqual({ slug: "spring-2026", label: "Spring 2026", term: "spring", year: 2026 });
    const lesson = fakeApi({ "GET /courses/:id": () => ({ data: twoEditions() }) });
    await runCli(["lesson", "create", "course-6", "--edition", "spring-2026", "--youtube-id", "vid00000004", "--duration-seconds", "900", "--part", "labs", ...P], { api: lesson });
    expect(lesson.requests.at(-1)?.body).toEqual({ youtubeId: "vid00000004", durationSeconds: 900, part: "labs", editionId: "edition-7" });
    const ambiguous = await runCli(["lesson", "create", "course-6", "--youtube-id", "vid00000004", "--duration-seconds", "900", ...P], { api: fakeApi({ "GET /courses/:id": () => ({ data: twoEditions() }) }) });
    expect(ambiguous.code).toBe(EXIT.usage);
    expect(ambiguous.stderr).toContain("has 2 editions (spring-2026, fall-2025): pass --edition <slug>");
    const moved = fakeApi({ "GET /courses/:id": () => ({ data: twoEditions() }) });
    await runCli(["lesson", "set", "course-6", "lesson-211", "--edition", "spring-2026", ...P], { api: moved });
    expect(moved.requests.at(-1)?.body).toEqual({ editionId: "edition-7", expectedRevision: 2 });
    const reorder = fakeApi({ "GET /courses/:id": () => ({ data: twoEditions() }) });
    await runCli(["lesson", "reorder", "course-6", "--edition", "fall-2025", "--ids", "lesson-213,lesson-211,lesson-212", ...P], { api: reorder });
    expect(reorder.mutations()).toEqual(["PUT /editions/edition-6/lessons/order"]);
    const imported = fakeApi({ "GET /courses": () => ({ data: { courses: [{ id: "course-6", slug: "freud" }] } }) });
    await runCli(["import", "https://www.youtube.com/playlist?list=PLabc", "--course", "freud", "--edition", "Fall 2026", "--part", "labs", "--items", itemsFile(), ...P], { api: imported });
    expect(imported.calls()).toEqual([`GET /courses?${coursePage}`, "POST /imports", "POST /imports/import-PLabc-202610111200/draft"]);
    expect(imported.requests.at(-1)?.body).toEqual({ courseId: "course-6", edition: { slug: "fall-2026", label: "Fall 2026", term: "fall", year: 2026 }, part: "labs" });
    const mixed = await runCli(["import", "https://www.youtube.com/playlist?list=PLabc", "--course", "freud", "--edition", "Fall 2026", "--slug", "x", "--items", itemsFile(), ...P]);
    expect(mixed.code).toBe(EXIT.usage);
  });

  it("publish --batch sends every course with its revision in ONE request and prints the rollback", async () => {
    const api = fakeApi();
    const list = file("batch.txt", "# lote\nfreud\n\n");
    const result = await runCli(["publish", "--batch", list, "--note", "Lote", "--yes", ...P], { api });
    expect(result.code).toBe(0);
    expect(api.calls().filter((key) => key === "POST /courses/publish-batch")).toHaveLength(1);
    expect(api.calls()).not.toContain("POST /courses/:id/publish");
    expect(api.requests.find((request) => request.key === "POST /courses/publish-batch")?.body).toEqual({ courses: [{ id: "course-6", expectedRevision: 7 }], note: "Lote" });
    expect(result.stdout).toContain("ONE release");
    expect(result.stdout).toContain("release activate 3");
    const json = await runCli(["publish", "--batch", file("batch.json", ["course-6"]), "--note", "Lote", "--allow-orphan", "--yes", ...P], { api: fakeApi() });
    expect(json.code).toBe(0);
    for (const bad of [file("dup.txt", "freud\ncourse-6\n"), file("empty.txt", "# nothing\n"), file("unknown.txt", "nope\n"), file("twice.txt", "freud\nfreud\n")]) {
      const refused = fakeApi();
      expect((await runCli(["publish", "--batch", bad, "--note", "x", "--yes", ...P], { api: refused })).code, bad).toBe(EXIT.usage);
      expect(refused.calls(), bad).not.toContain("POST /courses/publish-batch");
    }
    expect((await runCli(["publish", "course-6", "--batch", list, "--note", "x", "--yes", ...P], { api: fakeApi() })).code).toBe(EXIT.usage);
  });

  it("sends the bodies the API expects", async () => {
    const api = fakeApi();
    await runCli(["publish", "course-6", "--note", "Go", "--allow-orphan", "--yes", ...P], { api });
    expect(api.requests.find((request) => request.key === "POST /courses/:id/publish")?.body).toEqual({ expectedRevision: 7, note: "Go", allowOrphan: true });
    const set = fakeApi();
    await runCli(["course", "set", "course-6", "--title", "Freud!", "--unset", "attribution-text", ...P], { api: set });
    expect(set.requests.at(-1)?.body).toEqual({ title: "Freud!", attributionText: null, expectedRevision: 7 });
    const imported = fakeApi();
    await runCli(EXAMPLES.import?.argv().concat(P) ?? [], { api: imported });
    expect(imported.requests[1]?.body).toEqual({ slug: "freud-2", newAuthor: { slug: "sigmund-freud", name: "Sigmund Freud", monogram: "SF", kind: "person" }, exclude: ["vid00000002"] });
    expect(imported.requests[0]?.body).toMatchObject({ playlistUrl: "https://www.youtube.com/playlist?list=PLabc", playlistTitle: "Freud lectures" });
  });
});

describe("tower-catalog arguments", () => {
  const usage = [
    [[], "no command"], [["nope"], "unknown command"], [["course", "list"], "missing --target"], [["course", "list", "--target", "dev"], "unknown target"],
    [["course", "list", "--target", "preview", "--bogus"], "unknown option"], [["course", "get", ...P], "missing positional"], [["course", "get", "a", "b", ...P], "extra positional"],
    [["publish", "course-6", ...P], "--note required"], [["course", "create", "--slug", "Bad Slug", "--author-id", "author-3", "--title", "x", ...P], "schema"],
    [["lesson", "create", "course-6", "--youtube-id", "vid00000004", "--duration-seconds", "ten", ...P], "number"], [["lesson", "set", "course-6", "lesson-1", "--visible", "yes", ...P], "boolean"],
    [["course", "set", "course-6", ...P], "nothing to change"], [["course", "set", "course-6", "--unset", "title", ...P], "not nullable"], [["status", "course-6", "published", ...P], "status"],
    [["preview-url", "course-6", "--ttl-minutes", "90", ...P], "ttl"], [["course", "list", "--target", "preview", "--target", "prod"], "twice"], [["release", "activate", "x", ...P], "release number"],
    [["import", "https://www.youtube.com/playlist?list=PLabc", "--slug", "x", "--author", "author-1", ...P], "P6"], [["check", "course-6", ...P], "--embeds required"],
    [["license", "set", "cc-by", ...P], "refusal"], [["covers", "course-6", "--dir", "/nonexistent", ...P], "dir"], [["covers", "course-6", "--dir", "/tmp", "--target", "staging"], "staging"],
  ] as const;
  for (const [argv, why] of usage) {
    it(`exits 2 without sending anything: ${why}`, async () => {
      const api = fakeApi();
      const result = await runCli(argv, { api });
      expect(result.code, result.stderr).toBe(EXIT.usage);
      expect(api.mutations()).toEqual([]);
    });
  }

  it("says where yt-dlp extraction lives", async () => {
    const result = await runCli(["import", "https://www.youtube.com/playlist?list=PLabc", "--slug", "x", "--author", "author-1", ...P]);
    expect(result.stderr).toContain("yt-dlp extraction arrives in P6; pass --items <file.json>");
  });

  it("prints help without credentials and lists every command", async () => {
    const result = await runCli(["--help"], { deps: { transport: () => { throw new Error("no transport for help"); } } });
    expect(result.code).toBe(0);
    for (const command of COMMANDS) expect(result.stdout).toContain(command.name);
    const one = await runCli(["publish", "--help"]);
    expect(one.stdout).toContain("--allow-orphan");
  });

  it("derives the actor from the hostname within the API's pattern", () => {
    expect(actorFor("Box_01.Example.COM")).toBe("cli:tower-catalog@box-01.example.com");
    expect(actorFor("x".repeat(100))).toHaveLength(64);
  });
});

describe("tower-catalog targets and secrets", () => {
  it("accepts only https origins of openuniversity.si and AWS Lambda function URLs, never thetower.si (it belongs to The Tower)", () => {
    const origin = (url: string) => targetOrigin("preview", { TOWER_MEDIA_URL_PREVIEW: url });
    expect(origin("https://openuniversity.si")).toBe("https://openuniversity.si");
    expect(origin("https://openuniversity.si/")).toBe("https://openuniversity.si");
    expect(origin("https://tower0preview.lambda-url.eu-central-1.on.aws")).toBe("https://tower0preview.lambda-url.eu-central-1.on.aws");
    for (const bad of ["http://openuniversity.si", "https://www.openuniversity.si", "https://theopenuniversity.si", "https://evil.openuniversity.si", "https://openuniversity.si.evil.com", "https://evil-openuniversity.si", "http://www.thetower.si", "https://www.thetower.si", "https://thetower.si", "https://thetower.si/", "https://media.thetower.si", "https://torre-git-rewrite-v1-a-torre.example.invalid", "https://evil.lambda-url.us-east-1.on.aws.evil.com", "https://evil.com", "https://thetower.si.evil.com", "https://openuniversity.si/api", "https://www.thetower.si/api", "https://user:pw@openuniversity.si", "not a url"]) {
      expect(() => origin(bad), bad).toThrow(/TOWER_MEDIA_URL_PREVIEW/);
    }
    expect(() => targetOrigin("staging", {})).toThrow("TOWER_MEDIA_URL_STAGING is not set");
    expect(ALLOWED_HOSTS).toHaveLength(2);
  });

  it("reads one key per target from the descriptor and names a missing one without values", () => {
    expect(parseCredentials(`secret.prod=p-key\nsecret.preview=a=b\nbypass=\n`)).toEqual({ secrets: { prod: "p-key", preview: "a=b" } });
    // A wrapper installed before per-target keys sends one line: it serves every target, like the fallback.
    expect(parseCredentials(`secret=${SENTINEL}\nbypass=ignored\n`)).toEqual({ secrets: { prod: SENTINEL, preview: SENTINEL } });
    expect(() => parseCredentials("bypass=x\n")).toThrow("TOWER_ADMIN_SECRET_PROD and TOWER_ADMIN_SECRET_PREVIEW are not set in admin-media.env (nor the fallback TOWER_ADMIN_MEDIA_SECRET).");
    expect(() => parseCredentials("secret.prod=p\nsecret.preview=\n")).toThrow("TOWER_ADMIN_SECRET_PREVIEW is not set in admin-media.env.");
    expect(() => parseCredentials("secret.preview=v\n")).toThrow("TOWER_ADMIN_SECRET_PROD is not set in admin-media.env.");
    const credentials = parseCredentials("secret.prod=p-key\nsecret.preview=v-key\n");
    expect([secretFor(credentials, "prod"), secretFor(credentials, "preview"), secretFor(credentials, "staging")]).toEqual(["p-key", "v-key", "v-key"]);
  });

  it("never prints the secret, even when the API or the network echo it", async () => {
    const echo: Handler = (request) => ({ status: 409, error: { code: "state_conflict", message: `echo ${request.headers.authorization ?? ""}`, details: { authorization: request.headers.authorization, note: `token=${SENTINEL}` } } });
    const outputs: string[] = [];
    for (const json of [false, true]) {
      for (const api of [fakeApi({ "GET /courses/:id": echo }), fakeApi({ "GET /courses/:id": () => "network" })]) {
        const result = await runCli(["review", "course-6", ...P, ...(json ? ["--json"] : [])], { api });
        expect(result.code).not.toBe(0);
        outputs.push(result.stdout, result.stderr);
      }
    }
    const success = await runCli(["course", "get", "course-6", "--json", ...P], { api: fakeApi({ "GET /courses/:id": () => ({ data: { ...courseDetail(), leaked: SENTINEL, secretValue: "x" } }) }) });
    outputs.push(success.stdout, success.stderr);
    const all = outputs.join("\n");
    expect(all).not.toContain(SENTINEL);
    expect(all).toContain("[redacted]");
    expect(redact({ Authorization: "Bearer abc", nested: [{ url: "/p?token=abc&to=/" }], clientSecret: "x" })).toEqual({ Authorization: "[redacted]", nested: [{ url: "/p?token=[redacted]&to=/" }], clientSecret: "[redacted]" });
    expect(scrub(`a ${SENTINEL} b`, [SENTINEL])).toBe("a [redacted] b");
  });

  it("sends only the Bearer and the request metadata, on every target", async () => {
    for (const target of ["prod", "preview"] as const) {
      const api = fakeApi({}, { secrets: { prod: SENTINEL, preview: SENTINEL } }, target);
      await runCli(["doctor", "--target", target], { api });
      expect(Object.keys(api.requests[0]?.headers ?? {}).filter((name) => name.includes("bypass"))).toEqual([]);
    }
  });

  it("prints a preview URL only to stdout, whole, and nowhere else", async () => {
    const result = await runCli(["preview-url", "course-6", ...P]);
    expect(result.stdout).toBe(`${ORIGIN}/api/catalog/preview?token=v1.preview-token-abc&to=%2Fc%2Ffreud\n`);
    expect(result.stderr).not.toContain("preview-token-abc");
  });
});

describe("tower-catalog confirmations", () => {
  it("refuses any prod change outside a terminal without --yes, before sending it", async () => {
    for (const argv of [["status", "course-6", "review"], ["course", "create", "--slug", "x", "--author-id", "author-3", "--title", "X"], ["redirect", "add", "--from", "/c/a", "--to", "/c/freud"]]) {
      const api = fakeApi({}, undefined, "prod");
      const result = await runCli([...argv, "--target", "prod"], { api });
      expect(result.code, argv.join(" ")).toBe(EXIT.usage);
      expect(result.stderr).toContain("pass --yes outside a terminal");
      expect(api.mutations()).toEqual([]);
    }
  });

  it("asks y/N in a terminal on prod: n aborts, y sends", async () => {
    const no = fakeApi({}, undefined, "prod");
    const refused = await runCli(["status", "course-6", "review", "--target", "prod"], { api: no, answers: ["n"] });
    expect([refused.code, refused.prompts]).toEqual([EXIT.usage, ["Move course-6 from review to review on PROD? [y/N] "]]);
    expect(no.mutations()).toEqual([]);
    const yes = fakeApi({}, undefined, "prod");
    expect((await runCli(["status", "course-6", "review", "--target", "prod"], { api: yes, answers: ["y"] })).code).toBe(0);
    expect(yes.mutations()).toEqual(["POST /courses/course-6/status"]);
    const flagged = fakeApi({}, undefined, "prod");
    expect((await runCli(["status", "course-6", "review", "--target", "prod", "--yes"], { api: flagged })).code).toBe(0);
  });

  it("asks for publish, unpublish, activate, approve, home set and confirmed deletes on every target", async () => {
    for (const name of ["publish", "unpublish", "release activate", "approve", "home set", "course delete", "author delete"]) {
      const argv = (EXAMPLES[name]?.argv() ?? []).filter((arg) => arg !== "--yes");
      const api = fakeApi();
      const result = await runCli([...argv, ...P], { api });
      expect(result.code, name).toBe(EXIT.usage);
      expect(api.mutations(), name).toEqual([]);
    }
    const plain = fakeApi();
    expect((await runCli(["status", "course-6", "review", ...P], { api: plain })).code).toBe(0);
  });

  it("guards the client itself: a change that needs confirmation is refused if a command forgot to ask", async () => {
    const { ApiClient } = await import("./lib/catalog-cli/client.ts");
    const { Output } = await import("./lib/catalog-cli/io.ts");
    const api = fakeApi({}, undefined, "prod");
    const client = new ApiClient({ origin: "https://openuniversity.si", target: "prod", transport: api.transport, actor: "cli:tower-catalog@t", uuid: () => "id", sleep: () => Promise.resolve(), dryRun: false, out: new Output({ stdout: () => undefined, stderr: () => undefined, prompt: null }, false, []), fixedKey: undefined, intent: () => ({ command: "x", args: {}, files: {}, window: "w" }) });
    await expect(client.call("POST /courses/:id/status", { params: { id: "course-6" }, body: { to: "review", expectedRevision: 1 } })).rejects.toThrow("without a confirmation");
    expect(api.requests).toEqual([]);
  });
});

describe("tower-catalog --dry-run", () => {
  it("runs the reads, prints the change with its redacted body and sends nothing", async () => {
    const api = fakeApi();
    const result = await runCli(["publish", "course-6", "--note", "Go", "--dry-run", ...P], { api });
    expect(result.code).toBe(0);
    expect(api.calls()).toEqual(["GET /courses/course-6", "GET /releases", "POST /releases?dryRun=true"]);
    expect(result.stderr).toContain("DRY-RUN: POST /api/admin/catalog/courses/course-6/publish (Idempotency-Key tc-publish-");
    expect(result.stderr).toContain('"expectedRevision": 7');
    expect(result.stderr).toContain("DRY-RUN: not sent; nothing changed.");
    const purge = fakeApi();
    expect((await runCli(["course", "delete", "course-6", "--mode", "purge", "--confirm", "--dry-run", ...P], { api: purge })).code).toBe(0);
    expect(purge.mutations()).toEqual([]);
    const covers = await runCli(["covers", "course-6", "--dir", coversDir(), "--dry-run", ...P]);
    expect(covers.stdout).toContain("hero_present");
    expect(covers.stdout).toContain("hero_desktop_16x9/og");
    expect(covers.stderr).toContain("DRY-RUN: nothing uploaded.");
  });

  it("covers uploads run --parallel at a time and report every failure", async () => {
    const gate = (failStill: boolean) => {
      let running = 0;
      let peak = 0;
      const api = fakeApi(failStill ? { "media:POST /attach": (request) => (request.body as { kind?: string }).kind === "still_16x9" ? { status: 400, error: { code: "invalid", message: "still refused" } } : { data: { sha256: "a".repeat(64), url: "https://media.openuniversity.si/m/a.webp" } } } : {});
      const inner = api.transport;
      const transport: typeof inner = async (request) => {
        if (request.url.includes("/api/admin/media")) { running += 1; peak = Math.max(peak, running); await new Promise((resolve) => setTimeout(resolve, 15)); running -= 1; }
        return inner(request);
      };
      return { api, transport, peak: () => peak, attaches: () => api.requests.filter((request) => request.key === "media:POST /attach").length };
    };
    const ok = gate(false);
    const uploaded = await runCli(["covers", "course-6", "--dir", coversDir(), "--parallel", "3", "--yes", ...P], { api: ok.api, deps: { transport: () => ok.transport } });
    expect(uploaded.code, uploaded.stderr).toBe(0);
    expect(ok.peak()).toBe(3);
    expect(ok.attaches()).toBe(7);
    const failed = gate(true);
    const refused = await runCli(["covers", "course-6", "--dir", coversDir(), "--parallel", "2", "--yes", ...P], { api: failed.api, deps: { transport: () => failed.transport } });
    expect(refused.code).toBe(EXIT.api);
    expect(refused.stderr).toContain("still");
    expect((await runCli(["covers", "course-6", "--dir", coversDir(), "--parallel", "0", "--yes", ...P])).code).toBe(EXIT.usage);
    const wide = gate(false);
    expect((await runCli(["covers", "course-6", "--dir", coversDir(), "--yes", ...P], { api: wide.api, deps: { transport: () => wide.transport } })).code).toBe(0);
    expect(wide.peak()).toBe(7);
  });

  it("deletes are dry-runs unless --confirm", async () => {
    for (const argv of [["course", "delete", "course-6", "--mode", "archive"], ["lesson", "delete", "course-6", "lesson-211"], ["author", "delete", "author-3"], ["redirect", "rm", "--from", "/c/old"]]) {
      const api = fakeApi();
      const result = await runCli([...argv, ...P], { api });
      expect(result.code).toBe(0);
      expect(result.stdout).toContain("Re-run with --confirm");
      expect(api.mutations()).toEqual([]);
    }
  });
});

describe("tower-catalog idempotency keys", () => {
  const keyOf = async (argv: string[]) => {
    const api = fakeApi();
    await runCli([...argv, ...P], { api });
    return api.requests.find((request) => request.headers["idempotency-key"])?.headers["idempotency-key"];
  };

  it("are deterministic per intent: same command, same key; another file, nonce or day, another key", async () => {
    const author = ["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", "--kind", "person"];
    const first = await keyOf(author);
    expect(first).toMatch(/^tc-author\.create-[0-9a-f]{40}$/);
    expect(await keyOf(author)).toBe(first);
    expect(await keyOf([...author, "--json"])).toBe(first);
    expect(await keyOf([...author.slice(0, 2), "--name", "Carl Jung", "--slug", "jung", "--monogram", "CJ", "--kind", "person"])).toBe(first);
    expect(await keyOf([...author, "--idem-nonce", "retry-2"])).not.toBe(first);
    expect(await keyOf(["author", "create", "--slug", "jung2", "--name", "Carl Jung", "--monogram", "CJ", "--kind", "person"])).not.toBe(first);
    const items = file("items.json", { items: [{ id: "vid00000001", title: "Lecture 1", duration: 1500 }] });
    const importArgs = (path: string) => ["import", "https://www.youtube.com/playlist?list=PLabc", "--slug", "x", "--author", "author-1", "--items", path];
    const a = await keyOf(importArgs(items));
    expect(await keyOf(importArgs(items))).toBe(a);
    writeFileSync(items, JSON.stringify({ items: [{ id: "vid00000001", title: "Lecture 1 (edited)", duration: 1500 }] }));
    expect(await keyOf(importArgs(items))).not.toBe(a);
    const intent = { command: "author create", args: {}, files: {}, window: NOW.toISOString().slice(0, 10) };
    const request = { route: "POST /authors", params: {}, query: {}, body: { slug: "x" }, state: null };
    expect(idempotencyKey(intent, request)).not.toBe(idempotencyKey({ ...intent, window: "2026-10-12" }, request));
    expect(await keyOf([...author, "--idempotency-key", "fixed-key-1"])).toBe("fixed-key-1");
  });

  it("include what was read before an activation, so a later identical command is a new intent", async () => {
    const activate = fakeApi();
    await runCli(["release", "activate", "2", "--yes", ...P], { api: activate });
    const again = fakeApi();
    again.state.active = 4;
    await runCli(["release", "activate", "2", "--yes", ...P], { api: again });
    const key = (api: ReturnType<typeof fakeApi>) => api.requests.find((request) => request.key === "POST /releases/:n/activate")?.headers["idempotency-key"];
    expect(key(again)).not.toBe(key(activate));
  });

  it("report a replayed answer", async () => {
    const result = await runCli(["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", ...P, "--kind", "person"], { api: fakeApi({ "POST /authors": () => ({ status: 201, data: { author: { id: "author-9", slug: "jung" } }, headers: { "idempotent-replay": "true" } }) }) });
    expect(result.stderr).toContain("Replayed the stored answer of Idempotency-Key tc-author.create-");
  });
});

describe("tower-catalog errors and exit codes", () => {
  const fail = (status: number, code: string, details?: unknown): Handler => () => ({ status, error: { code, message: `${code} happened`, ...(details === undefined ? {} : { details }) } });
  const cases: [number, string, number, unknown?][] = [
    [409, "revision_conflict", EXIT.conflict, { currentRevision: 9 }], [409, "slug_taken", EXIT.conflict], [412, "preconditions_failed", EXIT.preconditions, { failed: [{ rule: "covers.active", entity: "course:course-6", message: "Cover hero_present is missing." }, { rule: "texts.present", entity: "lesson:lesson-212", message: "displayTitle is missing." }, { rule: "rights.status", entity: "course:course-6", message: "Rights are unverified." }] }],
    [422, "unprocessable", EXIT.unprocessable, [{ index: 0, issues: [{ rule: "texts.limit" }] }]], [422, "idempotency_mismatch", EXIT.unprocessable], [401, "unauthorized", EXIT.access], [429, "rate_limited", EXIT.access], [503, "unconfigured", EXIT.access],
    [404, "not_found", EXIT.api], [400, "invalid", EXIT.api], [502, "upstream_failed", EXIT.api],
  ];
  for (const [status, code, exit, details] of cases) {
    it(`${String(status)} ${code} → exit ${String(exit)} with the request id and every detail`, async () => {
      const result = await runCli(["status", "course-6", "review", ...P], { api: fakeApi({ "POST /courses/:id/status": fail(status, code, details) }) });
      expect(result.code).toBe(exit);
      expect(result.stderr).toContain(`HTTP ${String(status)} ${code}, requestId 00000000-0000-4000-8000-000000000002`);
      if (code === "preconditions_failed") {
        expect(result.stderr).toContain("Unmet preconditions (3):\n  - covers.active course:course-6: Cover hero_present is missing.\n  - texts.present lesson:lesson-212: displayTitle is missing.\n  - rights.status course:course-6: Rights are unverified.");
      }
      if (code === "revision_conflict") expect(result.stderr).toContain("Current revision: 9.");
    });
  }

  it("network failures and timeouts exit 7 with the request id; --json prints the error envelope", async () => {
    const network = await runCli(["status", "course-6", "review", ...P], { api: fakeApi({ "POST /courses/:id/status": () => "network" }) });
    expect(network.code).toBe(EXIT.network);
    expect(network.stderr).toMatch(/POST \/api\/admin\/catalog\/courses\/course-6\/status: TypeError \(requestId 0{8}-0000-4000-8000-0{11}2\)/);
    const json = await runCli(["status", "course-6", "review", "--json", ...P], { api: fakeApi({ "POST /courses/:id/status": fail(412, "preconditions_failed", { failed: [] }) }) });
    expect(JSON.parse(json.stdout)).toEqual({ ok: false, error: { code: "preconditions_failed", message: "preconditions_failed happened", details: { failed: [] } }, requestId: "00000000-0000-4000-8000-000000000002" });
    const notJson = await runCli(["doctor", ...P], { api: fakeApi({ "GET /doctor": () => ({ status: 401, raw: "<html>Login required</html>" }) }) });
    expect([notJson.code, notJson.stderr.includes("without the admin envelope")]).toEqual([EXIT.access, true]);
  });

  it("D-035: retries only a transport failure", async () => {
    const flaky = (times: number, reply: "network" | 502): Handler => (_request, call) => (call <= times ? (reply === "network" ? "network" : { status: 502, error: { code: "upstream_failed", message: "db" } }) : { data: courseDetail() });
    const read = fakeApi({ "GET /courses/:id": flaky(2, "network") });
    expect((await runCli(["review", "course-6", ...P], { api: read })).code).toBe(0);
    expect(read.calls()).toEqual(["GET /courses/course-6", "GET /courses/course-6", "GET /courses/course-6"]);
    const refused = fakeApi({ "GET /courses/:id": flaky(1, 502) });
    expect((await runCli(["review", "course-6", ...P], { api: refused })).code).toBe(EXIT.api);
    expect(refused.calls()).toHaveLength(1);
    const invalid = fakeApi({ "POST /authors": () => ({ status: 400, error: { code: "invalid", message: "no" } }) });
    expect((await runCli(["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", ...P, "--kind", "person"], { api: invalid })).code).toBe(EXIT.api);
    expect(invalid.requests).toHaveLength(1);
    const keyed = fakeApi({ "POST /authors": (_request, call) => (call === 1 ? "network" : { status: 201, data: { author: { id: "author-9", slug: "jung" } } }) });
    expect((await runCli(["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", ...P, "--kind", "person"], { api: keyed })).code).toBe(0);
    expect(new Set(keyed.requests.map((request) => request.headers["idempotency-key"])).size).toBe(1);
    expect(keyed.requests).toHaveLength(2);
    const purge = fakeApi({ "DELETE /courses/:id": (request) => (request.query.confirm === "true" ? "network" : { data: { dryRun: true, report: {} } }) });
    expect((await runCli(["course", "delete", "course-6", "--mode", "purge", "--confirm", "--yes", ...P], { api: purge })).code).toBe(EXIT.network);
    expect(purge.mutations()).toEqual(["DELETE /courses/course-6?mode=purge&confirm=true&expectedRevision=7"]);
    const patch = fakeApi({ "PATCH /courses/:id": () => "network" });
    expect((await runCli(["course", "set", "course-6", "--title", "X", ...P], { api: patch })).code).toBe(EXIT.network);
    expect(patch.mutations()).toHaveLength(1);
  });

  it("retries 429 for reads and mutations with Retry-After and jitter, preserving idempotency, then stops", async () => {
    const sleeps: number[] = [];
    const api = fakeApi({ "POST /authors": (_request, call) => call < 3 ? { status: 429, headers: { "Retry-After": "2" }, raw: "edge limit" } : { data: { author: { id: "author-9", slug: "jung" } } } });
    const result = await runCli(["author", "create", "--slug", "jung", "--name", "Carl Jung", "--monogram", "CJ", ...P, "--kind", "person"], { api, deps: { sleep: (ms) => { sleeps.push(ms); return Promise.resolve(); } } });
    expect(result.code).toBe(0);
    expect(sleeps[0]).toBeGreaterThanOrEqual(2500);
    expect(sleeps[1]).toBeGreaterThanOrEqual(3000);
    expect(new Set(api.requests.map((request) => request.headers["idempotency-key"])).size).toBe(1);
    const denied = fakeApi({ "GET /courses/:id": () => ({ status: 429, error: { code: "rate_limited", message: "quota" }, headers: { "Retry-After": "1" } }) });
    expect((await runCli(["course", "get", "course-6", ...P], { api: denied })).code).toBe(EXIT.access);
    expect(denied.requests).toHaveLength(5);
  });

  it("retries a PATCH once after a revision conflict only when nobody touched its fields", async () => {
    const conflict: Handler = (_request, call) => (call === 1 ? { status: 409, error: { code: "revision_conflict", message: "stale", details: { currentRevision: 8 } } } : { data: { course: { ...courseDetail().course, revision: 9 } } });
    let reads = 0;
    const safe = fakeApi({ "PATCH /courses/:id": conflict, "GET /courses/:id": () => { reads += 1; return { data: courseDetail({ revision: 6 + reads }) }; } });
    expect((await runCli(["course", "set", "course-6", "--title", "New", ...P], { api: safe })).code).toBe(0);
    expect(safe.requests.filter((request) => request.key === "PATCH /courses/:id").map((request) => (request.body as { expectedRevision: number }).expectedRevision)).toEqual([7, 8]);
    let readsB = 0;
    const touched = fakeApi({ "PATCH /courses/:id": conflict, "GET /courses/:id": () => { readsB += 1; const detail = courseDetail({ revision: 6 + readsB }); return { data: readsB > 1 ? { ...detail, course: { ...detail.course, title: "Someone else" } } : detail }; } });
    const result = await runCli(["course", "set", "course-6", "--title", "New", ...P], { api: touched });
    expect(result.code).toBe(EXIT.conflict);
    expect(result.stderr).toContain("someone else changed title");
    expect(touched.mutations()).toHaveLength(1);
    const status = fakeApi({ "POST /courses/:id/status": () => ({ status: 409, error: { code: "revision_conflict", message: "stale", details: { currentRevision: 8 } } }) });
    expect((await runCli(["status", "course-6", "review", ...P], { api: status })).code).toBe(EXIT.conflict);
    expect(status.mutations()).toHaveLength(1);
  });
});

describe("tower-catalog approve", () => {
  it("sends exactly the hashes it read and shows them first", async () => {
    const api = fakeApi();
    const result = await runCli(["approve", "course-6", "--by", "Daniel", "--yes", ...P], { api });
    const body = api.requests.find((request) => request.key === "POST /texts/approve")?.body;
    expect(body).toEqual({ approvedBy: "Daniel", items: [
      { entityKind: "course", entityId: "course-6", field: "subtitle", sha256: sha256Hex("On dreams") },
      { entityKind: "course", entityId: "course-6", field: "level", sha256: sha256Hex("Introductory") },
      { entityKind: "lesson", entityId: "lesson-212", field: "displayTitle", sha256: sha256Hex("Lecture 2") },
      { entityKind: "lesson", entityId: "lesson-213", field: "displayTitle", sha256: sha256Hex("Lecture 3") },
    ] });
    expect(result.stdout).toContain(`course:course-6.subtitle ${sha256Hex("On dreams").slice(0, 12)} «On dreams»`);
    const only = fakeApi();
    await runCli(["approve", "course-6", "--by", "Daniel", "--fields", "subtitle,lesson-213.displayTitle", "--yes", ...P], { api: only });
    expect((only.requests.at(-1)?.body as { items: { field: string; entityId: string }[] }).items.map((item) => `${item.entityId}.${item.field}`)).toEqual(["course-6.subtitle", "lesson-213.displayTitle"]);
  });

  it("approves nothing and names the changed fields when a text changed (409)", async () => {
    let reads = 0;
    const api = fakeApi({
      "GET /courses/:id": () => { reads += 1; return { data: courseDetail({ subtitle: reads === 1 ? "On dreams" : "On dreams, edited" }) }; },
      "POST /texts/approve": () => ({ status: 409, error: { code: "state_conflict", message: "A text changed since its hash was reviewed." } }),
    });
    const result = await runCli(["approve", "course-6", "--by", "Daniel", "--yes", ...P], { api });
    expect(result.code).toBe(EXIT.conflict);
    expect(result.stderr).toContain("Nothing was approved: changed since you read them: course:course-6.subtitle");
    expect(api.mutations()).toEqual(["POST /texts/approve"]);
  });

  it("requires --by and asks outside --yes", async () => {
    expect((await runCli(["approve", "course-6", ...P])).code).toBe(EXIT.usage);
    const api = fakeApi();
    expect((await runCli(["approve", "course-6", "--by", "Daniel", ...P], { api })).code).toBe(EXIT.usage);
    expect(api.mutations()).toEqual([]);
  });
});

describe("tower-catalog lesson set --slug", () => {
  const plan = { created: { from: "/c/freud/lesson-3", to: "/c/freud/dreams" }, flattened: [{ from: "/c/freud/old", before: "/c/freud/lesson-3", after: "/c/freud/dreams" }], removed: [] };
  const patch: Handler = (request) => (request.query.dryRun === "true"
    ? { data: { dryRun: true, lesson: { id: "lesson-213", slug: "lesson-3", revision: 2 }, changes: { slug: { before: "lesson-3", after: "dreams" } }, redirects: plan, noop: false } }
    : { data: { lesson: { id: "lesson-213", slug: "dreams", revision: 3 }, courseRevision: 8, redirects: plan } });

  it("takes the lesson alone (the course is looked up), or through the alias lesson update, and prints the redirects", async () => {
    for (const verb of ["set", "update"]) {
      const api = fakeApi({ "PATCH /lessons/:id": patch });
      const result = await runCli(["lesson", verb, "lesson-213", "--slug", "dreams", ...P], { api });
      expect(result.code, result.stderr).toBe(EXIT.ok);
      expect(api.calls()).toEqual([`GET /courses?${coursePage}`, "GET /courses/course-6", "GET /courses/course-6", "PATCH /lessons/lesson-213"]);
      expect(api.requests.at(-1)?.body).toEqual({ slug: "dreams", expectedRevision: courseDetail().lessons.find((lesson) => lesson.id === "lesson-213")?.revision });
      expect(result.stdout).toContain("redirect /c/freud/lesson-3 → /c/freud/dreams (308 from the next release)");
      expect(result.stdout).toContain("flattened /c/freud/old → /c/freud/dreams (was → /c/freud/lesson-3)");
    }
    const missing = await runCli(["lesson", "set", "lesson-999", "--slug", "dreams", ...P]);
    expect([missing.code, missing.stderr]).toEqual([EXIT.usage, "tower-catalog: No lesson lesson-999 in any course.\n"]);
  });

  it("--dry-run asks the API for its report (no confirmation, nothing written), even on prod", async () => {
    const api = fakeApi({ "PATCH /lessons/:id": patch }, undefined, "prod");
    const result = await runCli(["lesson", "set", "course-6", "lesson-213", "--slug", "dreams", "--dry-run", "--target", "prod"], { api });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(api.calls()).toEqual(["GET /courses/course-6", "PATCH /lessons/lesson-213?dryRun=true"]);
    expect(result.stdout).toContain("Dry-run for lesson-213 (nothing changed):");
    expect(result.stdout).toContain("redirect /c/freud/lesson-3 → /c/freud/dreams");
  });

  it("asks y/N on prod, needs --yes without a terminal, and maps 409 slug_taken to the conflict exit", async () => {
    const refused = fakeApi({ "PATCH /lessons/:id": patch }, undefined, "prod");
    expect((await runCli(["lesson", "set", "course-6", "lesson-213", "--slug", "dreams", "--target", "prod"], { api: refused })).code).toBe(EXIT.usage);
    expect(refused.mutations()).toEqual([]);
    const asked = fakeApi({ "PATCH /lessons/:id": patch }, undefined, "prod");
    expect((await runCli(["lesson", "set", "course-6", "lesson-213", "--slug", "dreams", "--target", "prod"], { api: asked, answers: ["y"] })).code).toBe(EXIT.ok);
    expect(asked.mutations()).toEqual(["PATCH /lessons/lesson-213"]);
    const taken = fakeApi({ "PATCH /lessons/:id": () => ({ status: 409, error: { code: "slug_taken", message: "The lesson slug dreams is taken in course-6." } }) });
    expect((await runCli(["lesson", "set", "course-6", "lesson-213", "--slug", "dreams", ...P], { api: taken })).code).toBe(EXIT.conflict);
  });
});

describe("tower-catalog lesson reslug", () => {
  const tables: Handler = () => ({ data: { activeRelease: null, tables: importedTables() } });
  const bodies = (api: ReturnType<typeof fakeApi>) => api.requests.filter((request) => request.key === "PUT /lessons/slugs").map((request) => request.body);

  it("prints old → new with the reason and, without --apply, only asks the API's dry-run (no confirmation, even on prod)", async () => {
    const api = fakeApi({ "GET /tables": tables }, undefined, "prod");
    const result = await runCli(["lesson", "reslug", "--all-imported", "--target", "prod"], { api });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(result.stdout).toContain("cmu-db  lesson-300  01-relational-model-algebra-cmu-intro-to-database-systems → lecture-01-relational-model-algebra  rule");
    expect(result.stdout).toContain("fall-2024-storage → lecture-03-database-storage-files-pages");
    expect(result.stdout).not.toContain("lesson-301 ");
    expect(result.stdout).toContain("2 slug(s) change in 1 of 1 course(s): 2 rule, 0 disambiguated, 1 kept, 0 excluded, 0 legacy.");
    expect(result.stdout).toContain("Nothing changed. Re-run with --apply");
    expect(bodies(api)).toEqual([{ courseId: "course-30", expectedRevision: 7, dryRun: true, changes: [
      { lessonId: "lesson-300", slug: "lecture-01-relational-model-algebra" }, { lessonId: "lesson-302", slug: "lecture-03-database-storage-files-pages" },
    ] }]);
    expect(api.requests.find((request) => request.key === "PUT /lessons/slugs")?.headers["idempotency-key"]).toBeTruthy();
  });

  it("--apply sends one batch per course; prod asks y/N and needs --yes without a terminal", async () => {
    const refused = fakeApi({ "GET /tables": tables }, undefined, "prod");
    expect((await runCli(["lesson", "reslug", "cmu-db", "--apply", "--target", "prod"], { api: refused })).code).toBe(EXIT.usage);
    expect(refused.mutations()).toEqual([]);
    const api = fakeApi({ "GET /tables": tables }, undefined, "prod");
    const result = await runCli(["lesson", "reslug", "cmu-db", "--apply", "--yes", "--target", "prod"], { api });
    expect(result.code, result.stderr).toBe(EXIT.ok);
    expect(api.mutations()).toEqual(["PUT /lessons/slugs"]);
    expect(bodies(api)[0]).not.toHaveProperty("dryRun");
    expect(result.stdout).toContain("cmu-db: 2 slug(s), 2 redirect(s) created, 0 flattened, 0 removed, 0 old path(s) reused; course revision 8.");
  });

  it("--exclude keeps those slugs; legacy courses never change; bad combinations send nothing", async () => {
    const api = fakeApi({ "GET /tables": tables });
    const result = await runCli(["lesson", "reslug", "course-30", "--exclude", "lesson-302", ...P], { api });
    expect(result.stdout).toContain("1 slug(s) change in 1 of 1 course(s): 1 rule, 0 disambiguated, 1 kept, 1 excluded, 0 legacy.");
    expect(bodies(api)).toEqual([expect.objectContaining({ changes: [{ lessonId: "lesson-300", slug: "lecture-01-relational-model-algebra" }] })]);
    const legacy = fakeApi({ "GET /tables": tables });
    const kept = await runCli(["lesson", "reslug", "fixture-course-2", "--apply", ...P], { api: legacy });
    expect(kept.stdout).toMatch(/0 slug\(s\) change in 0 of 1 course\(s\): 0 rule, 0 disambiguated, 0 kept, 0 excluded, \d+ legacy\./);
    expect(legacy.mutations()).toEqual([]);
    for (const argv of [["--all-imported", "cmu-db"], [], ["cmu-db", "--apply", "--dry-run"], ["cmu-db", "--exclude", "lesson-1"], ["nope"]]) {
      const bad = fakeApi({ "GET /tables": tables });
      expect((await runCli(["lesson", "reslug", ...argv, ...P], { api: bad })).code, argv.join(" ")).toBe(EXIT.usage);
      expect(bad.mutations()).toEqual([]);
    }
  });
});

describe("tower-catalog lesson reorder", () => {
  const reorder = async (...extra: string[]) => {
    const api = fakeApi();
    const result = await runCli(["lesson", "reorder", "course-6", ...extra, ...P], { api });
    return { result, api };
  };
  it("sends the complete permutation", async () => {
    const { api } = await reorder("--ids", "lesson-213,lesson-211,lesson-212");
    expect(api.requests.at(-1)?.body).toEqual({ lessonIds: ["lesson-213", "lesson-211", "lesson-212"], expectedRevision: 7 });
    const moved = await reorder("--move", "lesson-211", "--to", "3");
    expect(moved.api.requests.at(-1)?.body).toEqual({ lessonIds: ["lesson-212", "lesson-213", "lesson-211"], expectedRevision: 7 });
    const fromFile = await reorder("--file", file("ids.json", ["lesson-212", "lesson-211", "lesson-213"]));
    expect(fromFile.api.mutations()).toEqual(["PUT /courses/course-6/lessons/order"]);
  });
  it("refuses a missing, unknown or repeated lesson with the full list, and sends nothing", async () => {
    const { result, api } = await reorder("--ids", "lesson-213,lesson-213,lesson-999");
    expect(result.code).toBe(EXIT.usage);
    expect(result.stderr).toContain("Not a permutation of the edition's 3 lessons (missing: lesson-211, lesson-212; not in this course: lesson-999; repeated: lesson-213).");
    expect(api.mutations()).toEqual([]);
    for (const extra of [["--move", "lesson-999", "--to", "1"], ["--move", "lesson-211", "--to", "9"], ["--ids", "a", "--move", "lesson-211", "--to", "1"], ["--move", "lesson-211"]]) {
      expect((await reorder(...extra)).result.code, extra.join(" ")).toBe(EXIT.usage);
    }
    const same = await reorder("--ids", "lesson-211,lesson-212,lesson-213");
    expect([same.result.code, same.api.mutations()]).toEqual([0, []]);
  });
});

describe("tower-catalog publish verification", () => {
  it("fails with the rollback command when the site does not serve the new release", async () => {
    const api = fakeApi({ public: (request) => ({ raw: request.path.startsWith("/api/health") ? JSON.stringify({ catalog: { release: 3 } }) : "" }) });
    const result = await runCli(["publish", "course-6", "--note", "Go", "--yes", ...P], { api });
    expect(result.code).toBe(EXIT.api);
    expect(result.stderr).toContain("Post-check: /api/health serves release #3, not #4. Roll back with: tower-catalog release activate 3 --target preview");
    const missing = fakeApi({ public: (request) => (request.path.startsWith("/api/health") ? { status: 404, raw: JSON.stringify({ catalog: { release: 4 }, courses: [{ slug: "freud", present: false }] }) } : { status: 429, raw: "edge challenge" }) });
    const page = await runCli(["publish", "course-6", "--note", "Go", "--yes", ...P], { api: missing });
    expect(page.stderr).toContain("Post-check: /api/health did not confirm courses in release #4: freud.");
  });

  it("reminds the inverse command after an activation", async () => {
    const result = await runCli(["release", "activate", "2", "--yes", ...P], { api: fakeApi({ public: () => ({ raw: JSON.stringify({ catalog: { release: 2 } }) }) }) });
    expect(result.code).toBe(0);
    expect(result.stdout).toContain("Undo: tower-catalog release activate 3 --target preview");
  });
});

describe("tower-catalog review", () => {
  it("prints the whole course in a stable layout", () => {
    expect(reviewLines(courseDetail()).join("\n")).toMatchSnapshot();
  });
  it("--json returns the API envelope intact", async () => {
    const result = await runCli(["review", "course-6", "--json", ...P]);
    expect(JSON.parse(result.stdout)).toEqual({ ok: true, data: JSON.parse(JSON.stringify(courseDetail())) as unknown, requestId: "00000000-0000-4000-8000-000000000001" });
  });
});

describe("tooling/tower-catalog (bash)", () => {
  it("installs into ~/.local/bin a shim that runs only this checkout", () => {
    const home = tmp();
    const out = execFileSync("bash", [wrapper, "install"], { env: { ...process.env, HOME: home }, encoding: "utf8" });
    const installed = join(home, ".local/bin/tower-catalog");
    expect(out).toContain("installed ~/.local/bin/tower-catalog");
    expect(statSync(installed).mode & 0o111).not.toBe(0);
    // The shim runs only this checkout.
    expect(readFileSync(installed, "utf8")).toContain(`checkout=${repo.replace(/\/$/, "")}\n`);
    expect(readFileSync(installed, "utf8")).toContain('exec "$checkout/tooling/tower-catalog" "$@"');
  });

  it("names the missing variable without printing the file, and passes the secret on a descriptor", () => {
    const dir = tmp();
    const envFile = join(dir, "admin-media.env");
    const run = (args: string[]) => spawnSync("bash", [wrapper, ...args], { env: { ...process.env, TOWER_ADMIN_MEDIA_ENV: envFile, TOWER_ADMIN_MEDIA_SECRET: "ambient-must-not-leak", TOWER_MEDIA_URL_PREVIEW: "https://ambient0must0not0win.lambda-url.us-east-1.on.aws", TOWER_MEDIA_URL_PROD: "https://ambient0prod0must0not0win.lambda-url.us-east-1.on.aws", TOWER_MEDIA_URL_STAGING: "https://ambient0staging0must0not0win.lambda-url.us-east-1.on.aws" }, encoding: "utf8" });
    writeFileSync(envFile, `TOWER_ADMIN_MEDIA_SECRET=${SENTINEL}\n`);
    const noUrl = run(["doctor", "--target", "preview"]);
    expect([noUrl.status, noUrl.stderr.trim()]).toEqual([2, `tower-catalog: TOWER_MEDIA_URL_PREVIEW is not set in ${envFile}`]);
    writeFileSync(envFile, "TOWER_MEDIA_URL_PREVIEW=https://x0preview.lambda-url.us-east-1.on.aws\n");
    expect(run(["doctor", "--target", "preview"]).stderr).toContain(`TOWER_ADMIN_SECRET_PROD and TOWER_ADMIN_SECRET_PREVIEW are not set in ${envFile} (nor the fallback TOWER_ADMIN_MEDIA_SECRET)`);
    expect(run(["doctor"]).stderr).toContain("--target preview|staging|prod is required");
    writeFileSync(envFile, `TOWER_ADMIN_MEDIA_SECRET=${SENTINEL}\nTOWER_MEDIA_URL_PREVIEW=https://x0preview.lambda-url.us-east-1.on.aws\n`);
    // Fails on the local schema check, after the Node half read the descriptor and before any request.
    const bad = run(["course", "create", "--slug", "Bad Slug", "--author-id", "author-1", "--title", "X", "--target", "preview"]);
    expect(bad.status).toBe(2);
    expect(bad.stderr).toContain("Invalid request for POST /courses");
    expect(`${bad.stdout}${bad.stderr}${noUrl.stdout}${noUrl.stderr}`).not.toContain(SENTINEL);
    // The keys are only tested for emptiness and used as printf (builtin) arguments feeding descriptor 3.
    const uses = readFileSync(wrapper, "utf8").split("\n").filter((line) => /\$\{?secret/.test(line) && !/\[ -z "\$secret_(prod|preview)" \]/.test(line));
    expect(uses).toEqual([`exec "$node" "$entry" "$@" 3< <(printf 'secret.prod=%s\\nsecret.preview=%s\\n' "$secret_prod" "$secret_preview")`]);
  });

  it("sends each target its own key, falls back to the shared key only while neither exists, and refuses half a pair", () => {
    // A stand-in checkout (this wrapper, this Node) whose entry echoes descriptor 3: the wrapper's real output, with test values only.
    const fake = tmp();
    mkdirSync(join(fake, "scripts"));
    mkdirSync(join(fake, "tooling"));
    copyFileSync(wrapper, join(fake, "tooling/tower-catalog"));
    writeFileSync(join(fake, "scripts/tower-catalog.ts"), `import { readFileSync } from "node:fs";\nprocess.stdout.write(readFileSync(Number(process.env.TOWER_CATALOG_SECRET_FD), "utf8"));\n`);
    const envFile = join(tmp(), "admin-media.env");
    const url = "TOWER_MEDIA_URL_PREVIEW=https://x0preview.lambda-url.us-east-1.on.aws\nTOWER_MEDIA_URL_PROD=https://openuniversity.si\n";
    const run = (file: string, ambient: Record<string, string> = {}) => {
      writeFileSync(envFile, `${url}${file}`);
      return spawnSync("bash", [join(fake, "tooling/tower-catalog"), "doctor", "--target", "prod"], { env: { ...process.env, TOWER_NODE: process.execPath, TOWER_ADMIN_MEDIA_ENV: envFile, ...ambient }, encoding: "utf8" });
    };
    const both = run("TOWER_ADMIN_SECRET_PROD=k-prod\nTOWER_ADMIN_SECRET_PREVIEW=k-preview\nTOWER_ADMIN_MEDIA_SECRET=k-shared\n");
    expect([both.status, both.stdout]).toEqual([0, "secret.prod=k-prod\nsecret.preview=k-preview\n"]);
    const shared = run("TOWER_ADMIN_MEDIA_SECRET=k-shared\n", { TOWER_ADMIN_SECRET_PROD: "ambient-must-not-leak" });
    expect([shared.status, shared.stdout]).toEqual([0, "secret.prod=k-shared\nsecret.preview=k-shared\n"]);
    const half = run("TOWER_ADMIN_SECRET_PROD=k-prod\nTOWER_ADMIN_MEDIA_SECRET=k-shared\n");
    expect([half.status, half.stderr.trim()]).toEqual([2, `tower-catalog: TOWER_ADMIN_SECRET_PREVIEW is not set in ${envFile}; set both per-target keys (TOWER_ADMIN_SECRET_PROD is set)`]);
    const other = run("TOWER_ADMIN_SECRET_PREVIEW=k-preview\n");
    expect([other.status, other.stderr.trim()]).toEqual([2, `tower-catalog: TOWER_ADMIN_SECRET_PROD is not set in ${envFile}; set both per-target keys (TOWER_ADMIN_SECRET_PREVIEW is set)`]);
    expect(`${half.stdout}${half.stderr}${other.stdout}${other.stderr}`).not.toMatch(/k-prod|k-preview|k-shared/);
  });

  it("uses exported credentials when no env file exists, and does not send them to a refused host", () => {
    const missing = join(tmp(), "missing.env");
    const result = spawnSync("bash", [wrapper, "doctor", "--target", "preview"], {
      env: { ...process.env, TOWER_ADMIN_MEDIA_ENV: missing, TOWER_ADMIN_MEDIA_SECRET: "exported-test-secret", TOWER_MEDIA_URL_PREVIEW: "https://evil.example" },
      encoding: "utf8",
    });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain("outside openuniversity.si");
    expect(result.stderr).not.toContain("is not set");
    expect(`${result.stdout}${result.stderr}`).not.toContain("exported-test-secret");
  });

  it("is valid bash and executable", () => {
    expect(spawnSync("bash", ["-n", wrapper]).status).toBe(0);
    expect(statSync(wrapper).mode & 0o111).not.toBe(0);
    if (spawnSync("shellcheck", ["--version"]).status === 0) expect(spawnSync("shellcheck", [wrapper], { encoding: "utf8" }).stdout).toBe("");
  });
});


describe("link previews (og:image) in the publish pipeline", () => {
  it("covers uploads the 1200×630 JPEG rendered from hero-desktop as hero_desktop_16x9/og", async () => {
    const api = fakeApi();
    const result = await runCli(["covers", "course-6", "--dir", coversDir(), "--yes", ...P], { api });
    expect(result.code, result.stderr).toBe(0);
    const og = api.requests.find((request) => request.key === "media:POST /attach" && (request.body as { variant?: string }).variant === "og");
    expect(og).toBeDefined();
    // Uploads run concurrently; inspect the object attached as OG, independent of arrival order.
    const ogHash = (og?.body as { sha256?: string } | undefined)?.sha256;
    const bytes = api.requests.find((request) => request.key === "media:POST /objects" && (request.body as { sha256?: string }).sha256 === ogHash)?.fileBytes;
    expect(bytes).toBeDefined();
    const meta = await sharp(bytes ?? Buffer.alloc(0)).metadata();
    expect([meta.format, meta.width, meta.height]).toEqual(["jpeg", 1200, 630]);
    expect((bytes ?? Buffer.alloc(0)).length).toBeLessThanOrEqual(300 * 1024);
  });

  it("og backfills from the active hero listed by the media API, one course at a time", async () => {
    const { activeHeroUrl } = await import("./lib/catalog-cli/commands/covers.ts");
    expect(activeHeroUrl([{ active: false, kind: "hero_desktop_16x9", variant: "default", url: "https://media.openuniversity.si/a.webp" }, { active: true, kind: "hero_desktop_16x9", variant: "default", url: "https://media.openuniversity.si/b.webp" }]))
      .toBe("https://media.openuniversity.si/b.webp");
    expect(activeHeroUrl([{ active: true, kind: "hero_desktop_16x9", variant: "og", url: "https://x/y.jpg" }])).toBeNull();
    const api = fakeApi();
    const result = await runCli(["og", "course-6", "--file", heroFile(), "--yes", ...P], { api });
    expect(result.code, result.stderr).toBe(0);
    const attach = api.requests.filter((request) => request.key === "media:POST /attach");
    expect(attach).toHaveLength(1);
    expect(attach[0]?.body).toMatchObject({ owner: "course", ownerId: "course-6", kind: "hero_desktop_16x9", variant: "og" });
    expect((await runCli(["og", "course-6", "course-7", "--file", heroFile(), "--yes", ...P])).code).toBe(EXIT.usage);
  });

  it("home og letterboxes each university cover and keeps every other row as it is", async () => {
    const { homeRowsWithCovers } = await import("./lib/catalog-cli/commands/university-cover.ts");
    const cover = { url: "https://media.openuniversity.si/covers/mit/university_cover_9x16/a.webp", width: 1080, height: 1920, sha256: "a".repeat(64), alt: "MIT", credit: "Photo: X", sourceUrl: "https://example.org", license: "CC BY 2.0", note: null };
    const og = { url: "https://media.openuniversity.si/covers/mit/university_og/b.jpg", width: 1200, height: 630, sha256: "b".repeat(64) };
    const rows = [
      { id: "continue", kind: "continue" as const, title: null, authorId: null, visible: true, position: 1, courseIds: [] },
      { id: "mit", kind: "curated" as const, title: "MIT", authorId: null, visible: true, position: 2, courseIds: ["course-1"], cover },
    ];
    expect(homeRowsWithCovers(rows, new Map([["mit", { ...cover, og }]]))).toEqual([
      { id: "continue", kind: "continue", visible: true, courseIds: [] },
      { id: "mit", kind: "curated", title: "MIT", visible: true, courseIds: ["course-1"], cover: { ...cover, og } },
    ]);
    const dir = tmp();
    writeFileSync(join(dir, "mit.webp"), await sharp({ create: { width: 270, height: 480, channels: 3, background: "#ffffff" } }).webp().toBuffer());
    const api = fakeApi({ "GET /home": () => ({ data: { revision: 5, featuredCourseId: "course-1", rows } }) });
    const dry = await runCli(["home", "og", "mit", "--dir", dir, "--dry-run", ...P], { api });
    expect(dry.stderr).toContain("DRY-RUN: nothing uploaded or published.");
    expect(dry.code).toBe(0);
    expect(dry.stdout).toMatch(/mit: m\/[a-f0-9]{64}\.jpg \(\d+ KiB, 1200×630\)/);
    expect(api.mutations()).toEqual([]);
    expect((await runCli(["home", "og", "nope", "--dry-run", ...P], { api })).code).toBe(EXIT.usage);
  });
});

describe("byte deletes check the other environment (shared R2 bucket)", () => {
  const purge = ["course", "delete", "course-6", "--mode", "purge", "--confirm", "--yes", ...P];
  const withCandidates = (keys: string[]): Partial<Record<RouteKey, Handler>> => ({
    "DELETE /courses/:id": (request) => ({ data: request.query.confirm === "true" ? { dryRun: false, purged: true, report: {}, bytes: { deleted: [], pending: [] } } : { dryRun: true, report: { r2Candidates: keys, blockedBy: [] } } }),
  });
  const confirmed = (api: ReturnType<typeof fakeApi>) => api.requests.find((request) => request.key === "DELETE /courses/:id" && request.query.confirm === "true")?.query;

  it("keeps every byte by default and never asks the other environment", async () => {
    const api = fakeApi(withCandidates(["covers/course-6/poster_9x16/a.jpg"]));
    expect((await runCli(purge, { api })).code).toBe(0);
    expect(confirmed(api)?.deleteBytes).toBeUndefined();
    expect(api.calls().some((call) => call.includes("/media/references"))).toBe(false);
  });
  it("--delete-bytes deletes only after prod answers that it uses none of the candidates", async () => {
    const api = fakeApi(withCandidates(["covers/course-6/poster_9x16/a.jpg"]));
    const result = await runCli([...purge, "--delete-bytes"], { api });
    expect(result.code).toBe(0);
    expect(api.requests.find((request) => request.key === "POST /media/references")?.body).toEqual({ keys: ["covers/course-6/poster_9x16/a.jpg"] });
    expect(confirmed(api)?.deleteBytes).toBe("true");
    expect(JSON.parse(confirmed(api)?.checkedKeys ?? "[]")).toEqual(["covers/course-6/poster_9x16/a.jpg"]);
  });
  it("--delete-bytes keeps every byte when the other environment uses one of them, or cannot answer", async () => {
    const shared = fakeApi(withCandidates(["covers/course-6/poster_9x16/a.jpg", "covers/course-6/hero/shared.jpg"]));
    const used = await runCli([...purge, "--delete-bytes"], { api: shared });
    expect([used.code, confirmed(shared)?.deleteBytes]).toEqual([0, undefined]);
    expect(used.stderr + used.stdout).toMatch(/prod still uses 1 of these key\(s\).*keeping every R2 byte/);
    const down = fakeApi({ ...withCandidates(["covers/course-6/poster_9x16/a.jpg"]), "POST /media/references": () => ({ status: 503, error: { code: "unconfigured", message: "down" } }) });
    const failed = await runCli([...purge, "--delete-bytes"], { api: down });
    expect([failed.code, confirmed(down)?.deleteBytes]).toEqual([0, undefined]);
    expect(failed.stderr + failed.stdout).toMatch(/Could not check prod.*keeping every R2 byte/);
  });
});
