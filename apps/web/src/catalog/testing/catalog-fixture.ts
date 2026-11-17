import { REQUIRED_COVERS } from "../domain/rules/status.ts";
import { catalogTablesSchema, type CatalogRow, type CatalogTables } from "../domain/tables.ts";

const checkedAt = "2020-01-01T00:00:00.000Z";
const courseText: Record<string, string> = {
  displayTitle: "Title", shelfTitle: "Shelf", subtitle: "Subtitle", billboardDescription: "Billboard",
  billboardDescriptionMobile: "Mobile billboard", description: "Description", descriptionMobile: "Mobile description",
  about: "About", level: "Intro", format: "Lecture",
};

export interface CatalogFixture {
  readonly tables: CatalogTables;
  readonly covers: Readonly<Record<string, readonly string[]>>;
}

function text(entityKind: string, entityId: string, field: string, value: string): CatalogRow<"catalog_texts"> {
  return {
    entity_kind: entityKind, entity_id: entityId, field, locale: "en", text: value, source: "manual", source_ref: "fixture",
    confidence: "high", status: "draft", approved_by: null, approved_at: null, approved_sha256: null,
  };
}

function emptyTables(): CatalogTables {
  return catalogTablesSchema.parse({
    licenses: [], content_sources: [], authors: [], subject_areas: [], subject_subareas: [], courses: [], course_editions: [],
    lessons: [], lesson_videos: [], catalog_texts: [], home_rows: [], home_row_items: [], slug_redirects: [],
  });
}

/** A draft course with an author and none of the review facts. The author exists so the row can be inserted under the real foreign key. */
export function emptyCatalogFixture(): CatalogFixture {
  const tables = emptyTables();
  tables.authors.push({ id: "author-a", slug: "test-author", name: "Test Author", monogram: "TA", role: "Lecturer", kind: "person", cover: null });
  tables.courses.push({
    id: "course-empty", slug: "course-empty", author_id: "author-a", title: "Empty", language_label: "English", lesson_noun: "Lecture",
    status: "draft", featured: false, source_id: null, license_code: null, attribution_text: null, canonical_url: null, rights_status: "unverified",
    rights_notes: null, rights_checked_by: null, rights_checked_at: null, legacy: null, area_id: null, subarea_id: null, cover_from: "own", shared_with: [], published_at: null,
  });
  return { tables: catalogTablesSchema.parse(tables), covers: {} };
}

/** One review-ready draft, one published course for the lookup, and the author cover the owner inventory reads. */
export function readyCatalogFixture(): CatalogFixture {
  const tables = emptyTables();
  tables.subject_areas.push({ id: "fixture-area", title: "Fixture Area", position: 10000 });
  tables.licenses.push({ code: "cc-by", name: "CC BY", url: null, requires_attribution: true, non_commercial: false, share_alike: false, embed_only: false, attribution_template: null });
  tables.content_sources.push({ id: "source-a", kind: "institution-site", title: "Source", publisher: "Example", url: "https://example.org", youtube_channel_id: null, youtube_playlist_id: null });
  tables.authors.push({ id: "author-a", slug: "test-author", name: "Test Author", monogram: "TA", role: "Lecturer", kind: "person", cover: { alt: "Author" } });
  const course = (id: string, slug: string, status: string) => ({
    id, slug, author_id: "author-a", title: slug, language_label: "English", lesson_noun: "Lecture" as const, status, featured: false,
    source_id: "source-a", license_code: "cc-by", attribution_text: null, canonical_url: `https://example.org/${slug}`, rights_status: "cleared",
    rights_notes: null, rights_checked_by: null, rights_checked_at: null, legacy: null, area_id: "fixture-area", subarea_id: null, cover_from: "own", shared_with: [], published_at: null,
  });
  tables.courses.push(course("course-ready", "course-ready", "draft"), course("course-live", "course-live", "published"));
  for (const id of ["ready", "live"] as const) {
    tables.course_editions.push({ id: `edition-${id}`, course_id: `course-${id}`, slug: "2017", label: "2017", term: null, year: 2017, position: 1, resolution: null, source_playlist_ids: [], variant_kind: null, variant_label: null });
    tables.lessons.push({
      id: `lesson-${id}`, course_id: `course-${id}`, edition_id: `edition-${id}`, part: "lectures", slug: `lesson-${id}`, position: 1, kind: "lecture",
      youtube_title: "Lesson", duration_seconds: 60, visible: true, license_code: null, attribution_text: null,
    });
    tables.lesson_videos.push({
      lesson_id: `lesson-${id}`, provider: "youtube", external_id: id === "ready" ? "abcdefghijk" : "bcdefghijkl", playback_id: null, playback_policy: null, resolution_tier: null,
      status: "ok", duration_seconds: 60, youtube_license: null, channel_id: null, checked_at: checkedAt, checked_by: "fixture",
    });
  }
  for (const [field, value] of Object.entries(courseText)) tables.catalog_texts.push(text("course", "course-ready", field, value));
  tables.catalog_texts.push(text("lesson", "lesson-ready", "displayTitle", "Lesson one"));
  return { tables: catalogTablesSchema.parse(tables), covers: { "course-ready": [...REQUIRED_COVERS] } };
}
