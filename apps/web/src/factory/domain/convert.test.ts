import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { planBatch, type BatchRefs } from "../../catalog/domain/batch-plan.ts";
import { validateCourseBundle } from "../../catalog/domain/bundle.ts";
import { AppError } from "../../kernel/errors.ts";
import { parseCurated, type CuratedV1 } from "./curated.ts";
import { convertCurated, curatedToBatch, type ConvertIssue } from "./convert.ts";
import { GENERATOR_ACTOR, REVIEWER_ACTOR, generateTexts, reviewTexts } from "./texts.ts";
import type { CatalogBatchV2 } from "../../catalog/domain/schema/batch-v2.ts";

function bundleOf(course: CatalogBatchV2["courses"][number], author: CatalogBatchV2["lecturers"][number]) {
  const parsed = validateCourseBundle({
    version: 1,
    author,
    course: course.course,
    editions: course.editions,
    lessons: course.lessons,
    texts: course.texts,
    home: null,
    covers: course.covers.map((cover) => ({ kind: cover.kind, path: `covers/${cover.sha}.webp` })),
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

const sha = (digit: string) => digit.repeat(64);
const channel = `UC${"a".repeat(22)}`;
const lecturer = { id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" as const };
const coverCredit = { alt: "Universidade de São Paulo", credit: "Photo: USP", sourceUrl: "https://www.usp.br", license: "CC BY 4.0" };
const stored: BatchRefs = {
  sources: new Map(), authors: new Map(),
  areas: new Map([["physics", { title: "Physics" }], ["mathematics", { title: "Mathematics" }]]),
  subareas: new Map([["mechanics", { areaId: "physics", title: "Mechanics" }]]),
  homeRows: new Map([["iit-madras", { institutionId: "iit", title: "IIT Madras" }]]),
  courses: new Map(), licenses: new Set(["youtube-standard"]), covers: new Map(),
  media: new Set([sha("a"), sha("b"), sha("c"), sha("d"), sha("e"), sha("f"), sha("1")]),
};

function lesson(position: number, youtubeId: string, title: string) {
  return { youtubeId, originalTitle: title, durationSeconds: 3120, uploadDate: "2021-03-02", position, part: "lectures" as const };
}

function course(extra: Record<string, unknown> = {}) {
  return {
    sourcePlaylistId: "PLmecanica01", decision: "include", id: "usp-mecanica-geral", slug: "mecanica-geral",
    title: "Mecânica Geral", originalTitle: "Mecânica Geral - 2021", language: "Portuguese", areaId: "physics", subareaId: "mechanics",
    license: "youtube-standard", rights: "accepted-risk", canonicalUrl: "https://www.youtube.com/playlist?list=PLmecanica01",
    year: 2021, coverFrom: "own", sharedWith: [] as string[],
    cover: { poster: sha("a"), heroes: { desktop: sha("e"), present: sha("f"), mobile: sha("1"), still: sha("d") } }, lecturer,
    lessons: [lesson(1, "abcdefghijk", "Mecânica Geral - Aula 01"), lesson(2, "bcdefghijkl", "Mecânica Geral - Aula 02")],
    ...extra,
  };
}

const areaCover = { poster: sha("a"), heroDesktop: sha("e"), heroPresent: sha("f"), heroMobile: sha("1") };

function curated(courses: unknown[], extra: Record<string, unknown> = {}): CuratedV1 {
  const parsed = parseCurated({
    format: "curated/v1",
    run: { id: "brasil-2026-10-22", createdAt: "2026-10-22T10:00:00-03:00", adapter: "youtube-playlist@1" },
    institution: {
      id: "usp", slug: "usp", name: "USP", fullName: "Universidade de São Paulo", place: "São Paulo, Brazil",
      kind: "institution", monogram: "USP", cover: { poster: sha("b"), og: sha("c"), ...coverCredit }, homeRow: { after: "iit-madras", visible: true },
    },
    sources: [{ id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp", youtubeChannelId: channel }],
    courses,
    provenance: { titles: "original", fetchedAt: "2026-10-22T10:00:00-03:00", counts: { videos: 4, skippedScheduled: 1 } },
    ...extra,
  });
  if (!parsed.ok) throw new Error(parsed.issues.map((issue) => issue.message).join("\n"));
  return parsed.value;
}

function issuesOf(error: unknown): ConvertIssue[] {
  expect(error).toBeInstanceOf(AppError);
  const details = (error as AppError).details as { issues?: ConvertIssue[] };
  return details.issues ?? [];
}

describe("curatedToBatch", () => {
  it("converts a Brazil-shaped run into a batch whose courses the bundle schema accepts", () => {
    const input = curated([
      course(),
      course({
        sourcePlaylistId: "PLcalculo0001", id: "usp-calculo", slug: "calculo", title: "Cálculo I", originalTitle: "Cálculo I - 2020",
        areaId: "mathematics", subareaId: null, canonicalUrl: "https://www.youtube.com/playlist?list=PLcalculo0001",
        coverFrom: "area:mathematics", cover: undefined, lessons: [lesson(1, "cdefghijklm", "Cálculo I - Aula 01")],
      }),
      { sourcePlaylistId: "PLalgebra001", decision: "hold", holdReason: "needs-title", title: "Álgebra" },
      { sourcePlaylistId: "PLbare000001", decision: "hold", holdReason: "needs-title" },
      { sourcePlaylistId: "PLexcluded01", decision: "exclude" },
    ], { areas: [{ id: "mathematics", title: "Mathematics", cover: areaCover }], licenses: [{ code: "cc-by", name: "CC BY", url: "https://creativecommons.org/licenses/by/4.0/", requiresAttribution: true }] });
    const conversion = convertCurated(input, [{ entityKind: "course", entityId: "usp-mecanica-geral", field: "description", text: "Aulas de mecânica.", approved: false }]);
    expect(conversion.held).toEqual([{ course: "Álgebra", reason: "needs-title" }, { course: "unnamed", reason: "needs-title" }]);
    expect(conversion.excluded).toBe(1);
    const batch = conversion.batch;
    expect(batch.version).toBe(2);
    expect(batch.sources[0]).toMatchObject({ id: "yt-usp", kind: "youtube-channel", youtubeChannelId: channel });
    expect(batch.institutions[0]).toEqual({ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: sha("b"), og: sha("c") } });
    expect(batch.lecturers).toEqual([lecturer]);
    expect(batch.homeRows[0]).toMatchObject({ id: "usp", institutionId: "usp", fullName: "Universidade de São Paulo", after: "iit-madras", cover: { sha: sha("b"), ...coverCredit }, og: sha("c") });
    expect(planBatch(batch, stored).failures).toEqual([]);
    expect(batch.courses.map((entry) => entry.course.id)).toEqual(["usp-calculo", "usp-mecanica-geral"]);
    const mechanics = batch.courses.find((entry) => entry.course.id === "usp-mecanica-geral");
    const calculus = batch.courses.find((entry) => entry.course.id === "usp-calculo");
    if (!mechanics || !calculus) throw new Error("missing course");
    expect(mechanics.lessons.map((entry) => entry.title)).toEqual(["Mecânica Geral - Aula 01", "Mecânica Geral - Aula 02"]);
    expect(mechanics.editions[0]?.year).toBe(2021);
    expect(mechanics.covers).toEqual([
      { kind: "hero_desktop_16x9", sha: sha("e") },
      { kind: "hero_mobile_9x16", sha: sha("1") },
      { kind: "hero_present", sha: sha("f") },
      { kind: "poster_9x16", sha: sha("a") },
      { kind: "still_16x9", sha: sha("d") },
    ]);
    expect(mechanics.texts).toEqual([{ entityKind: "course", entityId: "usp-mecanica-geral", field: "description", text: "Aulas de mecânica.", approved: false, approvedBy: null, approvedAt: null }]);
    expect(mechanics.course.coverFrom).toBe("own");
    expect(calculus.course.coverFrom).toBe("area:mathematics");
    expect(calculus.covers).toEqual([]);
    expect(calculus.course.areaId).toBe("mathematics");
    expect(calculus.course.subareaId).toBeNull();
    expect(batch.areas[0]).toMatchObject({ id: "mathematics", cover: areaCover });
    expect(batch.licenses[0]?.code).toBe("cc-by");
    expect(mechanics.institutionId).toBe("usp");
    expect(mechanics.course.authorId).toBe("ana-lima");
    expect(mechanics.homeRowId).toBe("usp");
    expect(bundleOf(mechanics, lecturer).course.title).toBe("Mecânica Geral");
    expect(bundleOf(calculus, lecturer).course.coverFrom).toBe("area:mathematics");
    expect(batch.courses.some((entry) => entry.course.id === "Álgebra" || entry.course.title === "Álgebra")).toBe(false);
  });

  it("carries a lesson fact into the batch through the lesson link", () => {
    const batch = curatedToBatch(curated([course({ lessons: [lesson(1, "abcdefghijk", "Mecânica Geral - Aula 01")] })]));
    expect(batch.courses[0]?.lessons[0]).toMatchObject({
      title: "Mecânica Geral - Aula 01", youtubeId: "abcdefghijk", durationSeconds: 3120, position: 1, part: "lectures",
    });
    const source = readFileSync(new URL("./convert.ts", import.meta.url), "utf8");
    const link = readFileSync(new URL("./lesson-link.ts", import.meta.url), "utf8");
    expect(source).toContain("lessonLink(");
    expect(link).toContain("lesson.youtubeId");
    expect(link).toContain("lesson.durationSeconds");
    expect(link).toContain("lesson.originalTitle");
    expect(source).not.toContain("lesson.durationSeconds");
    expect(source).not.toContain("lesson.originalTitle");
    expect(source).not.toContain("cleanLessonSlug");
  });

  it("leaves a course in the unpublished batch when a publish rule would refuse it", () => {
    const mismatched = course({
      id: "usp-area-mismatch", slug: "area-mismatch", sourcePlaylistId: "PLareamismatch",
      coverFrom: "area:physics", areaId: "mathematics", subareaId: null,
    });
    const partial = course({
      id: "usp-partial-cover", slug: "partial-cover", sourcePlaylistId: "PLpartialcover",
      coverFrom: "own", cover: { poster: sha("a") },
    });
    const conversion = convertCurated(curated([mismatched, partial]));
    expect(conversion.held).toEqual([]);
    expect(conversion.batch.courses.map((entry) => entry.course.id).sort()).toEqual(["usp-area-mismatch", "usp-partial-cover"]);
    expect(JSON.stringify(conversion.batch)).not.toContain('"status":"published"');
    const source = readFileSync(new URL("./convert.ts", import.meta.url), "utf8");
    expect(source).not.toContain("validateCourseBundle");
    expect(source).not.toContain("coverDeclarationProblem");
    expect(source).not.toContain("missingCoverKinds");
  });

  it("keeps the reviewer separate and a date title unapproved", () => {
    const input = curated([course({
      lessons: [lesson(1, "abcdefghijk", "Mecânica Geral - Aula 01"), lesson(2, "bcdefghijkl", "Aula de 22/10/2026")],
    })]);
    const reviewed = reviewTexts(generateTexts([{
      id: "usp-mecanica-geral",
      title: "Mecânica Geral",
      lessons: [
        { youtubeId: "abcdefghijk", title: "Mecânica Geral - Aula 01" },
        { youtubeId: "bcdefghijkl", title: "Aula de 22/10/2026" },
      ],
    }], { language: "Portuguese", noun: "Aula" }), "2026-10-22T13:00:00.000Z");
    const batch = curatedToBatch(input, reviewed);
    const texts = batch.courses[0]?.texts ?? [];
    expect(texts.find((text) => text.text === "Aula de 22/10/2026")).toMatchObject({ approved: false, approvedBy: null, approvedAt: null });
    expect(texts.find((text) => text.text === "Mecânica Geral - Aula 01")).toMatchObject({
      approved: true, approvedBy: REVIEWER_ACTOR, approvedAt: "2026-10-22T13:00:00.000Z",
    });
    expect(texts.every((text) => text.approvedBy !== GENERATOR_ACTOR)).toBe(true);
    expect(batch.updateRefs).toBe(false);
  });

  it("derives a missing id and slug from the title", () => {
    const input = curated([course()]);
    const source = input.courses[0];
    if (!source) throw new Error("missing course");
    const batch = curatedToBatch({ ...input, courses: [{ ...source, id: undefined, slug: undefined }] });
    expect(batch.courses[0]?.course).toMatchObject({ id: "usp-mecanica-geral", slug: "mecanica-geral" });
    expect(batch.courses[0]?.editions[0]?.year).toBe(2021);
  });

  it("holds a course with no year and refuses a batch that would be empty", () => {
    const input = curated([course({ year: null })]);
    try {
      curatedToBatch(input);
      throw new Error("expected a refusal");
    } catch (error) {
      expect(issuesOf(error).map((issue) => issue.name)).toContain("courses.usp-mecanica-geral.year");
    }
    const alongside = curated([course(), course({
      id: "usp-sem-ano", slug: "sem-ano", sourcePlaylistId: "PLsemano0001", year: null,
      canonicalUrl: "https://www.youtube.com/playlist?list=PLsemano0001",
    })]);
    const conversion = convertCurated(alongside);
    expect(conversion.held.map((entry) => entry.course)).toEqual(["usp-sem-ano"]);
    expect(conversion.held[0]?.reason).toMatch(/year/);
    expect(conversion.batch.courses.map((entry) => entry.course.id)).toEqual(["usp-mecanica-geral"]);
  });

  it("names the course when a derived id does not fit", () => {
    const id = "a".repeat(62);
    const input = curated([course({ id, slug: id })]);
    try {
      curatedToBatch(input);
      throw new Error("expected a refusal");
    } catch (error) {
      const issues = issuesOf(error);
      expect(issues.map((issue) => issue.name)).toEqual(expect.arrayContaining([
        `courses.${id}.edition.id`,
        `courses.${id}.lessons.1.id`,
        `courses.${id}.lessons.2.id`,
      ]));
      expect(issues.every((issue) => issue.course === id && issue.message.includes(id))).toBe(true);
    }
  });

  it("keeps only the playlist positions in the range", () => {
    const input = curated([course({
      positions: { from: 2, to: 3 },
      lessons: [
        lesson(1, "abcdefghijk", "Aula 01"),
        lesson(2, "bcdefghijkl", "Aula 02"),
        lesson(3, "cdefghijklm", "Aula 03"),
        lesson(4, "defghijklmn", "Aula 04"),
      ],
    })]);
    const batch = curatedToBatch(input);
    expect(batch.courses[0]?.lessons.map((entry) => entry.position)).toEqual([2, 3]);
    expect(batch.courses[0]?.lessons.map((entry) => entry.title)).toEqual(["Aula 02", "Aula 03"]);
  });

  it("names the course when the position range keeps no lesson", () => {
    const input = curated([course({ positions: { from: 9, to: 10 } })]);
    try {
      curatedToBatch(input);
      throw new Error("expected a refusal");
    } catch (error) {
      expect(issuesOf(error).map((issue) => issue.name)).toContain("courses.usp-mecanica-geral.positions");
    }
  });

  it("writes a portal source as institution-site", () => {
    const input = curated([course()]);
    const batch = curatedToBatch({ ...input, sources: [{ id: "usp-site", kind: "portal", title: "USP", url: "https://www.usp.br" }] });
    expect(batch.sources[0]).toMatchObject({ id: "usp-site", kind: "institution-site" });
    expect(batch.courses[0]?.course.sourceId).toBe("usp-site");
  });

  it("refuses a lecturer that is the institution", () => {
    const input = curated([course({ lecturer: { id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "person" } })]);
    try {
      curatedToBatch(input);
      throw new Error("expected a refusal");
    } catch (error) {
      expect(issuesOf(error).map((issue) => issue.name)).toContain("courses.usp-mecanica-geral.lecturer");
    }
  });

  it("refuses a translated title even on an otherwise valid run", () => {
    const input = curated([course()]);
    const forged: CuratedV1 = { ...input, provenance: { ...input.provenance, titles: "translated" } };
    try {
      curatedToBatch(forged);
      throw new Error("expected a refusal");
    } catch (error) {
      expect(issuesOf(error).map((issue) => issue.name)).toContain("provenance.titles");
    }
  });
});
