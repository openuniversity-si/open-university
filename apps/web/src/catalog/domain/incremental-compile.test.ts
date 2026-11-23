import { describe, expect, it } from "vitest";
import { releaseSha } from "../../kernel/sha.ts";
import { compileRelease } from "./compile.ts";
import { readyCatalogFixture } from "../testing/catalog-fixture.ts";
import type { CatalogTables } from "./tables.ts";
import {
  COURSE_FINGERPRINT_TEXTS, assembleReleaseFromProjections, compileReleaseIndex, compileSingleCourseProjection, coursesToReuse, cutRelease, diffReleases, fingerprintAuthor, fingerprintCourse, fingerprintGlobals,
  indexCatalogTables, planIncrementalPublish, prepareReleaseCut, releaseContentSha, scopeCourseFromIndex, scopeCourseTables,
  type CompiledCourseProjection,
} from "./incremental-compile.ts";

// Verifies: D-033, REQ-contract-g-6
const checkedAt = "2020-01-01T00:00:00.000Z";

function publishable(): CatalogTables {
  const tables = structuredClone(readyCatalogFixture().tables);
  const author = tables.authors[0];
  if (!author) throw new Error("fixture");
  author.cover = null;
  tables.authors.push({ id: "author-b", slug: "other-author", name: "Other Author", monogram: "OA", role: "Lecturer", kind: "person", cover: null });
  const live = tables.courses.find((course) => course.id === "course-live");
  const ready = tables.courses.find((course) => course.id === "course-ready");
  if (!live || !ready) throw new Error("fixture");
  live.status = "published";
  ready.status = "published";
  ready.author_id = "author-b";
  for (const row of tables.catalog_texts) {
    row.status = "approved";
    row.approved_by = "editor";
    row.approved_at = checkedAt;
  }
  for (const row of [...tables.catalog_texts]) {
    if (row.entity_id === "course-ready") tables.catalog_texts.push({ ...row, entity_id: "course-live" });
  }
  const lessonText = tables.catalog_texts.find((row) => row.entity_id === "lesson-ready");
  if (!lessonText) throw new Error("fixture");
  tables.catalog_texts.push({ ...lessonText, entity_id: "lesson-live" });
  const liveVideo = tables.lesson_videos.find((row) => row.lesson_id === "lesson-live");
  if (liveVideo) liveVideo.external_id = "bbcdefghijk";
  tables.home_rows.push({ id: "continue", kind: "continue", author_id: null, title: null, position: 1, visible: true, cover: null, full_name: null, place: null });
  tables.slug_redirects.push({ from_path: "/c/old-course", to_path: "/c/course-live" });
  return tables;
}

function projectAll(tables: CatalogTables, fresh: ReadonlySet<string>) {
  return tables.courses.filter((course) => course.status === "published").map((course) => compileSingleCourseProjection({
    courseId: course.id, sourceRevision: 1, tables: scopeCourseTables(tables, course.id), previous: null, fresh: fresh.has(course.id),
  }));
}

describe("incremental compile", () => {
  it("lists About after the publish fields in the stored fingerprint", () => {
    expect(COURSE_FINGERPRINT_TEXTS).toEqual([
      "displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile",
      "description", "descriptionMobile", "level", "format", "about",
    ]);
  });

  it("scopes a course from the index the same way as a full walk", () => {
    const tables = publishable();
    const index = indexCatalogTables(tables);
    for (const course of tables.courses) {
      expect(scopeCourseFromIndex(tables, index, course.id)).toEqual(scopeCourseTables(tables, course.id));
    }
    expect(scopeCourseFromIndex(tables, index, "missing")).toEqual(scopeCourseTables(tables, "missing"));
  });

  it("matches the reference compiler and ignores input order and execution time", () => {
    const tables = publishable();
    const fresh = new Set(["course-live", "course-ready"]);
    const reference = compileRelease(tables, { number: 4, publishedAt: "2024-05-01T00:00:00.000Z" }, { fresh });
    const projections = projectAll(tables, fresh);
    const assembled = assembleReleaseFromProjections({ number: 4, publishedAt: "2024-05-01T00:00:00.000Z", tables, projections });
    expect(assembled).toEqual(reference);
    expect(releaseContentSha(assembled)).toBe(releaseContentSha({ ...assembled, number: 9, publishedAt: "2030-01-01T00:00:00.000Z" }));
    const reversed = structuredClone(tables);
    reversed.lessons.reverse();
    const again = projectAll(reversed, fresh);
    expect(again.map((projection) => projection.sha256).sort()).toEqual(projections.map((projection) => projection.sha256).sort());
    expect(again.map((projection) => projection.fingerprint).sort()).toEqual(projections.map((projection) => projection.fingerprint).sort());
    const index = compileReleaseIndex({
      globalFingerprint: fingerprintGlobals(tables),
      courses: projections.map((projection) => ({ courseId: projection.courseId, sha256: projection.sha256, fingerprint: projection.fingerprint, sourceRevision: projection.sourceRevision })),
      authors: tables.authors.map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
    });
    expect(index.manifestSha256).toHaveLength(64);
    expect(index.courses.map((course) => course.courseId)).toEqual(["course-live", "course-ready"]);
    expect(diffReleases(reference, assembled).empty).toBe(true);
  });

  it("builds the same home row from both compilers", () => {
    const tables = publishable();
    const cover = {
      url: `https://media.openuniversity.si/covers/mit/university_cover_9x16/${"a".repeat(40)}.webp`,
      width: 1080, height: 1920, sha256: "b".repeat(64), alt: "MIT", credit: "Test", sourceUrl: "https://example.org/mit", license: "test", note: null,
    };
    const watching = tables.home_rows.find((row) => row.kind === "continue");
    if (!watching) throw new Error("continue");
    watching.cover = cover;
    watching.full_name = "Not a university";
    watching.place = "Nowhere";
    tables.home_rows.push(
      { id: "ann", kind: "author", author_id: "author-a", title: null, position: 2, visible: true, cover, full_name: "Nope", place: "Nope" },
      { id: "mit", kind: "curated", author_id: null, institution_id: "inst-mit", title: "MIT", position: 3, visible: true, cover, full_name: "Massachusetts Institute of Technology", place: "Cambridge, MA" },
    );
    tables.home_row_items.push({ row_id: "mit", course_id: "course-live", position: 1 });
    const fresh = new Set(["course-live", "course-ready"]);
    const reference = compileRelease(tables, { number: 4, publishedAt: "2024-05-01T00:00:00.000Z" }, { fresh });
    const assembled = assembleReleaseFromProjections({ number: 4, publishedAt: "2024-05-01T00:00:00.000Z", tables, projections: projectAll(tables, fresh) });
    expect(assembled.home.rows).toEqual(reference.home.rows);
    expect(reference.home.rows.find((row) => row.id === "mit")).toMatchObject({
      cover, fullName: "Massachusetts Institute of Technology", place: "Cambridge, MA", institutionId: "inst-mit", courseIds: ["course-live"],
    });
    const continueRow = reference.home.rows.find((row) => row.id === "continue");
    expect(continueRow).not.toHaveProperty("cover");
    expect(continueRow).not.toHaveProperty("fullName");
    expect(continueRow).not.toHaveProperty("place");
    const authorRow = reference.home.rows.find((row) => row.id === "ann");
    expect(authorRow).toMatchObject({ authorId: "author-a", title: "Test Author" });
    expect(authorRow).not.toHaveProperty("cover");
    expect(authorRow).not.toHaveProperty("fullName");
    expect(authorRow).not.toHaveProperty("place");
  });

  it("recompiles only the courses of a changed author, and a home edit leaves course projections alone", () => {
    const tables = publishable();
    const fresh = new Set(["course-live", "course-ready"]);
    const projections = projectAll(tables, fresh);
    const stored = {
      globalFingerprint: fingerprintGlobals(tables),
      courses: projections.map((projection) => ({ courseId: projection.courseId, sha256: projection.sha256, fingerprint: projection.fingerprint, sourceRevision: 1 })),
      authors: tables.authors.map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
    };
    const published = projections.map((projection) => ({ courseId: projection.courseId, fingerprint: projection.fingerprint, authorId: projection.summary.authorId }));
    const renamed = structuredClone(tables);
    const renamedAuthor = renamed.authors[0];
    if (!renamedAuthor) throw new Error("fixture");
    renamedAuthor.name = "Renamed Author";
    const renamedProjections = projectAll(renamed, fresh);
    const authorPlan = planIncrementalPublish({
      published: renamedProjections.map((projection) => ({ courseId: projection.courseId, fingerprint: projection.fingerprint, authorId: projection.summary.authorId })),
      authorFingerprints: renamed.authors.map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
      homeAuthorIds: [],
      globalFingerprint: fingerprintGlobals(renamed),
      stored,
    });
    expect(authorPlan.dirty).toEqual(["course-live"]);
    expect(authorPlan.reasons.map((reason) => reason.reason)).toEqual(["author"]);
    const home = structuredClone(tables);
    const homeRow = home.home_rows[0];
    if (!homeRow) throw new Error("fixture");
    homeRow.title = "Keep watching";
    const homePlan = planIncrementalPublish({
      published,
      authorFingerprints: stored.authors,
      homeAuthorIds: [],
      globalFingerprint: fingerprintGlobals(home),
      stored,
    });
    expect(homePlan.dirty).toEqual([]);
    expect(homePlan.globalChanged).toBe(true);
    expect(homePlan.noop).toBe(false);
    const removed = planIncrementalPublish({
      published: published.filter((course) => course.courseId === "course-ready"),
      authorFingerprints: stored.authors,
      homeAuthorIds: [],
      globalFingerprint: stored.globalFingerprint,
      stored,
    });
    expect(removed.removed).toEqual(["course-live"]);
    expect(removed.dirty).toEqual([]);
  });

  it("cuts only the dirty courses and matches the reference compiler", () => {
    const tables = publishable();
    const fresh = new Set(["course-live", "course-ready"]);
    const revisions = new Map(tables.courses.map((course) => [course.id, 1]));
    const prepared = prepareReleaseCut({ tables, revisions, stored: null, active: null, fresh });
    expect([...prepared.plan.dirty].sort()).toEqual(["course-live", "course-ready"]);
    const cut = cutRelease({
      tables, prepared, stored: null, storedProjections: new Map(), active: null,
      now: new Date("2024-05-01T00:00:00.000Z"), nextNumber: 4,
    });
    const reference = compileRelease(tables, { number: 4, publishedAt: "2024-05-01T00:00:00.000Z" }, { fresh });
    expect(cut.payload).toEqual(reference);
    expect(releaseSha(cut.payload)).toBe(releaseSha(reference));
    expect(cut.unchanged).toBe(false);
    expect([...cut.compiledCourseIds].sort()).toEqual(["course-live", "course-ready"]);
    const stored = { globalFingerprint: cut.index.globalFingerprint, courses: cut.index.courses, authors: cut.index.authors };
    const same = prepareReleaseCut({ tables, revisions, stored, active: { payload: cut.payload }, fresh });
    expect(same.plan.noop).toBe(true);
    expect(same.plan.dirty).toEqual([]);

    const edited = structuredClone(tables);
    const live = edited.courses.find((course) => course.id === "course-live");
    if (!live) throw new Error("fixture");
    live.title = "Renamed live course";
    const compiled: string[] = [];
    const againPrepared = prepareReleaseCut({ tables: edited, revisions, stored, active: { payload: cut.payload }, fresh });
    const again = cutRelease({
      tables: edited, prepared: againPrepared, stored, storedProjections: new Map(cut.written.map((projection) => [projection.courseId, projection])),
      active: { number: cut.payload.number, sha: releaseSha(cut.payload), payload: cut.payload },
      now: new Date("2024-06-01T00:00:00.000Z"), nextNumber: 5,
      onCourseCompiled: (courseId) => { compiled.push(courseId); },
    });
    expect(compiled).toEqual(["course-live"]);
    expect(again.compiledCourseIds).toEqual(["course-live"]);
    const renamed = compileRelease(edited, { number: 5, publishedAt: "2024-06-01T00:00:00.000Z" }, { fresh });
    expect(again.payload).toEqual(renamed);
    expect(releaseSha(again.payload)).toBe(releaseSha(renamed));
    expect(releaseContentSha(again.payload)).toBe(releaseContentSha(compileRelease(edited, { number: 9, publishedAt: "2030-01-01T00:00:00.000Z" }, { fresh })));
  });

  it("cuts one changed course among 1000 in under 2 seconds", () => {
    const tables = publishable();
    const templateCourse = tables.courses.find((course) => course.id === "course-ready");
    const templateEdition = tables.course_editions.find((edition) => edition.course_id === "course-ready");
    const templateLesson = tables.lessons.find((lesson) => lesson.course_id === "course-ready");
    const templateVideo = templateLesson ? tables.lesson_videos.find((video) => video.lesson_id === templateLesson.id) : undefined;
    if (!templateCourse || !templateEdition || !templateLesson || !templateVideo) throw new Error("fixture");
    const templateTexts = tables.catalog_texts.filter((row) => row.entity_id === "course-ready" || row.entity_id === templateLesson.id);
    const extra = 998;
    for (let n = 0; n < extra; n += 1) {
      const id = `c${String(n).padStart(4, "0")}`;
      const lessonId = `l${String(n).padStart(4, "0")}`;
      const editionId = `e${String(n).padStart(4, "0")}`;
      tables.courses.push({ ...templateCourse, id, slug: `course-${id}`, title: `Course ${id}`, featured: false });
      tables.course_editions.push({ ...templateEdition, id: editionId, course_id: id });
      tables.lessons.push({ ...templateLesson, id: lessonId, slug: `lesson-${id}`, course_id: id, edition_id: editionId });
      tables.lesson_videos.push({ ...templateVideo, lesson_id: lessonId, external_id: `b${String(n).padStart(10, "0")}` });
      for (const row of templateTexts) tables.catalog_texts.push({ ...row, entity_id: row.entity_kind === "course" ? id : lessonId });
    }
    const fresh = new Set(["course-live"]);
    const revisions = new Map(tables.courses.map((course) => [course.id, 1]));
    const activePayload = compileRelease(publishable(), { number: 1, publishedAt: "2024-05-01T00:00:00.000Z" }, { fresh: new Set(["course-live", "course-ready"]) });
    const baseline = prepareReleaseCut({ tables, revisions, stored: null, active: { payload: activePayload }, fresh });
    const stored = {
      globalFingerprint: fingerprintGlobals(tables),
      courses: [...baseline.scopedById.values()].map((state) => ({
        courseId: state.courseId, sha256: "ab".repeat(32), fingerprint: fingerprintCourse(state), sourceRevision: 1,
      })),
      authors: tables.authors.map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
    };
    const donor = compileSingleCourseProjection({
      courseId: "course-ready", sourceRevision: 1, tables: scopeCourseTables(tables, "course-ready"), previous: activePayload, fresh: false,
    });
    const retarget = (courseId: string): CompiledCourseProjection => {
      const detail = structuredClone(donor.detail);
      detail.course.id = courseId;
      detail.course.slug = `course-${courseId}`;
      const editionIds = new Map<string, string>();
      detail.course.editions.forEach((edition, index) => {
        const next = `${courseId}-e${String(index)}`;
        editionIds.set(edition.id, next);
        edition.id = next;
      });
      detail.lessons.forEach((lesson, index) => {
        lesson.id = `${courseId}-l${String(index)}`;
        lesson.courseId = courseId;
        lesson.slug = `lesson-${courseId}-${String(index)}`;
        lesson.editionId = editionIds.get(lesson.editionId) ?? lesson.editionId;
      });
      return {
        courseId, sha256: donor.sha256, sourceRevision: 1, fingerprint: donor.fingerprint,
        summary: { authorId: donor.summary.authorId, lessonIds: detail.lessons.map((lesson) => lesson.id) },
        detail,
      };
    };
    const storedProjections = new Map(tables.courses.filter((course) => course.status === "published").map((course) => (
      [course.id, course.id === "course-ready" ? donor : retarget(course.id)] as const
    )));
    const edited = structuredClone(tables);
    const live = edited.courses.find((course) => course.id === "course-live");
    if (!live) throw new Error("fixture");
    live.title = "One course changed";
    const compiled: string[] = [];
    const started = Date.now();
    const prepared = prepareReleaseCut({ tables: edited, revisions, stored, active: { payload: activePayload }, fresh });
    const cut = cutRelease({
      tables: edited, prepared, stored, storedProjections, active: { number: 1, sha: releaseSha(activePayload), payload: activePayload },
      now: new Date("2024-06-01T00:00:00.000Z"), nextNumber: 2,
      onCourseCompiled: (courseId) => { compiled.push(courseId); },
    });
    expect(Date.now() - started).toBeLessThan(2000);
    expect(cut.releaseMs).toBeLessThan(2000);
    expect(compiled).toEqual(["course-live"]);
    expect(cut.compiledCourseIds).toEqual(["course-live"]);
    expect(cut.payload.courses).toHaveLength(1000);
  });

  it("plans a 500-course catalog without compiling untouched courses", () => {
    const published = Array.from({ length: 500 }, (_, index) => ({ courseId: `course-${String(index)}`, fingerprint: `fp-${String(index)}`, authorId: index < 3 ? "author-shared" : `author-${String(index)}` }));
    const stored = {
      globalFingerprint: "global",
      courses: published.map((course) => ({ courseId: course.courseId, sha256: "ab".repeat(32), fingerprint: course.fingerprint, sourceRevision: 1 })),
      authors: [{ id: "author-shared", fingerprint: "before" }, ...published.filter((course) => course.authorId !== "author-shared").map((course) => ({ id: course.authorId, fingerprint: course.authorId }))],
    };
    const started = Date.now();
    const plan = planIncrementalPublish({
      published,
      authorFingerprints: stored.authors.map((author) => author.id === "author-shared" ? { id: author.id, fingerprint: "after" } : author),
      homeAuthorIds: [],
      globalFingerprint: "global",
      stored,
    });
    expect(Date.now() - started).toBeLessThan(2000);
    expect(plan.dirty).toEqual(["course-0", "course-1", "course-2"]);
    expect(plan.noop).toBe(false);
    const repeat = planIncrementalPublish({ published, authorFingerprints: stored.authors, homeAuthorIds: [], globalFingerprint: "global", stored });
    expect(repeat.noop).toBe(true);
    expect(repeat.dirty).toEqual([]);
  });

  it("D-033: a stored course is reused unless its revision, author, license, source or rows changed", () => {
    const stored = {
      globalFingerprint: "g",
      courses: ["keep", "edit"].map((id) => ({ courseId: id, sha256: "ab".repeat(32), fingerprint: `fp-${id}`, sourceRevision: 2 })),
      authors: [{ id: "author-a", fingerprint: "author" }],
      licenses: [{ code: "cc-by", fingerprint: "lic" }],
      sources: [{ id: "src", fingerprint: "src" }],
    };
    const published = ["keep", "edit"].map((id) => ({ id, revision: 2, authorId: "author-a", licenseCode: "cc-by", sourceId: "src" }));
    const base = {
      published, stored, fresh: new Set<string>(), changed: new Set<string>(),
      dirtyAuthorIds: new Set<string>(), dirtyLicenseCodes: new Set<string>(), dirtySourceIds: new Set<string>(),
    };
    expect([...coursesToReuse(base)].sort()).toEqual(["edit", "keep"]);
    expect([...coursesToReuse({ ...base, fresh: new Set(["edit"]) })]).toEqual(["keep"]);
    expect([...coursesToReuse({ ...base, changed: new Set(["edit"]) })]).toEqual(["keep"]);
    expect([...coursesToReuse({ ...base, published: published.map((course) => course.id === "edit" ? { ...course, revision: 3 } : course) })]).toEqual(["keep"]);
    expect([...coursesToReuse({ ...base, dirtyAuthorIds: new Set(["author-a"]) })]).toEqual([]);
    expect([...coursesToReuse({ ...base, dirtyLicenseCodes: new Set(["cc-by"]) })]).toEqual([]);
    expect([...coursesToReuse({ ...base, dirtySourceIds: new Set(["src"]) })]).toEqual([]);
    expect(coursesToReuse({ ...base, stored: { ...stored, licenses: undefined } }).size).toBe(0);
    expect(coursesToReuse({ ...base, stored: null }).size).toBe(0);
  });

  it("D-033: a reused course keeps its stored fingerprint when its lessons were not loaded", () => {
    const tables = publishable();
    const revisions = new Map(tables.courses.map((course) => [course.id, 1]));
    const fresh = new Set(["course-live", "course-ready"]);
    const first = prepareReleaseCut({ tables, revisions, stored: null, active: null, fresh });
    const stored = {
      globalFingerprint: fingerprintGlobals(tables),
      courses: [...first.scopedById.values()].map((state) => ({
        courseId: state.courseId, sha256: "ab".repeat(32), fingerprint: fingerprintCourse(state), sourceRevision: 1,
      })),
      authors: tables.authors.map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
      licenses: [{ code: "cc-by", fingerprint: "lic" }],
      sources: [{ id: "src", fingerprint: "src" }],
    };
    const stripped = structuredClone(tables);
    const readyLessons = new Set(stripped.lessons.filter((lesson) => lesson.course_id === "course-ready").map((lesson) => lesson.id));
    stripped.lessons = stripped.lessons.filter((lesson) => lesson.course_id !== "course-ready");
    stripped.course_editions = stripped.course_editions.filter((edition) => edition.course_id !== "course-ready");
    stripped.lesson_videos = stripped.lesson_videos.filter((video) => !readyLessons.has(video.lesson_id));
    stripped.catalog_texts = stripped.catalog_texts.filter((row) => row.entity_id !== "course-ready" && !readyLessons.has(row.entity_id));
    const again = prepareReleaseCut({
      tables: stripped, revisions, stored, active: null, fresh: new Set(["course-live"]), reuse: new Set(["course-ready"]),
    });
    expect(again.scopedById.has("course-ready")).toBe(false);
    expect(again.plan.dirty).not.toContain("course-ready");
    expect(again.refs.map((ref) => ref.courseId)).toContain("course-ready");
  });
});
