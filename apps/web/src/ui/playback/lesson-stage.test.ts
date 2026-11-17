import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { authorOf, courseBySlug, editionOf, lessonBySlug } from "@/catalog/domain/queries.ts";
import { fakeCatalog, TEST_EDITIONS_COURSE } from "@/catalog/testing/fake.ts";
import type { MediaAsset } from "@/media/domain/types.ts";
import type { ProgressRow } from "@/progress/domain/rules.ts";
import type { CourseProgressView } from "@/progress/domain/view.ts";
import { lessonStage } from "./lesson-stage.ts";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

function cover(url: string): MediaAsset {
  return { ownerId: "lesson", kind: "cover_16x9", variant: "default", url, isActive: true } as MediaAsset;
}

function row(patch: Partial<ProgressRow> & Pick<ProgressRow, "lessonId">): ProgressRow {
  return { positionSeconds: 0, durationSeconds: null, completed: false, updatedAt: 1, ...patch };
}

function open(courseSlug: string, lessonSlug: string, extra: { readonly t?: string; readonly viewerRows?: readonly ProgressRow[]; readonly progress?: CourseProgressView; readonly figures?: ReadonlyMap<string, readonly MediaAsset[]> } = {}) {
  const course = courseBySlug(fakeCatalog, courseSlug);
  const lesson = course ? lessonBySlug(fakeCatalog, course.id, lessonSlug) : undefined;
  const author = course ? authorOf(fakeCatalog, course) : undefined;
  const edition = lesson ? editionOf(fakeCatalog, lesson) : undefined;
  if (!course || !lesson || !author || !edition) throw new Error(`missing ${courseSlug}/${lessonSlug}`);
  return lessonStage({
    catalog: fakeCatalog, course, lesson, edition, author,
    figures: extra.figures ?? new Map(),
    t: extra.t,
    ...(extra.viewerRows ? { viewerRows: extra.viewerRows } : {}),
    ...(extra.progress ? { progress: extra.progress } : {}),
  });
}

const progress: CourseProgressView = {
  cta: { kind: "resume", href: "/c/test-two-editions/edition-test-2?t=40", lesson: "Lecture 2" },
  card: null,
  watched: { count: 1, total: 5, percent: "20%", fraction: 0.2 },
  watchedIds: ["lesson-test-1"],
  current: { lessonId: "lesson-test-2", remaining: "22m left" },
  lastActivity: 4,
};

describe("lesson stage", () => {
  it("matches the one-edition page: kicker, duration, next, and a signed-out start at zero", () => {
    const stage = open("fixture-course-1", "fixture-lesson-1", {
      t: "90",
      figures: new Map([["lesson-1", [cover("https://media.example/covers/lesson-1/own.webp")]]]),
    });
    expect(stage.kicker).toBe("Lecture 1 of 17 · Fixture Course 1");
    expect(stage.duration).toBe("1h 00m");
    expect(stage.title).toBe("1: Fixture Lesson");
    expect(stage.author).toBe("Fixture Lecturer 1");
    expect(stage.previous).toBeUndefined();
    expect(stage.next).toEqual({ href: "/c/fixture-course-1/fixture-lesson-2", label: "Next" });
    expect(stage.backLabel).toBe("Back to course");
    expect(stage.editionLabel).toBeNull();
    expect(stage.second).toBe(90);
    expect(stage.startAt).toBe(0);
    expect(stage.poster?.url).toBe("https://media.example/covers/lesson-1/own.webp");
    expect(stage.source).toEqual({ youtubeId: "fx000000001" });
    expect(stage.rows[0]).toMatchObject({ label: "Lecture 1", duration: "1h 00m", href: "/c/fixture-course-1/fixture-lesson-1" });
    expect(stage.rows[8]).toMatchObject({ id: "lesson-9", label: "Background 9", duration: "1h 00m" });
    expect(stage.about).toBe("A synthetic lesson description with enough detail to exercise canonical metadata and display limits.");
  });

  it("matches the last lesson: previous, and Back to course when there is no next", () => {
    const stage = open("fixture-course-1", "fixture-lesson-17");
    expect(stage.kicker).toBe("Lecture 17 of 17 · Fixture Course 1");
    expect(stage.previous).toEqual({ href: "/c/fixture-course-1/fixture-lesson-16", label: "Previous" });
    expect(stage.next).toBeUndefined();
    expect(stage.backLabel).toBe("Back to course");
    expect(stage.courseHref).toBe("/c/fixture-course-1");
  });

  it("matches the two-edition page: the edition kicker, the part label, and the resume second", () => {
    const figures = new Map<string, readonly MediaAsset[]>();
    const first = open(TEST_EDITIONS_COURSE.slug, "edition-test-1", { progress, figures });
    const last = open(TEST_EDITIONS_COURSE.slug, "edition-test-3", {
      progress,
      viewerRows: [row({ lessonId: "lesson-test-3", positionSeconds: 40, durationSeconds: 50 })],
      t: "90",
    });
    expect(first.kicker).toBe("Spring 2025 · Lecture 1 of 3 · Two Editions");
    expect(first.duration).toBe("30m");
    expect(first.previous).toBeUndefined();
    expect(first.next).toEqual({ href: "/c/test-two-editions/edition-test-2", label: "Next" });
    expect(first.editionLabel).toBe("Spring 2025");
    expect(first.count).toBe("2 lectures + 1 labs");
    expect(first.rows[0]).toMatchObject({ status: "watched", duration: "30m", label: "Lecture 1" });
    expect(first.rows[2]).toMatchObject({ label: "Lab 3", title: "Lab 3: Practice" });
    expect(first.watched).toEqual({ count: 1, total: 3, percent: "33%", fraction: 1 / 3 });
    expect(last.kicker).toBe("Spring 2025 · Lab 3 of 3 · Two Editions");
    expect(last.previous).toEqual({ href: "/c/test-two-editions/edition-test-2", label: "Previous" });
    expect(last.next).toBeUndefined();
    expect(last.second).toBe(90);
    expect(last.startAt).toBe(50);
  });

  it("resumes a signed-in viewer from the saved second, from ?t=, or from zero when the lesson is done", () => {
    const saved = row({ lessonId: "lesson-1", positionSeconds: 40, durationSeconds: 3600 });
    expect(open("fixture-course-1", "fixture-lesson-1", { viewerRows: [saved] })).toMatchObject({ second: 0, startAt: 40, completed: false });
    expect(open("fixture-course-1", "fixture-lesson-1", { viewerRows: [saved], t: "15" })).toMatchObject({ second: 15, startAt: 15 });
    expect(open("fixture-course-1", "fixture-lesson-1", { viewerRows: [row({ lessonId: "lesson-1", positionSeconds: 40, completed: true })] })).toMatchObject({ startAt: 0, completed: true });
    expect(open("fixture-course-1", "fixture-lesson-1", { viewerRows: [], t: "99999" })).toMatchObject({ second: 3600, startAt: 3600 });
  });

  it("chooses no cover of its own", () => {
    const text = source("./lesson-stage.ts");
    expect(text).not.toMatch(/\bresolveCover\b|\bpickAsset\b/);
    expect(text).toContain("chosenLessonCover");
    expect(text).toContain("lessonStartSecond");
  });

  it("leaves the paint file with no neighbor or start-second choice", () => {
    const page = source("../../app/c/[courseSlug]/[lessonSlug]/view.tsx");
    expect(page).not.toMatch(/\blessonNeighbors\b|\bpickAsset\b|\blessonStartSecond\b/);
    expect(page).toContain("lessonStage");
    expect(page).toContain("@/ui/playback/LectureAbout");
    expect(page).not.toContain("@/ui/LectureAbout/");
  });

  it("measures the lecture sheet from the player family", () => {
    const measures = source("../tokens/screen-measures.test.ts");
    expect(measures).toContain("src/ui/playback/LectureAbout.module.css");
    expect(measures).not.toContain("src/ui/LectureAbout/LectureAbout.module.css");
  });
});
