import { describe, expect, it } from "vitest";
import { validateCourseBundle, type CourseBundleV1 } from "../bundle.ts";
import type { HomePut } from "../contracts.ts";
import { duplicateFailures, parseBundles } from "./batch.ts";
import { homeFailures, placementInstitutionFailures, homeInstitutionFailures, rowInstitution, homePlacementFailures, homeRefCoverErrors, type HomeRowRef } from "./home.ts";
import { authorDeleteBlockers, classificationFailures, courseDeleteBlockers, editionDeleteBlockers, hideLessonFailures, lessonDeleteBlockers, notWrittenFailures, textBatchIssues } from "./lifecycle.ts";
import { referenceFailures, refKeys, type CatalogRefs } from "./refs.ts";
import { declareRule, declaredRules } from "./registry.ts";
import { publishedAreaFailures, publishedKeepsCovers, publishedKeepsRights, REQUIRED_COVERS, RULES } from "./status.ts";

// Verifies: D-032, REQ-contract-inv-r2, REQ-contract-inv-r3
// One case per rule id of the core (INV-R2), over in-memory refs: no database, no network.

function bundle(id: string, course: Record<string, unknown> = {}, extra: Record<string, unknown> = {}): CourseBundleV1 {
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id, slug: id, title: "Title", authorId: "author-a", coverFrom: "own", sharedWith: [], ...course },
    editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons: [{ id: `${id}-l`, editionId: `${id}-e`, slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
    ...extra,
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

const emptyRefs: CatalogRefs = {
  licenses: new Set(), sources: new Set(), areas: new Set(), subareas: [], authors: [], courses: [], editions: [], videos: [], shares: [], lessons: [], homeRows: [],
};
const refs = (patch: Partial<CatalogRefs>): CatalogRefs => ({ ...emptyRefs, ...patch });
const row = (patch: Partial<HomeRowRef> & { id: string }): HomeRowRef => ({ kind: "curated", visible: true, hasCover: true, authorId: null, authorHasCover: null, ...patch });
const ids = (failures: readonly { rule: string }[]) => failures.map((failure) => failure.rule);
const exercised = new Set<string>();
const seen = <T extends { rule: string }>(failures: readonly T[]): T[] => {
  for (const failure of failures) exercised.add(failure.rule);
  return [...failures];
};

describe("catalog rules core", () => {
  it("area.required: publication and published edits require an area; draft shape still permits none", () => {
    expect(seen(publishedAreaFailures("course-a", null))).toEqual([expect.objectContaining({ rule: "area.required", entity: "course:course-a" })]);
    expect(publishedAreaFailures("course-a", "subject")).toEqual([]);
    expect(RULES.find((rule) => rule.rule.id === "area.required")?.targets).toEqual(["published"]);
  });
  it("home.institution: one row per institution, no cross-institution grouping or unknown parent", () => {
    const row = { id: "school", kind: "curated" as const, title: "School", courseIds: ["course-a"] };
    const parents = new Map([["course-a", "author-a"], ["course-b", "author-b"]]);
    const institutions = new Set(["author-a", "author-b"]);
    expect(rowInstitution(row, parents)).toBe("author-a");
    expect(homeInstitutionFailures([row], institutions, parents)).toEqual([]);
    expect(seen(placementInstitutionFailures({ ...row, visible: true, hasCover: true, authorId: null, authorHasCover: null, institutionId: "author-a" }, "author-b", "course-b"))).toEqual([expect.objectContaining({ rule: "home.institution", entity: "course:course-b" })]);
    for (const rows of [[{ ...row, courseIds: [] }], [row, { ...row, id: "second" }], [{ ...row, institutionId: "author-a", courseIds: ["course-a", "course-b"] }]]) {
      expect(ids(seen(homeInstitutionFailures(rows, institutions, parents)))).toEqual(["home.institution"]);
    }
  });

  it("bundle.invalid and bundle.edition.year: name each bundle that fails its shape", () => {
    const year = { ...bundle("course-y"), editions: [{ id: "course-y-e", slug: "original", label: "Original", position: 1, year: null }] };
    const parsed = parseBundles([{ version: 1, course: { id: "broken" } }, year, bundle("course-ok")]);
    expect(seen(parsed.failures).map((failure) => [failure.rule, failure.entity])).toEqual([["bundle.invalid", "course:broken"], ["bundle.edition.year", "course:course-y"]]);
    expect(parsed.bundles.map((entry) => entry.course.id)).toEqual(["course-ok"]);
  });

  it("bundle.duplicate and bundle.author: list every duplicate inside the batch, not the first", () => {
    const other = { ...bundle("course-b"), author: { id: "author-a", slug: "ann", name: "Someone else", monogram: "S", kind: "person" as const } };
    const failures = seen(duplicateFailures([bundle("course-a"), bundle("course-a"), other]));
    expect(ids(failures)).toEqual(expect.arrayContaining(["bundle.duplicate", "bundle.author"]));
    expect(failures.map((failure) => failure.message)).toEqual(expect.arrayContaining(["Course course-a appears twice in the batch.", "Video abcdefghijk appears twice in course-a.", "Author author-a is not the same person in every bundle."]));
    expect(duplicateFailures([bundle("course-a"), bundle("course-b")])).toEqual([]);
  });

  it("ref.license.unknown, ref.source.unknown, ref.area.unknown, ref.subarea.unknown: a reference the store lacks fails by id", () => {
    const course = bundle("course-a", { licenseCode: "cc-x", sourceId: "src-x", areaId: "physics", subareaId: "optics" });
    expect(seen(referenceFailures([course], emptyRefs)).map((failure) => failure.rule)).toEqual(["ref.license.unknown", "ref.source.unknown", "ref.area.unknown", "ref.subarea.unknown"]);
    const stored = refs({ licenses: new Set(["cc-x"]), sources: new Set(["src-x"]), areas: new Set(["physics"]), subareas: [{ areaId: "physics", id: "optics" }] });
    expect(referenceFailures([course], stored)).toEqual([]);
    expect(referenceFailures([course], { ...stored, subareas: [{ areaId: "chemistry", id: "optics" }] })).toEqual([expect.objectContaining({ rule: "ref.subarea.unknown", message: "Subarea optics is not in physics." })]);
  });

  it("bundle.author and bundle.slug: a stored slug owned by someone else is taken; one owned inside the batch is not", () => {
    const failures = seen(referenceFailures([bundle("course-a")], refs({ authors: [{ id: "author-z", slug: "ann" }], courses: [{ id: "course-z", slug: "course-a" }] })));
    expect(failures).toEqual([
      { rule: "bundle.author", entity: "course:course-a", message: "Author slug ann belongs to author-z." },
      { rule: "bundle.slug", entity: "course:course-a", message: "Slug course-a belongs to another course." },
    ]);
    expect(referenceFailures([
      bundle("course-a", { sharedWith: ["course-z"] }),
      bundle("course-z", { sharedWith: ["course-a"] }),
    ], refs({ courses: [{ id: "course-z", slug: "course-a" }] }))).toEqual([]);
    const lessonSlug = refs({ lessons: [{ id: "other-lesson", courseId: "course-a", slug: "intro" }] });
    expect(ids(referenceFailures([bundle("course-a")], lessonSlug))).toEqual(["bundle.slug"]);
  });

  it("bundle.edition: an edition id, slug or position held by another edition fails", () => {
    const stored = refs({ editions: [{ id: "course-a-e", courseId: "course-z", slug: "x", position: 9, year: 2019, variant: null }, { id: "course-a-old", courseId: "course-a", slug: "original", position: 1, year: 2019, variant: null }] });
    expect(seen(referenceFailures([bundle("course-a")], stored)).map((failure) => failure.message)).toEqual([
      "Edition course-a-e belongs to course-z.", "Edition slug original is taken in course-a.", "Edition position 1 is taken in course-a.",
    ]);
  });

  it("D-034: a stored edition of the same year without a distinct variant fails", () => {
    const stored = refs({ editions: [{ id: "stored", courseId: "course-a", slug: "other", position: 2, year: 2020, variant: null }] });
    expect(seen(referenceFailures([bundle("course-a")], stored)).map((failure) => failure.message)).toEqual([
      "Editions course-a-e, stored share the year 2020 without a distinct variant.",
    ]);
    const distinct = refs({ editions: [{ id: "stored", courseId: "course-a", slug: "other", position: 2, year: 2020, variant: { kind: "language", label: "Italiano" } }] });
    expect(referenceFailures([bundle("course-a")], distinct)).toEqual([]);
    const same = refs({ editions: [{ id: "stored", courseId: "course-a", slug: "other", position: 2, year: 2020, variant: { kind: "term", label: "SS" } }] });
    const offered = bundle("course-a", {}, { editions: [{ id: "course-a-e", slug: "original", label: "Original", position: 1, year: 2020, variant: { kind: "term", label: "SS" } }] });
    expect(referenceFailures([offered], same).map((failure) => failure.message)).toEqual([
      "Editions course-a-e, stored share the year 2020 without a distinct variant.",
    ]);
  });

  it("bundle.video and video.share: one video per course, and a second course only when both declare the share (INV-R3, D-003, D-032)", () => {
    const elsewhere = refs({ videos: [{ lessonId: "course-z-l", courseId: "course-z", youtubeId: "abcdefghijk" }] });
    expect(seen(referenceFailures([bundle("course-a")], elsewhere))).toEqual([{
      rule: "video.share", entity: "course:course-a", message: "Video abcdefghijk is also in course-z; both courses must declare the share.",
    }]);
    const shared = refs({
      videos: [{ lessonId: "course-z-l", courseId: "course-z", youtubeId: "abcdefghijk" }],
      shares: [{ id: "course-z", sharedWith: ["course-a"] }],
    });
    expect(referenceFailures([bundle("course-a", { sharedWith: ["course-z"] })], shared)).toEqual([]);
    const here = refs({ videos: [{ lessonId: "course-a-other", courseId: "course-a", youtubeId: "abcdefghijk" }] });
    expect(seen(referenceFailures([bundle("course-a")], here))).toEqual([{ rule: "bundle.video", entity: "course:course-a", message: "Video abcdefghijk belongs to course-a-other." }]);
  });

  it("refKeys names every reference of the batch once, the input of the one-round-trip port", () => {
    const keys = refKeys([bundle("course-a", { licenseCode: "cc", areaId: "physics", subareaId: "optics" }, { home: { rowId: "mit", expectedRevision: 3 } }), bundle("course-b", { licenseCode: "cc" })]);
    expect(keys).toMatchObject({ licenses: ["cc"], areas: ["physics"], subareas: [["physics", "optics"]], courseIds: ["course-a", "course-b"], homeRowIds: ["mit"], youtubeIds: ["abcdefghijk", "abcdefghijk"] });
  });

  it("home.row and home.revision: a placement names an existing row and the current revision", () => {
    const homes = [{ rowId: "mit", courseId: "course-a", expectedRevision: 3 }, { rowId: "gone", courseId: "course-b", expectedRevision: 3 }];
    expect(seen(homePlacementFailures(homes, [row({ id: "mit" })], 4))).toEqual([
      { rule: "home.revision", entity: "course:course-a", message: "Home revision is 4, not 3." },
      { rule: "home.row", entity: "course:course-b", message: "Home row gone does not exist." },
    ]);
    expect(homePlacementFailures(homes.slice(0, 1), [row({ id: "mit" })], 3)).toEqual([]);
  });

  it("home.cover: a visible university row needs its cover, an author row its author's (INV-M4, D-002)", () => {
    const rows = [row({ id: "mit", hasCover: false }), row({ id: "hidden", hasCover: false, visible: false }), row({ id: "ann", kind: "author", hasCover: false, authorId: "author-1", authorHasCover: false })];
    expect(homeRefCoverErrors(rows)).toEqual(["Curated row mit needs a cover.", "Author row ann needs a cover on author-1."]);
    exercised.add("home.cover");
  });

  it("home.valid: PUT /home lists every broken Home invariant at once", () => {
    const body = {
      expectedRevision: 1, featuredCourseId: "course-d",
      rows: [{ id: "r", kind: "curated", courseIds: ["course-a", "course-a", "course-x"] }, { id: "r", kind: "author", authorId: "nobody", courseIds: [] }],
    } as unknown as HomePut;
    const failures = seen(homeFailures(body, new Map([["course-a", "archived"], ["course-d", "draft"]]), new Set(["author-1"])));
    expect(new Set(ids(failures))).toEqual(new Set(["home.valid"]));
    expect(failures.map((failure) => failure.message)).toEqual([
      "Curated row r needs a title.", "Row r repeats a course.", "Row r: course course-a is archived.", "Row r: course course-a is archived.", "Row r: course course-x does not exist.",
      "Row r appears twice.", "Author row r needs an existing authorId.", "Featured course course-d is not published.",
    ]);
  });

  it("state, featured and has_dependents: deletes are blocked by named rules", () => {
    expect(seen(courseDeleteBlockers({ mode: "purge", status: "published", publishedBefore: true, featured: false, replacementGiven: false }))).toEqual([expect.objectContaining({ rule: "state" })]);
    expect(courseDeleteBlockers({ mode: "purge", status: "draft", publishedBefore: true, featured: false, replacementGiven: false })).toEqual([expect.objectContaining({ rule: "state" })]);
    expect(seen(courseDeleteBlockers({ mode: "archive", status: "published", publishedBefore: true, featured: true, replacementGiven: false }))).toEqual([expect.objectContaining({ rule: "featured" })]);
    expect(courseDeleteBlockers({ mode: "archive", status: "published", publishedBefore: true, featured: true, replacementGiven: true })).toEqual([]);
    expect(ids(seen(editionDeleteBlockers({ editions: 1, lessons: 2, withLessons: false, published: true, visibleHere: true, visibleElsewhere: 0 })))).toEqual(["has_dependents", "has_dependents", "lessons.visible"]);
    expect(ids(seen(authorDeleteBlockers(2)))).toEqual(["has_dependents"]);
    expect(authorDeleteBlockers(0)).toEqual([]);
  });

  it("lessons.visible: a published course keeps a visible lesson when one is hidden or deleted", () => {
    expect(seen(hideLessonFailures("course-a", true, 1))).toEqual([{ rule: "lessons.visible", entity: "course:course-a", message: "A published course keeps at least one visible lesson." }]);
    expect(hideLessonFailures("course-a", true, 2)).toEqual([]);
    expect(ids(lessonDeleteBlockers({ published: true, visible: true, otherVisible: 0 }))).toEqual(["lessons.visible"]);
    expect(lessonDeleteBlockers({ published: false, visible: true, otherVisible: 0 })).toEqual([]);
  });

  it("rights.fields, rights.status and covers.active: a published course keeps them while it is edited", () => {
    expect(ids(seen(publishedKeepsRights("course-a", { license_code: null, source_id: "s", canonical_url: "u", rights_status: "unverified" })))).toEqual(["rights.fields", "rights.status"]);
    expect(publishedKeepsRights("course-a", { license_code: "l", source_id: "s", canonical_url: "u", rights_status: "cleared" })).toEqual([]);
    expect(seen(publishedKeepsCovers("course-a", new Set(REQUIRED_COVERS.slice(1))))).toEqual([{ rule: "covers.active", entity: "course:course-a", message: `A published course keeps its active ${REQUIRED_COVERS[0]} cover; unpublish it first.` }]);
  });

  it("course.classification, course.missing, texts.duplicate and texts.entity", () => {
    expect(seen(classificationFailures("course-a", "Subarea optics is not in chemistry."))).toEqual([{ rule: "course.classification", entity: "course:course-a", message: "Subarea optics is not in chemistry." }]);
    expect(classificationFailures("course-a", null)).toEqual([]);
    expect(seen(notWrittenFailures(["course-a", "course-b"], new Set(["course-a"])))).toEqual([{ rule: "course.missing", entity: "course:course-b", message: "The course was not written." }]);
    const items = [{ entityKind: "course", entityId: "course-a", field: "summary" }, { entityKind: "course", entityId: "course-a", field: "summary" }, { entityKind: "lesson", entityId: "gone", field: "summary" }];
    expect(textBatchIssues(items, new Set(["course:course-a"])).map((issues) => ids(seen(issues)))).toEqual([[], ["texts.duplicate"], ["texts.entity"]]);
  });

  it("declares each rule id once; a second declaration is refused", () => {
    const declared = declaredRules().map((rule) => rule.id);
    expect(new Set(declared).size).toBe(declared.length);
    for (const id of declared) expect(id).toMatch(/^[a-z_]+(\.[a-z_]+)*$/);
    expect(() => declareRule("bundle.video", "again")).toThrow("Rule bundle.video is declared twice.");
  });

  it("has a case for every declared rule (status rules are proven in ../rules.test.ts)", () => {
    const status = new Set(RULES.map((entry) => entry.rule.id));
    const missing = declaredRules().map((rule) => rule.id).filter((id) => !exercised.has(id) && !status.has(id));
    expect(missing).toEqual([]);
  });
});
