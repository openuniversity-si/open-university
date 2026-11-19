import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { courseProgress, type ProgressLesson } from "../../../progress/domain/rules.ts";
import { unknownYearMessage, validateCourseBundle } from "../bundle.ts";
import { authorCreate, courseCreate, coursePatch, idParams, lessonCreate } from "../contracts.ts";
import { SCHEMA_DOC_PATH, renderSchemaDoc, schemaDocProblem } from "./doc.ts";
import { planBatch, type BatchRefs } from "../batch-plan.ts";
import { batchLicenseSchema, catalogBatchV2Schema } from "./batch-v2.ts";
import { publishedKeepsRights } from "../rules/status.ts";
import { ccByLicense, LIMITS, rightsStatuses } from "./fields.ts";

// Verifies: D-035
const author = { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" };
const course = { id: "course-live", slug: "contracts", title: "Contracts", authorId: "author-a", coverFrom: "own", sharedWith: [] };
const edition = { id: "edition-1", slug: "original", label: "Original", position: 1, year: 2021 };
const lesson = { id: "lesson-1", editionId: "edition-1", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 90 };
const bundle = (extra: Record<string, unknown> = {}) => ({ version: 1, author, course, editions: [edition], lessons: [lesson], ...extra });

describe("one catalog schema (INV-R1)", () => {
  it("X4: institution kind must be declared in both the route and bundle", () => {
    const { kind: _kind, ...missing } = author;
    expect(_kind).toBe("person");
    expect(authorCreate.safeParse({ slug: missing.slug, name: missing.name, monogram: missing.monogram }).success).toBe(false);
    expect(validateCourseBundle(bundle({ author: missing })).ok).toBe(false);
    expect(authorCreate.safeParse({ slug: author.slug, name: author.name, monogram: author.monogram, kind: "channel" }).success).toBe(true);
  });

  it("fails a 65-char id in a bundle and in an admin route alike, and accepts 64 in both", () => {
    const long = `course-${"x".repeat(58)}`;
    const max = long.slice(0, LIMITS.entityId);
    expect(long).toHaveLength(65);
    expect(max).toHaveLength(64);
    expect(validateCourseBundle(bundle({ course: { ...course, id: long } })).ok).toBe(false);
    expect(validateCourseBundle(bundle({ author: { ...author, id: long }, course: { ...course, authorId: long } })).ok).toBe(false);
    expect(validateCourseBundle(bundle({ lessons: [{ ...lesson, id: long }] })).ok).toBe(false);
    expect(idParams.safeParse({ id: long }).success).toBe(false);
    expect(courseCreate.safeParse({ slug: "contracts", authorId: long, title: "Contracts" }).success).toBe(false);
    expect(coursePatch.safeParse({ expectedRevision: 1, areaId: long }).success).toBe(false);
    expect(lessonCreate.safeParse({ editionId: long, youtubeId: "abcdefghijk", durationSeconds: 90 }).success).toBe(false);
    const parsed = validateCourseBundle(bundle({ course: { ...course, id: max } }));
    expect(parsed.ok && parsed.value.course.id).toBe(max);
    expect(idParams.safeParse({ id: max }).success).toBe(true);
    const refused = validateCourseBundle(bundle({ course: { ...course, id: long } }));
    expect(!refused.ok && refused.error.message).toMatch(/^course\.id: /);
  });

  it("refuses a missing or null year instead of inventing one", () => {
    const withoutYear: Record<string, unknown> = { ...edition };
    delete withoutYear.year;
    expect(validateCourseBundle(bundle({ editions: [withoutYear] })).ok).toBe(false);
    const explicit = validateCourseBundle(bundle({ editions: [{ ...edition, year: null }] }));
    expect(explicit.ok).toBe(false);
    if (!explicit.ok) expect(explicit.error.message).toMatch(/no known year/);
    const known = validateCourseBundle(bundle());
    expect(known.ok && known.value.editions[0]?.year).toBe(2021);
    expect(known.ok && unknownYearMessage(known.value)).toBeNull();
    expect(validateCourseBundle(bundle({ editions: [{ ...edition, year: 2021.5 }] })).ok).toBe(false);
    expect(validateCourseBundle(bundle({ editions: [{ ...edition, year: 1989 }] })).ok).toBe(false);
  });

  it("fails schema:check on a stale or missing doc and passes on the generated one", () => {
    const generated = renderSchemaDoc();
    expect(schemaDocProblem(generated)).toBeNull();
    expect(schemaDocProblem(generated.replace("| `entityId` | 64 |", "| `entityId` | 80 |"))).toBe(`${SCHEMA_DOC_PATH} is stale; run pnpm schema:generate.`);
    expect(schemaDocProblem(null)).toBe(`${SCHEMA_DOC_PATH} is missing; run pnpm schema:generate.`);
    expect(generated).toContain(`| \`entityId\` | ${String(LIMITS.entityId)} |`);
    expect(readFileSync(new URL(`../../../../${SCHEMA_DOC_PATH}`, import.meta.url), "utf8")).toBe(generated);
  });

  it("keeps progress separate for one video in two courses (D-003, INV-R3)", () => {
    const video = "abcdefghijk";
    const lessonsOf = (courseId: string) => {
      const parsed = validateCourseBundle(bundle({
        course: { ...course, id: courseId, slug: courseId },
        lessons: [{ ...lesson, id: `${courseId}-l1`, youtubeId: video }, { ...lesson, id: `${courseId}-l2`, slug: "next", position: 2, youtubeId: "bcdefghijkl" }],
      }));
      if (!parsed.ok) throw parsed.error;
      return parsed.value.lessons.map((entry, index): ProgressLesson => ({ id: entry.id, slug: entry.slug, order: index + 1, durationSeconds: entry.durationSeconds }));
    };
    const first = lessonsOf("course-a");
    const second = lessonsOf("course-b");
    const rows = [{ lessonId: "course-a-l1", positionSeconds: 90, durationSeconds: 90, completed: true, updatedAt: 1 }];
    expect(courseProgress(first, rows).completedIds).toEqual(new Set(["course-a-l1"]));
    expect(courseProgress(second, rows)).toMatchObject({ started: false, completedCount: 0, continueWatching: false });
    expect(courseProgress(second, rows).cta.lesson.id).toBe("course-b-l1");
  });

  it("D-035: cc-by is a valid license", () => {
    expect(rightsStatuses).not.toContain("cc-by");
    expect(batchLicenseSchema.parse(ccByLicense)).toMatchObject({ code: "cc-by", name: "CC BY 3.0", embedOnly: true });
    const parsed = catalogBatchV2Schema.parse({
      version: 2,
      licenses: [ccByLicense],
      institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "U", kind: "institution", cover: { poster: "a".repeat(64) } }],
      lecturers: [{ id: "ann", slug: "ann", name: "Ann", monogram: "A", kind: "person" }],
      courses: [{
        institutionId: "usp",
        course: {
          id: "course-cc", slug: "contracts", title: "Contracts", authorId: "ann", licenseCode: ccByLicense.code,
          languageLabel: "English", coverFrom: "own", sharedWith: [], rightsStatus: "cleared",
        },
        editions: [{ id: "edition-cc", slug: "original", label: "Original", position: 1, year: 2021, language: "English" }],
        lessons: [{ id: "lesson-cc", editionId: "edition-cc", slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 90 }],
      }],
    });
    expect(parsed.licenses[0]).toMatchObject({ code: "cc-by", name: "CC BY 3.0", embedOnly: true, url: "https://creativecommons.org/licenses/by/3.0/" });
    const refs: BatchRefs = {
      sources: new Map(), authors: new Map(), areas: new Map(), subareas: new Map(), homeRows: new Map(),
      courses: new Map(), licenses: new Set(), covers: new Map(), media: new Set(),
    };
    expect(planBatch(parsed, refs).ops).toContainEqual({ step: "license", action: "create", id: "cc-by" });
    expect(planBatch(parsed, refs).failures.map((failure) => failure.rule)).not.toContain("batch.course");
    expect(publishedKeepsRights("course-cc", { license_code: "cc-by", source_id: "src", canonical_url: "https://example.org/c", rights_status: "cleared" })).toEqual([]);
    expect(publishedKeepsRights("course-cc", { license_code: "cc-by", source_id: "src", canonical_url: "https://example.org/c", rights_status: "accepted-risk" })).toEqual([]);
  });
});
