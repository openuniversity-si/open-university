import { sha256Hex } from "../../kernel/canonical.ts";
import { compileRelease } from "../domain/compile.ts";
import { LEGACY_LESSON_IDS } from "../domain/slug-course.ts";
import { sortTables, type CatalogTables } from "../domain/tables.ts";

/** Synthetic current-schema catalog. No copied catalog data and no restore/import role. */
export function syntheticTables(): CatalogTables {
  const at = "2026-01-01T12:00:00.000Z";
  const text = (entity_kind: string, entity_id: string, field: string, value: string) => ({
    entity_kind, entity_id, field, locale: "en", text: value, source: "manual", source_ref: "synthetic", confidence: "high",
    status: "approved", approved_by: "fixture-reviewer", approved_at: at, approved_sha256: sha256Hex(value),
  });
  const tables: CatalogTables = {
    licenses: [{ code: "youtube-standard", name: "Standard", url: null, requires_attribution: false, non_commercial: false, share_alike: false, embed_only: true, attribution_template: null }],
    content_sources: [{ id: "fixture-source", kind: "institution-site", title: "Fixture Source", publisher: "Fixture", url: "https://example.org", youtube_channel_id: null, youtube_playlist_id: null }],
    authors: [1, 2].map((n) => ({ id: `author-${String(n)}`, slug: `fixture-lecturer-${String(n)}`, name: `Fixture Lecturer ${String(n)}`, monogram: `F${String(n)}`, role: "Lecturer", kind: "person", cover: null })),
    subject_areas: [{ id: "fixture-subject", title: "Fixture Subject", position: 1 }], subject_subareas: [],
    courses: [], course_editions: [], lessons: [], lesson_videos: [], catalog_texts: [],
    home_rows: [{ id: "continue-watching", kind: "continue", author_id: null, title: null, position: 1, visible: true, cover: null, full_name: null, place: null }],
    home_row_items: [], slug_redirects: [],
  };
  // Exercise the existing fixed-id slug compatibility rule without retaining any old content.
  const ids = [...LEGACY_LESSON_IDS];
  let offset = 0;
  for (const [index, count] of [17, 12, 20, 51, 26].entries()) {
    const n = index + 1, id = `course-${String(n)}`, author = n <= 3 ? 1 : 2;
    tables.courses.push({ id, slug: `fixture-course-${String(n)}`, author_id: `author-${String(author)}`, title: `Fixture Course ${String(n)}`, language_label: "English", lesson_noun: n === 4 ? "Episode" : "Lecture", status: "published", featured: n === 1,
      source_id: "fixture-source", license_code: "youtube-standard", attribution_text: null, canonical_url: `https://example.org/course/${String(n)}`, rights_status: "cleared", rights_notes: null, rights_checked_by: null, rights_checked_at: null,
      legacy: null, area_id: "fixture-subject", subarea_id: null, cover_from: "own", shared_with: [], published_at: at });
    tables.course_editions.push({ id: `edition-${String(n)}`, course_id: id, slug: "2026", label: "2026", term: null, year: 2026, position: 1, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null });
    for (const field of ["displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile", "description", "descriptionMobile", "level", "format"]) {
      tables.catalog_texts.push(text("course", id, field, field === "displayTitle" || field === "shelfTitle" ? `Fixture Course ${String(n)}` : field === "level" ? "Intermediate" : field.startsWith("description") || field.startsWith("billboardDescription") ? "A synthetic course description with enough detail to exercise canonical metadata and display limits." : field === "subtitle" ? "A synthetic course explores connected ideas through carefully ordered lessons." : "Fixture text"));
    }
    for (let position = 1; position <= count; position++) {
      const lessonId = ids[offset++];
      if (!lessonId) throw new Error("Fixture id coverage");
      tables.lessons.push({ id: lessonId, slug: `fixture-${lessonId}`, course_id: id, edition_id: `edition-${String(n)}`, part: "lectures", position, kind: n === 1 && position === 9 ? "background" : n === 4 && position === 1 ? "trailer" : "lecture", youtube_title: `Fixture Lesson ${String(position)}`, duration_seconds: 3600, visible: true, license_code: null, attribution_text: null });
      tables.lesson_videos.push({ lesson_id: lessonId, provider: "youtube", external_id: `fx${String(offset).padStart(9, "0")}`, playback_id: null, playback_policy: null, resolution_tier: null, status: "ok", duration_seconds: 3600, youtube_license: null, channel_id: null, checked_at: at, checked_by: "fixture" });
      tables.catalog_texts.push(text("lesson", lessonId, "displayTitle", `${String(position)}: Fixture Lesson`));
      if (offset <= 77) tables.catalog_texts.push(text("lesson", lessonId, "about", "A synthetic lesson description with enough detail to exercise canonical metadata and display limits."));
    }
    tables.home_row_items.push({ row_id: `fixture-lecturer-${String(author)}`, course_id: id, position: n <= 3 ? n : n - 3 });
  }
  for (const n of [1, 2]) tables.home_rows.push({ id: `fixture-lecturer-${String(n)}`, kind: "author", author_id: `author-${String(n)}`, title: null, position: n + 1, visible: true, cover: null, full_name: null, place: null });
  return sortTables(tables);
}
export const syntheticCatalog = compileRelease(syntheticTables(), { number: 1, publishedAt: "2026-01-01T12:00:00.000Z" });
