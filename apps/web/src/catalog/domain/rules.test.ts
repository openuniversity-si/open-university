import { describe, expect, it } from "vitest";
import { TEXT_FIELDS } from "./fields.ts";
import type { CatalogTables } from "./tables.ts";
import { sha256Hex } from "../../kernel/canonical.ts";
import { canTransition, catalogCourseFacts, courseFacts, evaluateRules, REQUIRED_COVERS, RULES, STATUS_TRANSITIONS } from "./rules/status.ts";

const approved = (kind: string, id: string, field: string, text = `${field} text`) => ({
  entity_kind: kind, entity_id: id, field, locale: "en", text, source: "manual", source_ref: "test", confidence: "high",
  status: "approved", approved_by: "Daniel", approved_at: "2026-10-01T00:00:00.000Z", approved_sha256: sha256Hex(text),
});

/** A course that passes every rule for `published`. */
function readyTables(): CatalogTables {
  const lessons = ["lesson-1", "lesson-2"].map((id, index) => ({
    id, course_id: "course-9", edition_id: "edition-9", part: "lectures", slug: `l-${String(index + 1)}`, position: index + 1, kind: "lecture", youtube_title: id, duration_seconds: 600, visible: true, license_code: null, attribution_text: null,
  }));
  return {
    licenses: [], content_sources: [],
    authors: [{ id: "author-1", slug: "a", name: "A", monogram: "A", role: "Lecturer", kind: "person", cover: null }],
    subject_areas: [], subject_subareas: [],
    courses: [{
      id: "course-9", slug: "ready", author_id: "author-1", title: "Ready", language_label: "English", lesson_noun: "Lecture", status: "review", featured: false,
      source_id: "src", license_code: "youtube-standard", attribution_text: null, canonical_url: "https://example.org", rights_status: "cleared",
      rights_notes: null, rights_checked_by: null, rights_checked_at: null, legacy: null, area_id: "subject", subarea_id: null, cover_from: "own", shared_with: [], published_at: null,
    }],
    course_editions: [{ id: "edition-9", course_id: "course-9", slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025, position: 1, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null }],
    lessons,
    lesson_videos: lessons.map((lesson, index) => ({
      lesson_id: lesson.id, provider: "youtube", external_id: `vid0000000${String(index)}`, playback_id: null, playback_policy: null, resolution_tier: null,
      status: "ok", duration_seconds: null, youtube_license: null, channel_id: null, checked_at: "2026-10-01T00:00:00.000Z", checked_by: "oembed",
    })),
    catalog_texts: [
      ...Object.keys(TEXT_FIELDS.course).map((field) => approved("course", "course-9", field, field === "level" ? "Intro" : "Short text")),
      ...lessons.map((lesson) => approved("lesson", lesson.id, "displayTitle")),
    ],
    home_rows: [{ id: "main", kind: "curated", author_id: null, title: "Main", position: 1, visible: true, cover: null, full_name: null, place: null }],
    home_row_items: [{ row_id: "main", course_id: "course-9", position: 1 }],
    slug_redirects: [],
  };
}
/** Replaces fields of one row in place (the fixture rows are plain arrays). */
function edit<T>(rows: T[], index: number, changes: Partial<T>): void {
  const row = rows[index];
  if (row === undefined) throw new Error(`No row ${String(index)}.`);
  rows[index] = { ...row, ...changes };
}
const covers = new Set<string>(REQUIRED_COVERS);
const facts = (tables: CatalogTables, kinds: ReadonlySet<string> = covers) => {
  const result = courseFacts(tables, "course-9", kinds);
  if (!result) throw new Error("no course");
  return result;
};
const rules = (failures: { rule: string }[]) => failures.map((failure) => failure.rule);

describe("status preconditions (plan §2.2)", () => {
  it("passes a ready course for review and for publishing", () => {
    expect(evaluateRules("review", facts(readyTables()))).toEqual([]);
    expect(evaluateRules("published", facts(readyTables()))).toEqual([]);
    expect(courseFacts(readyTables(), "course-missing", covers)).toBeNull();
  });

  it("builds the same facts for every course in one pass", () => {
    const tables = readyTables();
    const single = courseFacts(tables, "course-9", covers);
    expect(catalogCourseFacts(tables, new Map([["course-9", covers]])).get("course-9")).toEqual(single);
    expect(catalogCourseFacts(tables, new Map()).get("course-9")?.coverKinds).toEqual(new Set());
  });

  it("lists every unmet rule at once, never only the first", () => {
    const tables = readyTables();
    edit(tables.courses, 0, { author_id: "author-gone", license_code: null, source_id: null, canonical_url: null, rights_status: "unverified" });
    edit(tables.lessons, 1, { position: 3 });
    edit(tables.lesson_videos, 0, { status: "unavailable" });
    tables.lesson_videos.pop();
    tables.catalog_texts = tables.catalog_texts.filter((row) => !(row.entity_kind === "course" && row.field === "subtitle"))
      .map((row) => (row.field === "level" ? { ...row, text: "A level label that is too long", status: "draft" } : row));
    tables.home_row_items = [];
    const failed = evaluateRules("published", facts(tables, new Set(["poster_9x16"])));
    expect(new Set(rules(failed))).toEqual(new Set(["author.exists", "lessons.contiguous", "videos.ok", "texts.required", "texts.limit", "texts.approved", "covers.active", "rights.fields", "rights.status", "home.row"]));
    expect(failed.filter((failure) => failure.rule === "covers.active")).toHaveLength(3);
    expect(failed.filter((failure) => failure.rule === "covers.active").every((failure) => failure.owner === "figure")).toBe(true);
    expect(failed.filter((failure) => failure.rule === "rights.fields")).toHaveLength(3);
    expect(failed.find((failure) => failure.rule === "videos.ok" && failure.entity === "lesson:lesson-2")?.message).toBe("The lesson has no YouTube video.");
  });

  it("applies the publish-only rules only to published", () => {
    const tables = readyTables();
    edit(tables.courses, 0, { rights_status: "unverified" });
    tables.catalog_texts = tables.catalog_texts.map((row) => ({ ...row, status: "draft", approved_sha256: null }));
    tables.home_row_items = [];
    expect(evaluateRules("review", facts(tables))).toEqual([]);
    expect(new Set(rules(evaluateRules("published", facts(tables))))).toEqual(new Set(["texts.approved", "rights.status", "home.row"]));
    expect(rules(evaluateRules("published", facts(tables), { allowOrphan: true }))).not.toContain("home.row");
  });

  it("refuses an approval whose hash no longer matches the text", () => {
    const tables = readyTables();
    tables.catalog_texts = tables.catalog_texts.map((row) => (row.field === "subtitle" ? { ...row, text: "Edited after approval" } : row));
    expect(evaluateRules("published", facts(tables))).toEqual([{ rule: "texts.approved", entity: "course:course-9", message: "subtitle is not approved at its current text." }]);
  });

  it("ignores hidden lessons, but needs one visible lesson", () => {
    const tables = readyTables();
    edit(tables.lessons, 1, { visible: false });
    edit(tables.lesson_videos, 1, { status: "unavailable" });
    expect(evaluateRules("published", facts(tables))).toEqual([]);
    edit(tables.lessons, 0, { visible: false });
    expect(rules(evaluateRules("review", facts(tables)))).toEqual(["lessons.visible"]);
  });

  it("turns fresh oEmbed failures and hidden Home rows into failures", () => {
    const tables = readyTables();
    edit(tables.home_rows, 0, { visible: false });
    const failed = evaluateRules("published", facts(tables), { videoFailures: [{ lessonId: "lesson-1", status: "embed-disabled" }] });
    expect(failed).toEqual([
      { rule: "videos.fresh", entity: "lesson:lesson-1", message: "The fresh oEmbed check says embed-disabled.", owner: "lesson" },
      { rule: "home.row", entity: "course:course-9", message: "The course is in no visible Home row (pass allowOrphan to publish it anyway).", owner: "showcase" },
    ]);
  });

  it("names the site when a published course uses a character the page cannot draw", () => {
    const tables = readyTables();
    const text = "Intro 🙂";
    tables.catalog_texts = tables.catalog_texts.map((row) => (row.field === "level" ? { ...row, text, approved_sha256: sha256Hex(text) } : row));
    const published = evaluateRules("published", facts(tables)).filter((failure) => failure.rule === "texts.charset");
    expect(published).toEqual([
      { rule: "texts.charset", entity: "course:course-9", message: "course.level uses characters outside the Inter subset: U+1F642.", owner: "site" },
    ]);
    expect(evaluateRules("review", facts(tables)).some((failure) => failure.rule === "texts.charset")).toBe(true);
  });

  it("names each rule once", () => {
    expect(new Set(RULES.map((entry) => entry.rule.id)).size).toBe(RULES.length);
  });
});

describe("status transition matrix", () => {
  const statuses = ["draft", "review", "published", "archived"] as const;
  it("allows exactly the plan's moves through POST /status", () => {
    const allowed = statuses.flatMap((from) => statuses.filter((to) => canTransition(from, to)).map((to) => `${from}->${to}`));
    expect(allowed).toEqual(["draft->review", "draft->archived", "review->draft", "review->archived", "archived->draft"]);
    expect(STATUS_TRANSITIONS.published).toEqual([]);
    expect(canTransition("unknown", "draft")).toBe(false);
  });

  it("consults a stored map and leaves the code map untouched", () => {
    const stored = { draft: ["archived"], review: ["draft", "archived"], archived: ["draft"], published: [] };
    expect(canTransition("draft", "review", stored)).toBe(false);
    expect(canTransition("draft", "archived", stored)).toBe(true);
    expect(canTransition("draft", "review")).toBe(true);
    expect(STATUS_TRANSITIONS.published).toEqual([]);
  });

  it("checks the editions: one at least, positions 1..N, none empty, lessons of the course's editions, no ambiguous year (ADR-21)", () => {
    const tables = readyTables();
    const second = { id: "edition-10", course_id: "course-9", slug: "2024", label: "2024", term: null, year: 2024, position: 3, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null };
    tables.course_editions.push(second, { ...second, id: "edition-11", slug: "other-2024", position: 4 });
    edit(tables.lessons, 1, { edition_id: "edition-foreign" });
    const failed = evaluateRules("published", facts(tables));
    expect(failed.map((failure) => `${failure.rule} ${failure.entity}`)).toEqual([
      "editions.contiguous course:course-9", "editions.lessons edition:edition-10", "editions.lessons edition:edition-11", "lessons.edition lesson:lesson-2",
      "editions.ambiguous edition:edition-10", "editions.ambiguous edition:edition-11",
    ]);
    tables.course_editions = [];
    expect(rules(evaluateRules("review", facts(tables)))).toContain("editions.exists");
  });

  it("D-034: a year passes review when each edition's variant differs, and a season term does not stand in for one", () => {
    const tables = readyTables();
    const base = { course_id: "course-9", term: "fall" as const, year: 2024, resolution: null, source_playlist_ids: [] as string[], label: "Fall 2024" };
    tables.course_editions.push(
      { ...base, id: "edition-10", slug: "2024-it", position: 3, variant_kind: "language", variant_label: "Italiano" },
      { ...base, id: "edition-11", slug: "2024-en", position: 4, variant_kind: "language", variant_label: "English" },
    );
    const lesson = tables.lessons[0];
    const video = tables.lesson_videos[0];
    const italian = tables.course_editions[1];
    const english = tables.course_editions[2];
    if (!lesson || !video || !italian || !english) throw new Error("ready tables");
    tables.lessons.push(
      { ...lesson, id: "lesson-10", edition_id: "edition-10", slug: "lesson-10", position: 1 },
      { ...lesson, id: "lesson-11", edition_id: "edition-11", slug: "lesson-11", position: 1 },
    );
    tables.lesson_videos.push(
      { ...video, lesson_id: "lesson-10", external_id: "video0000010" },
      { ...video, lesson_id: "lesson-11", external_id: "video0000011" },
    );
    expect(rules(evaluateRules("review", facts(tables)))).not.toContain("editions.ambiguous");
    tables.course_editions[1] = { ...italian, variant_kind: null, variant_label: null };
    tables.course_editions[2] = { ...english, variant_kind: null, variant_label: null };
    expect(rules(evaluateRules("review", facts(tables)))).toContain("editions.ambiguous");
  });
});
