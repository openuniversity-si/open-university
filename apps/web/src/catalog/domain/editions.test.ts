import { describe, expect, it } from "vitest";
import { asReleaseV1, releaseFixture } from "../../../test/fixtures/release.ts";
const snapshot = asReleaseV1(releaseFixture());
import { compileRelease } from "./compile.ts";
import { fakeCatalog, TEST_EDITIONS_COURSE } from "../testing/fake.ts";
import { courseBySlug, defaultEdition, editionCount, editionOf, editionsForCourse, lessonLabel, lessonNeighbors, lessonsForCourse, lessonsForEdition } from "./queries.ts";
import { normalizeRelease, parseRelease, parseStoredRelease, releaseSchema, releaseV1Schema, syntheticEditionId, type PublicCatalog } from "./release.ts";
import { releaseSha } from "../../kernel/sha.ts";
import type { CatalogTables } from "./tables.ts";

// Course editions in the release and the site's queries (ADR-21).

const course = () => {
  const found = courseBySlug(fakeCatalog, TEST_EDITIONS_COURSE.slug);
  if (!found) throw new Error("No test editions course.");
  return found;
};

describe("release version 2 and the version 1 reader", () => {
  it("reads release #1 (version 1, as stored) as one synthetic edition per course, everything else unchanged", () => {
    const v1 = releaseV1Schema.parse(snapshot);
    const read = parseRelease(snapshot);
    expect(read.schemaVersion).toBe(2);
    expect(read.courses.map((entry) => entry.editions.map((edition) => [edition.id, edition.position, edition.lessonCount, edition.parts.labs]))).toEqual(
      v1.courses.map((entry) => [[syntheticEditionId(entry.id), 1, v1.lessons.filter((lesson) => lesson.courseId === entry.id).length, 0]]),
    );
    expect(asReleaseV1(read)).toEqual(v1);
    // The stored bytes, not the normalized view, are what the sha covers; a snapshot writes them back unchanged.
    expect(releaseSha(parseStoredRelease(snapshot))).toBe(releaseSha(v1));
    expect(normalizeRelease(read)).toBe(read);
    // The same queries answer for release #1 as before editions: course order, neighbors, labels.
    for (const entry of v1.courses) {
      expect(lessonsForCourse(read, entry.id).map((lesson) => lesson.id)).toEqual(v1.lessons.filter((lesson) => lesson.courseId === entry.id).sort((a, b) => a.order - b.order).map((lesson) => lesson.id));
    }

  });

  it("rejects editions that break the invariants", () => {
    const issues = (mutate: (release: PublicCatalog) => void) => {
      const release = releaseFixture();
      mutate(release);
      const result = releaseSchema.safeParse(release);
      return result.success ? "" : result.error.issues.map((issue) => issue.message).join("\n");
    };
    const first = (release: PublicCatalog) => release.courses[0]?.editions[0];
    expect(issues((release) => { const edition = first(release); if (edition) edition.position = 2; })).toContain("Non-contiguous edition positions in course-1");
    expect(issues((release) => { const lesson = release.lessons[2]; if (lesson) lesson.editionId = "course-1-e1"; })).toContain("Lesson lesson-3 names an edition of another course.");
    expect(issues((release) => { const edition = first(release); if (edition) edition.lessonCount = 5; })).toContain("Edition course-1-e1 counts differ from its lessons.");
    expect(issues((release) => { const entry = release.courses[1]; if (entry) entry.editions = []; })).not.toBe("");
    expect(issues((release) => { const entry = release.courses[0]; const edition = first(release); if (entry && edition) entry.editions = [edition, { ...edition, id: "course-1-e2", position: 2 }]; })).toContain("Duplicate edition slug in course-1");
    expect(issues((release) => { const edition = first(release); if (edition) edition.label = "x".repeat(41); })).not.toBe("");
  });

  it("D-034: a release carries a variant and refuses two editions of one year without one", () => {
    const release = releaseFixture();
    const course = release.courses[0];
    const edition = course?.editions[0];
    const second = release.lessons.find((lesson) => lesson.id === "lesson-2");
    if (!course || !edition || !second) throw new Error("fixture");
    course.editions = [
      { ...edition, lessonCount: 1, durationSeconds: 3600, parts: { lectures: 1, labs: 0 }, variant: { kind: "language", label: "Italiano" } },
      { ...edition, id: "course-1-e2", slug: "english", position: 2, lessonCount: 1, durationSeconds: 3600, parts: { lectures: 1, labs: 0 }, variant: { kind: "language", label: "English" } },
    ];
    second.editionId = "course-1-e2";
    second.order = 1;
    const parsed = releaseSchema.parse(release);
    expect(parsed.courses[0]?.editions.map((row) => row.variant)).toEqual([
      { kind: "language", label: "Italiano" }, { kind: "language", label: "English" },
    ]);
    const stripped = structuredClone(parsed);
    for (const row of stripped.courses[0]?.editions ?? []) delete row.variant;
    const refused = releaseSchema.safeParse(stripped);
    expect(refused.success ? "" : refused.error.issues.map((issue) => issue.message).join("\n")).toContain(
      "Editions course-1-e1, course-1-e2 share the year 2025 without a distinct variant.",
    );
    const same = structuredClone(parsed);
    const twin = same.courses[0]?.editions[1];
    if (twin) twin.variant = { kind: "language", label: "Italiano" };
    const collided = releaseSchema.safeParse(same);
    expect(collided.success ? "" : collided.error.issues.map((issue) => issue.message).join("\n")).toContain(
      "Editions course-1-e1, course-1-e2 share the year 2025 without a distinct variant.",
    );
  });
});

describe("queries over editions", () => {
  it("lists editions newest first and lessons edition by edition", () => {
    expect(editionsForCourse(course()).map((edition) => edition.slug)).toEqual(["spring-2025", "fall-2024"]);
    expect(defaultEdition(course()).label).toBe("Spring 2025");
    expect(lessonsForEdition(fakeCatalog, `${TEST_EDITIONS_COURSE.id}-fall-2024`).map((lesson) => [lesson.id, lesson.order])).toEqual([["lesson-test-4", 1], ["lesson-test-5", 2]]);
    expect(lessonsForCourse(fakeCatalog, TEST_EDITIONS_COURSE.id).map((lesson) => lesson.id)).toEqual(["lesson-test-1", "lesson-test-2", "lesson-test-3", "lesson-test-4", "lesson-test-5"]);
    const lab = fakeCatalog.lessons.find((lesson) => lesson.id === "lesson-test-3");
    expect(lab && editionOf(fakeCatalog, lab)?.slug).toBe("spring-2025");
    expect(lab && lessonLabel(course(), lab)).toBe("Lab");
    expect(() => defaultEdition({ ...course(), editions: [] })).toThrow("has no edition");
    const [spring, fall] = editionsForCourse(course());
    expect([spring && editionCount(course(), spring), fall && editionCount(course(), fall)]).toEqual(["2 lectures + 1 labs", "2 lectures"]);
    if (spring) expect(editionCount(course(), { ...spring, parts: { lectures: 0, labs: 3 } })).toBe("3 labs");
  });

  it("never steps across editions", () => {
    expect(lessonNeighbors(fakeCatalog, "lesson-test-3")).toMatchObject({ previous: { id: "lesson-test-2" }, next: undefined });
    expect(lessonNeighbors(fakeCatalog, "lesson-test-4")).toMatchObject({ previous: undefined, next: { id: "lesson-test-5" } });
  });
});

describe("compileRelease with editions", () => {
  it("numbers visible lessons per edition and leaves out an edition whose lessons are all hidden", () => {
    const tables: CatalogTables = {
      licenses: [{ code: "youtube-standard", name: "Standard", url: null, requires_attribution: false, non_commercial: false, share_alike: false, embed_only: true, attribution_template: null }],
      content_sources: [{ id: "src", kind: "institution-site", title: "Src", publisher: "Src", url: "https://example.org", youtube_channel_id: null, youtube_playlist_id: null }],
      authors: [{ id: "author-1", slug: "a", name: "A", monogram: "A", role: "Lecturer", kind: "person", cover: null }],
      subject_areas: [], subject_subareas: [],
      courses: [{
        id: "course-1", slug: "c", author_id: "author-1", title: "C", language_label: "English", lesson_noun: "Lecture", status: "published", featured: false, source_id: "src",
        license_code: "youtube-standard", attribution_text: null, canonical_url: "https://example.org/c", rights_status: "cleared", rights_notes: null, rights_checked_by: null,
        rights_checked_at: null, legacy: null, area_id: null, subarea_id: null, cover_from: "own", shared_with: [], published_at: "2026-10-01T00:00:00.000Z",
      }],
      course_editions: [
        { id: "edition-1", course_id: "course-1", slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025, position: 1, resolution: "1080p", source_playlist_ids: [], variant_kind: null, variant_label: null },
        { id: "edition-2", course_id: "course-1", slug: "2024", label: "2024", term: null, year: 2024, position: 2, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null },
        { id: "edition-3", course_id: "course-1", slug: "2023", label: "2023", term: null, year: 2023, position: 3, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null },
      ],
      lessons: [
        ["lesson-1", "edition-1", "lectures", 1, true], ["lesson-2", "edition-1", "labs", 2, false], ["lesson-3", "edition-1", "labs", 3, true],
        ["lesson-4", "edition-2", "lectures", 1, false], ["lesson-5", "edition-3", "lectures", 1, true],
      ].map(([id, edition, part, position, visible]) => ({
        id: String(id), course_id: "course-1", edition_id: String(edition), part: String(part), slug: String(id), position: Number(position), kind: "lecture",
        youtube_title: String(id), duration_seconds: 600, visible: Boolean(visible), license_code: null, attribution_text: null,
      })),
      lesson_videos: ["lesson-1", "lesson-2", "lesson-3", "lesson-4", "lesson-5"].map((id, index) => ({
        lesson_id: id, provider: "youtube", external_id: `video00000${String(index)}`, playback_id: null, playback_policy: null, resolution_tier: null, status: "ok",
        duration_seconds: null, youtube_license: null, channel_id: null, checked_at: "2026-10-01T00:00:00.000Z", checked_by: "oembed",
      })),
      catalog_texts: [
        ...["displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile", "description", "descriptionMobile", "level", "format"].map((field) => ({ entity: "course", id: "course-1", field })),
        ...["lesson-1", "lesson-2", "lesson-3", "lesson-4", "lesson-5"].map((id) => ({ entity: "lesson", id, field: "displayTitle" })),
      ].map((slot) => ({
        entity_kind: slot.entity, entity_id: slot.id, field: slot.field, locale: "en", text: `${slot.field} text`, source: "manual", source_ref: "t", confidence: "high",
        status: "approved", approved_by: "T", approved_at: "2026-10-01T00:00:00.000Z", approved_sha256: null,
      })),
      home_rows: [], home_row_items: [], slug_redirects: [],
    };
    const first = tables.course_editions[0];
    if (first) tables.course_editions[0] = { ...first, variant_kind: "group", variant_label: "presencial" };
    const release = compileRelease(tables, { number: 2, publishedAt: "2026-10-11T00:00:00.000Z" });
    expect(release.courses[0]?.editions.map((edition) => [edition.id, edition.position, edition.lessonCount, edition.parts, edition.resolution, edition.variant ?? null])).toEqual([
      ["edition-1", 1, 2, { lectures: 1, labs: 1 }, "1080p", { kind: "group", label: "presencial" }],
      ["edition-3", 2, 1, { lectures: 1, labs: 0 }, null, null],
    ]);
    expect(release.lessons.map((lesson) => [lesson.id, lesson.editionId, lesson.part, lesson.order])).toEqual([
      ["lesson-1", "edition-1", "lectures", 1], ["lesson-3", "edition-1", "labs", 2], ["lesson-5", "edition-3", "lectures", 1],
    ]);
  });
});
