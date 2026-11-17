import { expect, it } from "vitest";
import { syntheticCatalog, syntheticTables } from "../testing/synthetic.ts";
import { jsonText } from "../../../scripts/lib/catalog-files.ts";
import { compileRelease } from "./compile.ts";
import type { MediaAsset } from "../../media/domain/types.ts";
import { redundantLessons, resolveCover, type CoverNodeKind, type CoverSources } from "./cover-resolve.ts";

const asset = (kind: string, id = kind) => ({ kind, id });
const nodes: CoverNodeKind[] = ["institution", "area", "subarea", "course", "lesson"];

it.each(nodes)("INV-M2: %s prefers its own active kind and variant", (target) => {
  const own = asset("poster_9x16", target);
  const sources = Object.fromEntries(nodes.map((node) => [node, [asset("poster_9x16", node)]]));
  const coverFrom = target === "course" || target === "lesson" ? "own" : undefined;
  expect(resolveCover({ ...sources, [target]: [{ ...own, isActive: false }, { ...own, variant: "alternate" }, own], coverFrom, courseId: "course" }, { target, kind: "poster_9x16" })).toBe(own);
});

it("D-014: never resolves a course cover from its institution", () => {
  expect(resolveCover({ institution: [asset("poster_9x16")], coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBeUndefined();
  expect(resolveCover({ institution: [asset("poster_9x16")], area: [asset("poster_9x16", "area")], coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBeUndefined();
});

it("D-031: a course reads only its declared owner and does not walk", () => {
  const area = [asset("poster_9x16", "area")];
  const subarea = [asset("poster_9x16", "subarea")];
  const course = [asset("poster_9x16", "course")];
  expect(resolveCover({ area, coverFrom: "area:physics", courseId: "course-1" }, { target: "course" })).toBe(area[0]);
  expect(resolveCover({ area, subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course" })).toBe(subarea[0]);
  expect(resolveCover({ area, subarea, course, coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBe(course[0]);
  expect(resolveCover({ area, subarea, coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBeUndefined();
  expect(resolveCover({ area, subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course" })).toBe(subarea[0]);
  expect(resolveCover({ area }, { target: "subarea" })).toBeUndefined();
  expect(resolveCover({ area: [asset("lesson_default")], subarea: [asset("lesson_default", "subarea")], coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "lesson" })?.id).toBe("subarea");
  expect(resolveCover({ area: [asset("lesson_default")], course: [asset("still_16x9", "course")], coverFrom: "own", courseId: "course-1" }, { target: "lesson" })?.id).toBe("course");
});

it("D-031: a lesson fallback is the declared owner, and its own frame still wins", () => {
  const lesson = asset("cover_16x9", "lesson");
  const subarea = asset("lesson_default", "subarea");
  expect(resolveCover({ lesson: [lesson], subarea: [subarea], coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "lesson" })).toBe(lesson);
  expect(resolveCover({ area: [asset("lesson_default", "area")], coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "lesson" })).toBeUndefined();
});

it("INV-M2: a declaration never resolves from a descendant or another owner", () => {
  let seed = 741;
  const random = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32;
  const tokens = ["own", "subarea:mechanics", "area:physics"] as const;
  for (let tree = 0; tree < 300; tree++) {
    const sources: CoverSources<ReturnType<typeof asset>> = {
      institution: random() < 0.5 ? [asset("poster_9x16", "institution")] : [],
      area: random() < 0.5 ? [asset("poster_9x16", "area")] : [],
      subarea: random() < 0.5 ? [asset("poster_9x16", "subarea")] : [],
      course: random() < 0.5 ? [asset("poster_9x16", "course")] : [],
      lesson: random() < 0.5 ? [asset("poster_9x16", "lesson")] : [],
    };
    const coverFrom = tokens[Math.floor(random() * tokens.length)] ?? "own";
    const resolved = resolveCover({ ...sources, coverFrom, courseId: "course-1" }, { target: "course", kind: "poster_9x16" });
    const ownerId = coverFrom === "own" ? "course" : coverFrom.startsWith("subarea:") ? "subarea" : "area";
    const present = (coverFrom === "own" ? sources.course : coverFrom.startsWith("subarea:") ? sources.subarea : sources.area) ?? [];
    expect(resolved?.id).toBe(present.length > 0 ? ownerId : undefined);
    expect(resolved?.id).not.toBe("institution");
    expect(resolved?.id).not.toBe("lesson");
  }
});

it("INV-M3: current schema compiles synthetic tables deterministically", () => {
  const actual = compileRelease(syntheticTables(), { number: syntheticCatalog.number, publishedAt: syntheticCatalog.publishedAt });
  expect(jsonText(actual)).toBe(jsonText(syntheticCatalog));
});

it("INV-M3: resolves share art on the declared owner and never borrows another owner", () => {
  const poster = asset("poster_9x16");
  const og = asset("og");
  expect(resolveCover({ institution: [poster, og] }, { target: "institution", presentation: "share" })).toBe(og);
  expect(resolveCover({ institution: [poster], course: [og], coverFrom: "own", courseId: "course-1" }, { target: "institution", presentation: "share" })).toBe(poster);
  expect(resolveCover({ course: [asset("still_16x9", "course")], area: [asset("og", "area")], coverFrom: "own", courseId: "course-1" }, { target: "course", presentation: "share" })).toMatchObject({ id: "course" });
  expect(resolveCover({ course: [asset("still_16x9", "course")], area: [asset("og", "area")], coverFrom: "area:physics", courseId: "course-1" }, { target: "course", presentation: "share" })).toMatchObject({ id: "area" });
});

it("returns only the lesson frames whose sha matches the declared owner", () => {
  const sha = "a".repeat(64);
  const frame = { kind: "lesson_default", variant: "default", sha256: sha, ownerId: "sub", isActive: true } as MediaAsset;
  const copy = { kind: "cover_16x9", variant: "default", sha256: sha, ownerId: "lesson-1", isActive: true } as MediaAsset;
  const other = { kind: "cover_16x9", variant: "default", sha256: "b".repeat(64), ownerId: "lesson-2", isActive: true } as MediaAsset;
  const found = redundantLessons({
    courses: [{ id: "course-1", subarea_id: "sub", cover_from: "subarea:sub" }],
    lessons: [{ id: "lesson-1", course_id: "course-1" }, { id: "lesson-2", course_id: "course-1" }],
    courseAssets: new Map(),
    subareaAssets: new Map([["sub", [frame]]]),
    lessonAssets: [copy, other],
  });
  expect(found.map((item) => item.asset.sha256)).toEqual([sha]);
  expect(found.map((item) => item.inherited.sha256)).toEqual([sha]);
});
