import { describe, expect, it } from "vitest";
import type { ProgressRow } from "../../progress/domain/rules.ts";
import { catalogProgressViews, courseReading } from "./progress-reading.ts";
import { lessonsForCourse, signedInHome, snapshotCatalog as catalog } from "../../../test/fixtures/progress-oracle.ts";

const genesis = catalog.courses.find((course) => course.id === "course-1");
if (!genesis) throw new Error("Genesis is required.");
const done = (lessonId: string, updatedAt = 1): ProgressRow => ({ lessonId, positionSeconds: 0, durationSeconds: null, completed: true, updatedAt });
const spec06: ProgressRow[] = [done("lesson-1"), done("lesson-2"), done("lesson-3"),
  { lessonId: "lesson-4", positionSeconds: 3134, durationSeconds: 9128, completed: false, updatedAt: 20 },
  { lessonId: "lesson-54", positionSeconds: 2520, durationSeconds: 6000, completed: false, updatedAt: 30 },
  { lessonId: "lesson-147", positionSeconds: 1347, durationSeconds: 3207, completed: false, updatedAt: 10 }];

describe("progress reading at the page", () => {
  it("keeps the resume second, the watched count, and the continue order", () => {
    const reading = courseReading(catalog, genesis, spec06);
    expect(reading.cta.href).toContain("?t=3134");
    expect(reading.watched).toMatchObject({ count: 3, total: 17 });
    const rows = [...spec06, ...lessonsForCourse(catalog, "course-5").map((lesson) => done(lesson.id, 99))];
    const home = signedInHome(catalog, new Map(), catalogProgressViews(catalog, rows));
    expect(home.continueWatching.map((course) => course.id)).toEqual(["course-2", "course-1", "course-4"]);
  });
});
