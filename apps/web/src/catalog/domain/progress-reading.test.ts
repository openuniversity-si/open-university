import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { lessonsForCourse } from "./queries.ts";
import { snapshotCatalog } from "../testing/fake.ts";
import { catalogProgressViews, courseReading } from "../server/progress-reading.ts";

const surfaces = [
  "./home.ts",
  "./view-model.ts",
  "../../app/page.tsx",
  "../../app/signed-in-home/page.tsx",
  "../../app/c/[courseSlug]/(course)/view.tsx",
  "../../app/c/[courseSlug]/[lessonSlug]/view.tsx",
];

describe("one progress reading", () => {
  it("gives Home and a course the same reading, and the surfaces only place it", () => {
    const course = snapshotCatalog.courses.find((entry) => lessonsForCourse(snapshotCatalog, entry.id).length > 0);
    if (!course) throw new Error("A course with a lesson is required.");
    const rows = [{ lessonId: lessonsForCourse(snapshotCatalog, course.id)[0]?.id ?? "", positionSeconds: 12, durationSeconds: 90, completed: false, updatedAt: 4 }];
    const reading = courseReading(snapshotCatalog, course, rows);
    expect(catalogProgressViews(snapshotCatalog, rows).get(course.id)).toEqual(reading);
    const readingSource = readFileSync(new URL("../server/progress-reading.ts", import.meta.url), "utf8");
    expect(readingSource.match(/courseProgressView\(/g)).toHaveLength(1);
    for (const path of surfaces) {
      expect(readFileSync(new URL(path, import.meta.url), "utf8"), path).not.toContain("courseProgressView(");
    }
    const home = readFileSync(new URL("../../app/signed-in-home/page.tsx", import.meta.url), "utf8");
    const offer = readFileSync(new URL("../../app/page.tsx", import.meta.url), "utf8");
    expect(home).toContain("catalogProgressViews");
    expect(offer).not.toContain("catalogProgressViews");
    expect(offer).not.toContain("courseReading");
    const bridge = readFileSync(new URL("../../playback/client/progress-bridge.ts", import.meta.url), "utf8");
    expect(bridge).toContain("completed: true");
  });
});
