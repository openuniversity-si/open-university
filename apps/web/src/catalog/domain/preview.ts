import { courseStatus } from "./course-status.ts";
import { TEXT_FIELDS } from "./fields.ts";
import type { CatalogRow, CatalogTables } from "./tables.ts";

/** Placeholder rights of a preview-only course; never part of a stored release. */
export const PREVIEW_RIGHTS = { license: "preview-rights-missing", source: "preview-source-missing", url: "https://preview.invalid/rights-missing" } as const;
const PREVIEW_APPROVER = "preview";

/**
 * The tables as a reviewer previews them (plan §4.4): the scoped draft/review courses count as published, every text of a
 * scoped course counts as approved (drafts included, missing required ones as `[field]`), any YouTube video of a previewed
 * course plays, and missing rights get placeholders. Courses without a playable lesson stay out. compileRelease then builds the preview catalog unchanged.
 * `scope` is a course id, or null for every draft/review course.
 */
export function previewTables(tables: CatalogTables, scope: string | null): CatalogTables {
  const youtube = new Set(tables.lesson_videos.filter((video) => video.provider === "youtube").map((video) => video.lesson_id));
  const playable = new Set(tables.lessons.filter((lesson) => lesson.visible && youtube.has(lesson.id)).map((lesson) => lesson.course_id));
  const inScope = (course: CatalogRow<"courses">) => scope === null || course.id === scope;
  const extra = new Set(tables.courses.filter((course) => (course.status === courseStatus.draft || course.status === courseStatus.review) && inScope(course) && playable.has(course.id)).map((course) => course.id));
  // Published courses in scope show their unpublished text edits too.
  const edited = new Set([...extra, ...tables.courses.filter((course) => course.status === courseStatus.published && inScope(course)).map((course) => course.id)]);
  const courses = tables.courses.map((course) => (extra.has(course.id) ? {
    ...course, status: courseStatus.published, featured: false,
    license_code: course.license_code ?? PREVIEW_RIGHTS.license, source_id: course.source_id ?? PREVIEW_RIGHTS.source, canonical_url: course.canonical_url ?? PREVIEW_RIGHTS.url,
  } : course));
  const approve = (row: CatalogRow<"catalog_texts">): CatalogRow<"catalog_texts"> => ({ ...row, status: "approved", approved_by: row.approved_by ?? PREVIEW_APPROVER });
  const texts = tables.catalog_texts.map((row) => (row.entity_kind !== "author" && isPreviewed(row, edited, tables) ? approve(row) : row));
  const present = new Set(texts.map((row) => `${row.entity_kind}/${row.entity_id}/${row.field}`));
  const placeholder = (kind: "course" | "lesson", id: string, field: string): CatalogRow<"catalog_texts"> => ({
    entity_kind: kind, entity_id: id, field, locale: "en", text: `[${field}]`, source: "manual", source_ref: "preview", confidence: "low",
    status: "approved", approved_by: PREVIEW_APPROVER, approved_at: null, approved_sha256: null,
  });
  for (const id of extra) {
    for (const [field, spec] of Object.entries(TEXT_FIELDS.course)) if (spec.publish && !present.has(`course/${id}/${field}`)) texts.push(placeholder("course", id, field));
    for (const lesson of tables.lessons.filter((row) => row.course_id === id)) {
      for (const [field, spec] of Object.entries(TEXT_FIELDS.lesson)) {
        if (spec.publish && !present.has(`lesson/${lesson.id}/${field}`)) texts.push(placeholder("lesson", lesson.id, field));
      }
    }
  }
  return {
    ...tables,
    licenses: [...tables.licenses, { code: PREVIEW_RIGHTS.license, name: "Rights not set (preview)", url: null, requires_attribution: false, non_commercial: false, share_alike: false, embed_only: true, attribution_template: null }],
    content_sources: [...tables.content_sources, { id: PREVIEW_RIGHTS.source, kind: "institution-site", title: "Source not set (preview)", publisher: "Preview", url: PREVIEW_RIGHTS.url, youtube_channel_id: null, youtube_playlist_id: null }],
    courses,
    // A previewed lesson needs only its YouTube id; the embed check is the reviewer's job here.
    lessons: tables.lessons.filter((lesson) => !extra.has(lesson.course_id) || youtube.has(lesson.id)),
    lesson_videos: tables.lesson_videos.map((video) => (video.provider === "youtube" && extra.has(courseOf(video.lesson_id, tables)) ? { ...video, status: "ok" } : video)),
    catalog_texts: texts,
  };
}

function courseOf(lessonId: string, tables: CatalogTables): string {
  return tables.lessons.find((lesson) => lesson.id === lessonId)?.course_id ?? "";
}
function isPreviewed(row: CatalogRow<"catalog_texts">, courses: ReadonlySet<string>, tables: CatalogTables): boolean {
  return row.entity_kind === "course" ? courses.has(row.entity_id) : courses.has(courseOf(row.entity_id, tables));
}
