import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { syntheticCatalog } from "../../../src/catalog/testing/synthetic.ts";
import { describe, expect, it } from "vitest";
import { REQUIRED_COVERS } from "../../../src/catalog/domain/rules/status.ts";
import { TEXT_FIELDS } from "../../../src/catalog/domain/fields.ts";
import { parseStoredRelease } from "../../../src/catalog/domain/release.ts";
import { catalogTables } from "../../../src/catalog/domain/tables.ts";
import { MEDIA_BYTE_BUDGETS } from "../../../src/media/domain/budget.ts";
import { courseKinds, lessonKinds } from "../../../src/media/domain/types.ts";
import { lessonPatchQuery, lessonSlugSchema, lessonSlugsPut } from "../../../src/catalog/domain/contracts.ts";
import { reslugCourse, slugCourseFromTables } from "../../../src/catalog/domain/slug-course.ts";
import { SLUG_PATTERN } from "../../../src/catalog/domain/lesson-address.ts";
import { courseDetail, fakeApi, importedTables, runCli, snapshotTables } from "./cli.test-helpers.ts";
import { EXIT } from "./errors.ts";
import { cliRoute, isServerDryRun } from "./routes.ts";
import { COURSE_COVER_FILES, LESSON_COVER_KIND, planCovers } from "./commands/covers.ts";
import { jsonbKeyOrder, snapshotFiles } from "../catalog-export.ts";
import { checkTextsFile } from "./commands/texts.ts";

// Guardians that keep tower-catalog's local checks equal to the code they mirror: cover kinds and byte budgets
// (src/media), slot limits and the Inter subset (src/catalog/domain/fields.ts), and the current API export byte format.


describe("covers ↔ src/media", () => {
  it("maps file names to real media kinds, including every cover review requires", () => {
    for (const kind of Object.values(COURSE_COVER_FILES)) expect(courseKinds).toContain(kind);
    expect(lessonKinds).toContain(LESSON_COVER_KIND);
    for (const kind of REQUIRED_COVERS) expect(Object.values(COURSE_COVER_FILES)).toContain(kind);
  });

  it("enforces MEDIA_BYTE_BUDGETS byte for byte", () => {
    for (const [name, kind] of [...Object.entries(COURSE_COVER_FILES), ["lessons/01", LESSON_COVER_KIND] as const]) {
      const dir = mkdtempSync(join(tmpdir(), "covers-"));
      mkdirSync(join(dir, "lessons"));
      const path = join(dir, `${name}.jpg`);
      writeFileSync(path, Buffer.alloc(MEDIA_BYTE_BUDGETS[kind]));
      expect(planCovers(dir).files.map((entry) => [entry.kind, entry.bytes])).toEqual([[kind, MEDIA_BYTE_BUDGETS[kind]]]);
      writeFileSync(path, Buffer.alloc(MEDIA_BYTE_BUDGETS[kind] + 1));
      expect(() => planCovers(dir), kind).toThrow(`over the ${String(MEDIA_BYTE_BUDGETS[kind] / 1024)} KiB budget of ${kind}`);
      expect(planCovers(dir, true).warnings).toHaveLength(1);
    }
  });

  it("lists every problem of a folder at once", () => {
    const dir = mkdtempSync(join(tmpdir(), "covers-"));
    mkdirSync(join(dir, "lessons"));
    for (const name of ["poster.jpg", "poster.png", "hero.jpg", "still.gif", "lessons/1.jpg", "lessons/02.tiff"]) writeFileSync(join(dir, name), "x");
    expect(() => planCovers(dir)).toThrow(/5 problem\(s\)[\s\S]*hero\.jpg[\s\S]*lessons\/02\.tiff[\s\S]*lessons\/1\.jpg[\s\S]*poster\.png and poster\.jpg fill the same cover[\s\S]*still\.gif/);
  });
});

describe("texts ↔ src/catalog/domain/fields.ts", () => {
  it("draft-copy hands the session the slots of fields.ts and a template of every review field", async () => {
    const result = await runCli(["draft-copy", "course-6", "--json", "--target", "preview"]);
    // --json wraps the pack in the one envelope; --out writes the bare pack.
    const { data: pack } = JSON.parse(result.stdout) as { ok: true; data: { slots: Record<string, Record<string, { maxChars: number; requiredForReview: boolean; requiredForPublish: boolean }>>; template: { entityKind: string; field: string; source: string; confidence: string }[] } };
    for (const kind of ["course", "lesson"] as const) {
      expect(pack.slots[kind]).toEqual(Object.fromEntries(Object.entries(TEXT_FIELDS[kind]).map(([field, spec]) => [field, { maxChars: spec.maxChars, requiredForReview: spec.review, requiredForPublish: spec.publish }])));
    }
    expect(pack.template.filter((item) => item.entityKind === "course").map((item) => item.field)).toEqual(Object.entries(TEXT_FIELDS.course).filter(([, spec]) => spec.review).map(([field]) => field));
    expect([...new Set(pack.template.filter((item) => item.entityKind === "lesson").map((item) => item.field))]).toEqual(Object.entries(TEXT_FIELDS.lesson).filter(([, spec]) => spec.review).map(([field]) => field));
    expect(pack.template.every((item) => item.source === "llm" && item.confidence === "medium")).toBe(true);
  });

  it("texts put refuses a text over its slot or outside the Inter subset, and an entity of another course", () => {
    const item = (field: string, text: string, entityId = "course-6") => ({ entityKind: "course", entityId, field, text, source: "llm", sourceRef: "t", confidence: "medium" });
    const max = TEXT_FIELDS.course.level.maxChars;
    expect(checkTextsFile([item("level", "x".repeat(max))], courseDetail())).toHaveLength(1);
    expect(() => checkTextsFile([item("level", "x".repeat(max + 1)), item("subtitle", "Dreams \u{1F600}"), item("subtitle", "ok", "course-7")], courseDetail()))
      .toThrow(/3 problem\(s\)[\s\S]*\[0\] texts\.limit[\s\S]*\[1\] texts\.charset[\s\S]*\[2\] course:course-7 is not course-6/);
    expect(() => checkTextsFile([{ ...item("level", "x"), source: "robot" }], courseDetail())).toThrow("texts.json does not match PUT /texts: 0.source");
  });
});

describe("current catalog export", () => {
  it("writes synthetic current-schema exports stably regardless of API key order", () => {
    const release = parseStoredRelease(syntheticCatalog);
    // jsonb reorders object keys (arrays keep their order); table rows may come in any order.
    const shuffle = (value: unknown): unknown => (Array.isArray(value) ? value.map(shuffle) : value !== null && typeof value === "object" ? Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, shuffle(item)])) : value);
    const files = snapshotFiles(shuffle(release) as typeof release, Object.fromEntries(Object.entries(snapshotTables).map(([name, rows]) => [name, [...rows as unknown[]].reverse().map(shuffle)])) as typeof snapshotTables);
    expect([...files.keys()].sort()).toEqual(["release.json", ...catalogTables.map(({ name }) => `tables/${name}.json`)].sort());
    expect(files).toEqual(snapshotFiles(release, snapshotTables));
  });

  it("orders free-form JSON like jsonb", () => {
    expect(JSON.stringify(jsonbKeyOrder({ still: 1, b: { zz: 1, a: 2 }, heroPresent: [{ yy: 1, x: 2 }], aa: 0 }))).toBe('{"b":{"a":2,"zz":1},"aa":0,"still":1,"heroPresent":[{"x":2,"yy":1}]}');
  });

  it("is stable: a second run changes nothing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "snapshot-"));
    const first = await runCli(["snapshot", "--dir", dir, "--target", "preview"]);
    expect(first.stdout).toContain("14 file(s) changed");
    const second = await runCli(["snapshot", "--dir", dir, "--target", "preview"]);
    expect(second.stdout).toContain(": no change.");
    expect(JSON.parse(readFileSync(join(dir, "release.json"), "utf8"))).toEqual(syntheticCatalog);
  });
});

describe("lesson set --slug ↔ PATCH /lessons/:id", () => {
  it("checks the slug locally with the API's schema (the lessons_slug CHECK: pattern, ≤ 160) and sends nothing when it fails", async () => {
    expect(lessonSlugSchema.safeParse("a".repeat(160)).success).toBe(true);
    for (const slug of ["a".repeat(161), "Dreams", "two--dashes", "-lead", "trail-", "ç"]) {
      expect(lessonSlugSchema.safeParse(slug).success, slug).toBe(false);
      expect(SLUG_PATTERN.test(slug) && slug.length <= 160, slug).toBe(false);
      const api = fakeApi();
      const result = await runCli(["lesson", "set", "course-6", "lesson-213", "--slug", slug, "--target", "preview"], { api });
      expect(result.code, slug).toBe(EXIT.usage);
      expect(api.mutations(), slug).toEqual([]);
    }
  });

  it("treats ?dryRun=true as the server's dry-run, like the route's query schema", () => {
    expect(lessonPatchQuery.safeParse({ dryRun: "true" }).success).toBe(true);
    expect(isServerDryRun("PATCH /lessons/:id", { dryRun: "true" })).toBe(true);
    expect(isServerDryRun("PATCH /lessons/:id", {})).toBe(false);
  });
});

describe("lesson reslug ↔ PUT /lessons/slugs", () => {
  it("sends exactly the slugs src/catalog/domain/slug-course.ts gives, in a body the route's own schema accepts", async () => {
    const api = fakeApi({ "GET /tables": () => ({ data: { activeRelease: null, tables: importedTables() } }) });
    expect((await runCli(["lesson", "reslug", "cmu-db", "--apply", "--target", "preview"], { api })).code).toBe(EXIT.ok);
    const body = api.requests.find((request) => request.key === "PUT /lessons/slugs")?.body;
    expect(lessonSlugsPut.safeParse(body).success).toBe(true);
    const course = slugCourseFromTables(importedTables(), "course-30");
    const expected = reslugCourse(course ?? { slug: "", title: "", institution: null, editions: [], lessons: [] }).filter((entry) => entry.before !== entry.after);
    expect((body as { changes: unknown }).changes).toEqual(expected.map((entry) => ({ lessonId: entry.lessonId, slug: entry.after })));
    expect(cliRoute("PUT /lessons/slugs").body).toBe(lessonSlugsPut);
  });

  it("treats a body with dryRun: true as the server's dry-run (the key is still required) and caps the batch like the API", () => {
    expect(isServerDryRun("PUT /lessons/slugs", {}, { dryRun: true })).toBe(true);
    expect(isServerDryRun("POST /batches/apply", {}, { dryRun: true })).toBe(true);
    expect(isServerDryRun("POST /batches/apply", {}, { dryRun: false })).toBe(false);
    expect(isServerDryRun("PUT /lessons/slugs", {}, { dryRun: false })).toBe(false);
    expect(isServerDryRun("PUT /lessons/slugs", {})).toBe(false);
    expect(cliRoute("PUT /lessons/slugs").idempotency).toBe("required");
    const change = { lessonId: "lesson-1", slug: "a" };
    expect(lessonSlugsPut.safeParse({ courseId: "course-1", expectedRevision: 1, changes: [] }).success).toBe(false);
    expect(lessonSlugsPut.safeParse({ courseId: "course-1", expectedRevision: 1, changes: Array.from({ length: 2001 }, () => change) }).success).toBe(false);
    expect(lessonSlugsPut.safeParse({ courseId: "course-1", expectedRevision: 1, changes: [{ ...change, slug: "Bad" }] }).success).toBe(false);
  });
});
