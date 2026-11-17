import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { validateCourseBundle } from "../../../../src/catalog/domain/bundle.ts";
import { prepareMedia } from "../../../../src/media/server/prepare.ts";
import { fakeApi, runCli } from "../cli.test-helpers.ts";

function video(index: number): string {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  return `abcdefghi${alphabet[Math.floor(index / 36)] ?? "a"}${alphabet[index % 36] ?? "a"}`;
}

function bundle(count: number, id = "course-live") {
  const lessons = Array.from({ length: count }, (_, index) => ({
    id: `${id}-lesson-${String(index + 1)}`, editionId: `${id}-edition-1`, slug: `lecture-${String(index + 1)}`, title: `Lecture ${String(index + 1)}`,
    position: index + 1, youtubeId: video(index), durationSeconds: 60,
  }));
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id, slug: id, title: "Contracts", authorId: "author-a", coverFrom: "own", sharedWith: [] },
    editions: [{ id: `${id}-edition-1`, slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons,
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

const SHIP_KEYS = new Set(["media:POST /check", "media:POST /objects", "POST /batches/apply"]);

describe("ship", () => {
  it("sends only media check, media objects and POST /batches/apply", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-v2-"));
    const poster = join(dir, "poster.png");
    copyFileSync(new URL("../../../../public/icons/icon-512.png", import.meta.url), poster);
    const prepared = await prepareMedia(poster);
    writeFileSync(join(dir, "batch.json"), JSON.stringify({
      version: 2,
      courses: [{
        institutionId: "usp",
        course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] },
        covers: [{ kind: "poster_9x16", sha: prepared.sha256 }],
      }],
    }));
    const api = fakeApi({
      "media:POST /check": (request) => ({ data: { missing: (request.body as { sha256: string[] }).sha256, objects: [] } }),
      "media:POST /objects": (request) => ({ data: { sha256: (request.body as { sha256: string }).sha256, pathname: "" } }),
    });
    const result = await runCli(["ship", join(dir, "batch.json"), "--to", "preview", "--yes", "--target", "preview"], { api });
    expect(result.code, result.stderr).toBe(0);
    const keys = api.requests.map((request) => request.key);
    expect(keys.every((key) => SHIP_KEYS.has(key))).toBe(true);
    expect(new Set(keys)).toEqual(SHIP_KEYS);
    const apply = api.requests.find((request) => request.key === "POST /batches/apply");
    expect(apply?.body).toMatchObject({ dryRun: false, chunk: 0, chunks: 1 });
    expect(result.stdout).toContain("committed");
    expect(result.stdout).not.toMatch(/\d+ms/);
  });

  it("ships a directory of v1 bundles through apply and does not read Home", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-dir-"));
    mkdirSync(join(dir, "covers"));
    copyFileSync(new URL("../../../../public/icons/icon-512.png", import.meta.url), join(dir, "covers", "poster.png"));
    const author = { id: "inst-ship", slug: "inst-ship", name: "Ship U", monogram: "SU", kind: "institution" };
    for (const id of ["course-a", "course-b"]) {
      const value = bundle(1, id);
      writeFileSync(join(dir, `${id}.json`), JSON.stringify({
        ...value, author, course: { ...value.course, authorId: author.id }, covers: [{ kind: "poster_9x16", path: "covers/poster.png" }],
      }));
    }
    const api = fakeApi({
      "media:POST /check": (request) => ({ data: { missing: (request.body as { sha256: string[] }).sha256, objects: [] } }),
      "media:POST /objects": (request) => ({ data: { sha256: (request.body as { sha256: string }).sha256, pathname: "" } }),
    });
    const result = await runCli(["ship", dir, "--to", "preview", "--yes", "--target", "preview"], { api });
    expect(result.code, result.stderr).toBe(0);
    const keys = api.requests.map((request) => request.key);
    expect(keys.every((key) => SHIP_KEYS.has(key))).toBe(true);
    expect(keys).not.toContain("GET /home");
    expect(api.requests.filter((request) => request.key === "POST /batches/apply")).toHaveLength(1);
    const part = (api.requests.find((request) => request.key === "POST /batches/apply")?.body as { part: { courses: { institutionId: string }[] } }).part;
    expect(part.courses.map((course) => course.institutionId)).toEqual(["inst-ship", "inst-ship"]);
  });

  it("refuses a person author on no University row before any request", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-person-"));
    writeFileSync(join(dir, "one.json"), JSON.stringify(bundle(1, "course-live")));
    const api = fakeApi();
    const result = await runCli(["ship", dir, "--to", "preview", "--yes", "--target", "preview"], { api });
    expect(result.code).not.toBe(0);
    expect(result.stderr).toMatch(/nothing was sent/);
    expect(result.stderr).toMatch(/D-024/);
    expect(api.calls()).toEqual([]);
  });

  it("points home cover at ship and sends nothing", async () => {
    const api = fakeApi();
    const result = await runCli(["home", "cover", "picks", "--clear", "--yes", "--target", "preview"], { api });
    expect(result.code).not.toBe(0);
    expect(result.stderr).toContain("ship <dir|batch>");
    expect(api.calls()).toEqual([]);
  });

  it("points --batch, --bulk and --concurrency at ship <dir|batch> and sends nothing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-removed-"));
    writeFileSync(join(dir, "batch.json"), JSON.stringify({ version: 2, courses: [{ institutionId: "usp", course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] }, editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }] }] }));
    for (const extra of [["--batch"], ["--bulk"], ["--concurrency", "4"]]) {
      const api = fakeApi();
      const result = await runCli(["ship", dir, "--to", "preview", ...extra, "--yes", "--target", "preview"], { api });
      expect(result.code, extra.join(" ")).not.toBe(0);
      expect(result.stderr).toContain("ship <dir|batch>");
      expect(api.calls()).toEqual([]);
    }
  });

  it("prints the dry-run report, repeats the same bytes, and exits non-zero when apply fails", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-dry-"));
    const poster = join(dir, "poster.png");
    copyFileSync(new URL("../../../../public/icons/icon-512.png", import.meta.url), poster);
    const prepared = await prepareMedia(poster);
    const batch = join(dir, "batch.json");
    writeFileSync(batch, JSON.stringify({
      version: 2,
      courses: [{
        institutionId: "usp",
        course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] },
        covers: [{ kind: "poster_9x16", sha: prepared.sha256 }],
      }],
    }));
    const handlers = {
      "media:POST /check": (request: { body: unknown }) => ({ data: { missing: (request.body as { sha256: string[] }).sha256, objects: [] } }),
      "media:POST /objects": (request: { body: unknown }) => ({ data: { sha256: (request.body as { sha256: string }).sha256, pathname: "" } }),
      "POST /batches/apply": (request: { body: unknown }) => {
        const body = request.body as { batchHash: string; dryRun: boolean };
        return { data: { status: body.dryRun ? "dry-run" : "committed", batchHash: body.batchHash, draft: false, plan: { course: { create: 1 } }, courses: ["usp-mecanica"], release: { number: 4, created: true } } };
      },
    };
    const firstApi = fakeApi(handlers);
    const argv = ["ship", batch, "--to", "preview", "--dry-run", "--yes", "--target", "preview"] as const;
    const first = await runCli(argv, { api: firstApi });
    const secondApi = fakeApi(handlers);
    const second = await runCli(argv, { api: secondApi });
    expect(first.code, first.stderr).toBe(0);
    expect(first.stdout).toBe(second.stdout);
    expect(first.stdout).toContain("dry-run");
    expect(first.stdout).not.toMatch(/\d+ms/);
    expect(new Set(firstApi.requests.map((request) => request.key))).toEqual(SHIP_KEYS);
    expect(firstApi.requests.find((request) => request.key === "POST /batches/apply")?.body).toMatchObject({ dryRun: true });
    const failed = fakeApi({
      "POST /batches/apply": () => ({ status: 422, error: { code: "unprocessable", message: "Violates catalog_institution_cover." } }),
    });
    const failure = await runCli(["ship", batch, "--to", "preview", "--dry-run", "--yes", "--target", "preview"], { api: failed });
    expect(failure.code).not.toBe(0);
    expect(failure.stderr).toMatch(/catalog_institution_cover/);
  });

  it("ships --to both as one apply on each environment", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-both-"));
    const path = join(dir, "batch.json");
    writeFileSync(path, JSON.stringify({
      version: 2,
      courses: [{ institutionId: "usp", course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] }, editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }] }],
    }));
    const credentials = { secrets: { prod: "key-prod", preview: "key-preview" } };
    const preview = fakeApi({}, credentials, "preview");
    const prod = fakeApi({}, credentials, "prod");
    const result = await runCli(["ship", path, "--to", "both", "--yes", "--target", "preview"], {
      api: preview, deps: { transport: (target) => (target === "prod" ? prod : preview).transport },
    });
    expect(result.code, result.stderr).toBe(0);
    expect(preview.requests.map((request) => request.key)).toEqual(["POST /batches/apply"]);
    expect(prod.requests.map((request) => request.key)).toEqual(["POST /batches/apply"]);
    expect(new Set(preview.requests.map((request) => request.headers.authorization))).toEqual(new Set(["Bearer key-preview"]));
    expect(new Set(prod.requests.map((request) => request.headers.authorization))).toEqual(new Set(["Bearer key-prod"]));
    expect(`${result.stdout}${result.stderr}`).not.toMatch(/key-prod|key-preview/);
  });

  it("D-038: refuses production without a passing rehearsal and rehearses a committed preview ship", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-health-"));
    const path = join(dir, "batch.json");
    writeFileSync(path, JSON.stringify({
      version: 2,
      courses: [{ institutionId: "usp", course: { id: "usp-mecanica", slug: "mecanica-geral", title: "Mecânica Geral", authorId: "ana-lima", coverFrom: "own", sharedWith: [] }, editions: [{ id: "usp-mecanica-2021", slug: "2021", label: "2021", position: 1, year: 2021 }] }],
    }));
    const runs: string[][] = [];
    const record = (command: string, args: readonly string[]) => {
      runs.push([command, ...args]);
    };
    const missing = fakeApi();
    const refused = await runCli(["ship", path, "--to", "prod", "--yes"], {
      api: missing,
      env: { TOWER_MEDIA_URL_PROD: "https://tower0test.lambda-url.us-east-1.on.aws" },
      deps: {
        run: (command, args) => {
          record(command, args);
          return Promise.resolve({ code: 1, stdout: "", stderr: "site-health report is missing for this batch" });
        },
      },
    });
    expect(refused.code).not.toBe(0);
    expect(refused.stderr).toContain("site-health");
    expect(missing.calls()).toEqual([]);
    expect(runs.some((args) => args.includes("--require") && args.some((part) => part.endsWith("site-health.ts")))).toBe(true);

    runs.length = 0;
    const preview = fakeApi();
    const shipped = await runCli(["ship", path, "--to", "preview", "--yes", "--target", "preview"], {
      api: preview,
      deps: {
        run: (command, args) => {
          record(command, args);
          return Promise.resolve({ code: 0, stdout: "", stderr: "" });
        },
      },
    });
    expect(shipped.code, shipped.stderr).toBe(0);
    expect(preview.calls()).toEqual(["POST /batches/apply"]);
    const rehearsal = runs.find((args) => args.includes("--clone") && args.includes("staging") && args.some((part) => part.endsWith("site-health.ts")));
    expect(rehearsal?.some((part) => /^[a-f0-9]{64}$/.test(part))).toBe(true);

    runs.length = 0;
    const dry = fakeApi();
    const dryRun = await runCli(["ship", path, "--to", "preview", "--dry-run", "--yes", "--target", "preview"], {
      api: dry,
      deps: {
        run: (command, args) => {
          record(command, args);
          return Promise.resolve({ code: 1, stdout: "", stderr: "site-health should not run" });
        },
      },
    });
    expect(dryRun.code, dryRun.stderr).toBe(0);
    expect(runs).toEqual([]);
    expect(dry.calls()).toEqual(["POST /batches/apply"]);
  });
});
