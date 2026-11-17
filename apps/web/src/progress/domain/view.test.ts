import { describe, expect, it } from "vitest";
import type { ProgressRow } from "./rules.ts";
import { catalogProgressViews, lessonsForCourse, progressViewCourse, signedInHome, snapshotCatalog as catalog } from "../../../test/fixtures/progress-oracle.ts";
import { courseProgressView } from "./view.ts";

const genesis = catalog.courses.find((course) => course.id === "course-1");
if (!genesis) throw new Error("Genesis is required.");
const done = (lessonId: string, updatedAt = 1): ProgressRow => ({ lessonId, positionSeconds: 0, durationSeconds: null, completed: true, updatedAt });
const spec06: ProgressRow[] = [done("lesson-1"), done("lesson-2"), done("lesson-3"),
  { lessonId: "lesson-4", positionSeconds: 3134, durationSeconds: 9128, completed: false, updatedAt: 20 },
  { lessonId: "lesson-54", positionSeconds: 2520, durationSeconds: 6000, completed: false, updatedAt: 30 },
  { lessonId: "lesson-147", positionSeconds: 1347, durationSeconds: 3207, completed: false, updatedAt: 10 }];

describe("courseProgressView", () => {
  it("Spec 06 Genesis: Resume · Lecture 4 at 52:14, card, Current row and 3 of 17 (18%)", () => {
    const view = courseProgressView(progressViewCourse(catalog, genesis), spec06);
    const lesson4 = lessonsForCourse(catalog, genesis.id)[3];
    expect(view.cta).toEqual({ kind: "resume", href: `/c/${genesis.slug}/${lesson4?.slug ?? ""}?t=3134`, lesson: "Lecture 4" });
    expect(view.card).toMatchObject({ label: "Lecture 4 of 17", remaining: "1h 40m left", href: view.cta.href });
    expect(view.watched).toMatchObject({ count: 3, total: 17, percent: "18%" });
    expect(view.current).toEqual({ lessonId: "lesson-4", remaining: "1h 40m left" });
    expect(view.watchedIds).toEqual(["lesson-1", "lesson-2", "lesson-3"]);
  });

  it("D4: everything watched → Start at lesson 1, no card, checks kept", () => {
    const lessons = lessonsForCourse(catalog, genesis.id);
    const view = courseProgressView(progressViewCourse(catalog, genesis), lessons.map((lesson) => done(lesson.id)));
    expect(view.cta).toEqual({ kind: "start", href: `/c/${genesis.slug}/${lessons[0]?.slug ?? ""}`, lesson: "Lecture 1" });
    expect(view.card).toBeNull();
    expect(view.watchedIds).toHaveLength(17);
  });
});

describe("signedInHome", () => {
  it("Continue Watching holds started, unfinished courses, most recent first, with their progress", () => {
    const rows = [...spec06, ...lessonsForCourse(catalog, "course-5").map((lesson) => done(lesson.id, 99))];
    const home = signedInHome(catalog, new Map(), catalogProgressViews(catalog, rows));
    expect(home.continueWatching.map((course) => course.id)).toEqual(["course-2", "course-1", "course-4"]);
    expect(home.continueWatching[2]?.progress?.card?.label).toBe("Episode 12 of 51");
    expect(home.featured?.progress?.cta.kind).toBe("resume");
    expect(home.rails.flatMap((rail) => rail.courses).find((course) => course.id === "course-5")?.progress?.cta.kind).toBe("start");
  });
});
