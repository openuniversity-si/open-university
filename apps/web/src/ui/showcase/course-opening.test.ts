import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { authorOf, courseBySlug, editionsForCourse } from "@/catalog/domain/queries.ts";
import { fakeCatalog, TEST_EDITIONS_COURSE } from "@/catalog/testing/fake.ts";
import type { MediaAsset } from "@/media/domain/types.ts";
import type { CourseProgressView } from "@/progress/domain/view.ts";
import { courseOpening } from "./course-opening.ts";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

function cover(url: string): MediaAsset {
  return { ownerId: "lesson", kind: "cover_16x9", variant: "default", url, isActive: true } as MediaAsset;
}

function open(slug: string, lessons: ReadonlyMap<string, readonly MediaAsset[]> = new Map(), progress?: CourseProgressView) {
  const course = courseBySlug(fakeCatalog, slug);
  const author = course ? authorOf(fakeCatalog, course) : undefined;
  if (!course || !author) throw new Error(`missing ${slug}`);
  return courseOpening({
    catalog: fakeCatalog,
    course,
    figures: { lessons, courses: new Map() },
    author,
    editions: editionsForCourse(course),
    ...(progress ? { progress } : {}),
  });
}

describe("course opening", () => {
  it("matches the one-edition page: meta, summary, duration, and the author's other cards", () => {
    const opening = open("fixture-course-1", new Map([["lesson-1", [cover("https://media.example/covers/lesson-1/own.webp")]]]));
    const [edition] = opening.editions;
    if (!edition) throw new Error("missing edition");
    const [first] = edition.rows;
    const background = edition.rows.find((row) => row.id === "lesson-9");

    expect(edition.meta).toBe("17 lectures  ·  17h  ·  Intermediate  ·  English");
    expect(edition.metaMobile).toBe("17 lectures  ·  17h  ·  Intermediate");
    expect(edition.summary).toBe("2026  ·  17 lectures  ·  17.0 h");
    expect(edition.parts).toBeUndefined();
    expect(edition.hours).toBe(17);
    expect(first).toMatchObject({
      id: "lesson-1", href: "/c/fixture-course-1/fixture-lesson-1", title: "1: Fixture Lesson", label: "Lecture", duration: "1h 00m",
    });
    expect(first).not.toHaveProperty("status");
    expect(first).not.toHaveProperty("currentMeta");
    expect(edition.covers[0]?.url).toBe("https://media.example/covers/lesson-1/own.webp");
    expect(background).toMatchObject({
      href: "/c/fixture-course-1/fixture-lesson-9", title: "9: Fixture Lesson", label: "Background", duration: "1h 00m",
    });
    expect(opening.moreTitle).toBe("More from Fixture Lecturer 1");
    expect(opening.more.map((card) => card.id)).toEqual(["course-2", "course-3"]);
    expect(opening.more.map((card) => card.title)).toEqual(["Fixture Course 2", "Fixture Course 3"]);
  });

  it("matches the two-edition page: part labels, the one-decimal summary, and the current lesson's resume", () => {
    const progress: CourseProgressView = {
      cta: { kind: "resume", href: "/c/test-two-editions/edition-test-2?t=40", lesson: "Lecture 2" },
      card: null,
      watched: { count: 1, total: 5, percent: "20%", fraction: 0.2 },
      watchedIds: ["lesson-test-1"],
      current: { lessonId: "lesson-test-2", remaining: "22m left" },
      lastActivity: 4,
    };
    const opening = open(TEST_EDITIONS_COURSE.slug, new Map(), progress);
    const [spring, fall] = opening.editions;
    if (!spring || !fall) throw new Error("missing editions");
    const [first, current, lab] = spring.rows;

    expect(spring.meta).toBe("2 lectures + 1 labs  ·  2h  ·  Intermediate  ·  English");
    expect(spring.metaMobile).toBe("2 lectures + 1 labs  ·  2h  ·  Intermediate");
    expect(spring.summary).toBe("Spring 2025  ·  2 lectures + 1 labs  ·  1.5 h");
    expect(spring.parts).toEqual([{ label: "Lectures · 2", from: 0 }, { label: "Labs · 1", from: 2 }]);
    expect(spring.watched).toEqual({ count: 1, total: 3, percent: "33%", fraction: 1 / 3 });
    expect(first).toMatchObject({ href: "/c/test-two-editions/edition-test-1", title: "Lecture 1: Spring test", label: "Lecture", duration: "30m", status: "watched" });
    expect(current).toMatchObject({
      href: "/c/test-two-editions/edition-test-2?t=40", title: "Lecture 2: Spring test", label: "Lecture", duration: "30m", status: "current", currentMeta: "Resume · 22m left",
    });
    expect(current?.href).toBe(progress.cta.href);
    expect(lab).toMatchObject({ href: "/c/test-two-editions/edition-test-3", title: "Lab 3: Practice", label: "Lab", duration: "30m" });
    expect(lab).not.toHaveProperty("status");
    expect(fall.meta).toBe("2 lectures  ·  1h  ·  Intermediate  ·  English");
    expect(fall.summary).toBe("Fall 2024  ·  2 lectures  ·  1.0 h");
    expect(fall.parts).toBeUndefined();
    expect(fall.watched).toEqual({ count: 0, total: 2, percent: "0%", fraction: 0 });
    expect(opening.moreTitle).toBe("More from Fixture Lecturer 2");
    expect(opening.more.map((card) => card.id)).toEqual(["course-4", "course-5"]);
  });

  it("writes the row duration itself and does not import the player", () => {
    const text = source("./course-opening.ts");
    expect(text).not.toMatch(/lessonDuration|ui\/playback/);
    expect(text).toContain("toFixed(1)");
    expect(text).toContain("Math.round");
  });

  it("leaves the paint file with no offering arithmetic", () => {
    const page = source("../../app/c/[courseSlug]/(course)/view.tsx");
    expect(page).not.toMatch(/\bdurationSeconds\b|\blessonsForEdition\b/);
    expect(page).toContain("courseOpening");
  });
});
