import { describe, expect, it } from "vitest";
import { resolveCover } from "./cover-resolve.ts";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { compileRelease } from "./compile.ts";
import { assembleReleaseFromProjections, compileSingleCourseProjection, scopeCourseTables } from "./incremental-compile.ts";
import { readyCatalogFixture } from "../testing/catalog-fixture.ts";
import type { CatalogTables } from "./tables.ts";
import { assertReleaseCovers, releaseCoverErrors } from "./cover-rule.ts";
import { storedCoverErrors } from "./rules/home.ts";

const checkedAt = "2020-01-01T00:00:00.000Z";
const cover = {
  url: `https://media.openuniversity.si/covers/mit/university_cover_9x16/${"a".repeat(40)}.webp`,
  width: 1080, height: 1920, sha256: "b".repeat(64), alt: "MIT", credit: "Test", sourceUrl: "https://example.org/mit", license: "test", note: null,
};

function publishable(): CatalogTables {
  const tables = structuredClone(readyCatalogFixture().tables);
  const author = tables.authors[0];
  if (!author) throw new Error("fixture");
  author.cover = null;
  const live = tables.courses.find((course) => course.id === "course-live");
  if (!live) throw new Error("fixture");
  live.status = "published";
  for (const row of tables.catalog_texts) {
    row.status = "approved";
    row.approved_by = "editor";
    row.approved_at = checkedAt;
  }
  for (const row of [...tables.catalog_texts]) {
    if (row.entity_id === "course-ready" || row.entity_id === "lesson-ready") tables.catalog_texts.push({ ...row, entity_id: row.entity_id.replace("ready", "live") });
  }
  const liveVideo = tables.lesson_videos.find((row) => row.lesson_id === "lesson-live");
  if (liveVideo) liveVideo.external_id = "bbcdefghijk";
  return tables;
}

describe("cover direction", () => {
  it("D-031: a lesson uses its course's declared owner, and a course does not walk", () => {
    const course = [{ kind: "still_16x9", isActive: true }];
    const subarea = [{ kind: "poster_9x16", isActive: true }];
    expect(resolveCover({ course, coverFrom: "own", courseId: "course-1" }, { target: "lesson" })).toBe(course[0]);
    expect(resolveCover({ subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course" })).toBe(subarea[0]);
    expect(resolveCover({ subarea, coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBeUndefined();
    expect(resolveCover({ course, subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "lesson" })).toBeUndefined();
  });

  it("names a Universities row and an Authors row that would publish without a cover", () => {
    const release = releaseFixture();
    expect(releaseCoverErrors(release, "all")).toEqual(["Author row test-lecturer needs a cover on author-1."]);
    release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", courseIds: ["course-1"] });
    expect(releaseCoverErrors(release, "university")).toEqual(["Curated row mit needs a cover."]);
    const row = release.home.rows.find((entry) => entry.id === "mit");
    if (!row) throw new Error("mit");
    row.cover = cover;
    expect(releaseCoverErrors(release, "university")).toEqual([]);
    expect(() => { assertReleaseCovers(release, "all"); }).toThrow("Author row test-lecturer needs a cover on author-1.");
  });

  it("rejects a stored visible row that would end up without a cover, and keeps a hidden one", () => {
    const authors = new Map([["author-1", false]]);
    expect(storedCoverErrors([
      { id: "mit", kind: "curated", visible: true, cover: null, authorId: null },
      { id: "hidden", kind: "curated", visible: false, cover: null, authorId: null },
      { id: "ann", kind: "author", visible: true, cover: null, authorId: "author-1" },
    ], authors)).toEqual(["Curated row mit needs a cover.", "Author row ann needs a cover on author-1."]);
  });

  it("refuses to compile a university release without a cover, and to cut one for an author without a cover", () => {
    const tables = publishable();
    tables.home_rows.push({ id: "mit", kind: "curated", author_id: null, title: "MIT", position: 1, visible: true, cover: null, full_name: null, place: null });
    tables.home_row_items.push({ row_id: "mit", course_id: "course-live", position: 1 });
    expect(() => compileRelease(tables, { number: 2, publishedAt: checkedAt })).toThrow("Curated row mit needs a cover.");
    const row = tables.home_rows[0];
    if (!row) throw new Error("mit");
    row.cover = cover;
    expect(compileRelease(tables, { number: 2, publishedAt: checkedAt }).home.rows.find((entry) => entry.id === "mit")?.cover?.url).toBe(cover.url);
    tables.home_rows.push({ id: "ann", kind: "author", author_id: "author-a", title: null, position: 2, visible: true, cover: null, full_name: null, place: null });
    tables.home_row_items.push({ row_id: "ann", course_id: "course-live", position: 1 });
    const fresh = new Set(["course-live"]);
    const projections = tables.courses.filter((course) => course.status === "published").map((course) => compileSingleCourseProjection({
      courseId: course.id, sourceRevision: 1, tables: scopeCourseTables(tables, course.id), previous: null, fresh: fresh.has(course.id),
    }));
    // compileRelease stays able to recompile a snapshot whose author rows predate covers.
    expect(compileRelease(tables, { number: 3, publishedAt: checkedAt }).home.rows.some((entry) => entry.id === "ann")).toBe(true);
    expect(() => assembleReleaseFromProjections({ number: 3, publishedAt: checkedAt, tables, projections })).toThrow("Author row ann needs a cover on author-a.");
  });
});
