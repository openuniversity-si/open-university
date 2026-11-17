import type { Queryable } from "../../platform/db/uow.ts";
import type { CatalogRow } from "../domain/tables.ts";
import { evaluateRules, type CourseFacts, type RuleTarget } from "../domain/rules/status.ts";
import { iso } from "../domain/rules-helpers.ts";
import { pageCoverKinds } from "./cover-kinds.ts";
import { selectCoursePage } from "./projections-repo.ts";

/**
 * One keyset page of the admin course list, as a read model. Drafts stay in the list, and pending rules are still
 * `evaluateRules` on the page's facts (INV-R2). Cover kinds still come from `resolveCover` (INV-M3).
 */
export async function projectCoursePage(db: Queryable, filter: { readonly status?: string; readonly cursor?: string; readonly limit: number }): Promise<{
  readonly courses: ProjectedCourse[];
  readonly nextCursor: string | null;
}> {
  const status = filter.status ?? null;
  const rows = await selectCoursePage(db, status, filter.cursor ?? "", filter.limit + 1);
  const page = rows.slice(0, filter.limit);
  const nextCursor = rows.length > filter.limit ? stringOf(page.at(-1)?.id) : null;
  if (page.length === 0) return { courses: [], nextCursor: null };
  const covers = await pageCoverKinds(db, page.map((row) => ({
    id: stringOf(row.id),
    areaId: typeof row.area_id === "string" ? row.area_id : null,
    subareaId: typeof row.subarea_id === "string" ? row.subarea_id : null,
    coverFrom: stringOf(row.cover_from),
  })));
  return {
    courses: page.map((row) => projectCourse(row, covers.get(stringOf(row.id)) ?? NO_COVERS)),
    nextCursor,
  };
}

export interface ProjectedCourse {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly authorId: string;
  readonly status: string;
  readonly featured: boolean;
  readonly revision: number;
  readonly publishedAt: string | null;
  readonly areaId: string | null;
  readonly subareaId: string | null;
  readonly counts: { readonly editions: number; readonly lessons: number; readonly visibleLessons: number; readonly texts: number; readonly draftTexts: number };
  readonly pending: { readonly target: RuleTarget | null; readonly failed: ReturnType<typeof evaluateRules> };
}

const NO_COVERS: ReadonlySet<string> = new Set();

interface EditionFact { readonly id: string; readonly slug: string; readonly position: number; readonly year: number; readonly term: string | null; readonly variant_kind: string | null; readonly variant_label: string | null; readonly language: string | null }
interface LessonFact { readonly id: string; readonly edition_id: string; readonly position: number; readonly visible: boolean }
interface VideoFact { readonly lesson_id: string; readonly status: string }
interface TextFact {
  readonly entity_kind: string;
  readonly entity_id: string;
  readonly field: string;
  readonly locale: string;
  readonly text: string;
  readonly status: string;
  readonly approved_sha256: string | null;
}

const EMPTY_EDITIONS: readonly CatalogRow<"course_editions">[] = [];
const EMPTY_LESSONS: readonly CatalogRow<"lessons">[] = [];
const EMPTY_TEXTS = new Map<string, CatalogRow<"catalog_texts">>();
const EMPTY_VIDEOS = new Map<string, string>();

function projectCourse(row: Record<string, unknown>, coverKinds: ReadonlySet<string>): ProjectedCourse {
  const id = stringOf(row.id);
  const editionFacts = asArray<EditionFact>(row.editions);
  const lessonFacts = asArray<LessonFact>(row.lessons);
  const editions = editionFacts.length === 0 ? EMPTY_EDITIONS : editionFacts.map((edition) => editionRow(id, edition)).sort((a, b) => a.position - b.position);
  const rank = editions.length === 0 ? null : new Map(editions.map((edition, index) => [edition.id, index]));
  const lessons = lessonFacts.length === 0 ? EMPTY_LESSONS : lessonFacts.map((lesson) => lessonRow(id, lesson))
    .sort((a, b) => (rank?.get(a.edition_id) ?? editions.length) - (rank?.get(b.edition_id) ?? editions.length) || a.position - b.position);
  const textFacts = asArray<TextFact>(row.texts);
  const english = textFacts.length === 0 ? EMPTY_TEXTS : englishTexts(textFacts);
  const videoFacts = asArray<VideoFact>(row.videos);
  const course = courseRow(row);
  const target: RuleTarget | null = course.status === "draft" ? "review" : course.status === "archived" ? null : "published";
  const facts: CourseFacts = {
    course,
    authorExists: row.author_exists === true,
    editions,
    lessons,
    youtube: videoFacts.length === 0 ? EMPTY_VIDEOS : new Map(videoFacts.map((video) => [video.lesson_id, video.status])),
    texts: english,
    coverKinds,
    inHomeRow: row.in_home === true,
  };
  return {
    id: course.id, slug: course.slug, title: course.title, authorId: course.author_id, status: course.status, featured: course.featured,
    revision: Number(row.revision ?? 1), publishedAt: iso(row.published_at), areaId: course.area_id, subareaId: course.subarea_id,
    counts: {
      editions: editions.length,
      lessons: lessons.length,
      visibleLessons: lessons.length === 0 ? 0 : lessons.filter((lesson) => lesson.visible).length,
      texts: textFacts.length,
      draftTexts: textFacts.filter((text) => text.status === "draft").length,
    },
    pending: { target, failed: target ? evaluateRules(target, facts) : [] },
  };
}

function englishTexts(texts: readonly TextFact[]): Map<string, CatalogRow<"catalog_texts">> {
  const english = new Map<string, CatalogRow<"catalog_texts">>();
  for (const text of texts) {
    if (text.locale !== "en") continue;
    const parsed = textRow(text);
    english.set(`${parsed.entity_kind}/${parsed.entity_id}/${parsed.field}`, parsed);
  }
  return english;
}

function courseRow(row: Record<string, unknown>): CatalogRow<"courses"> {
  return {
    id: stringOf(row.id), slug: stringOf(row.slug), author_id: stringOf(row.author_id), title: stringOf(row.title),
    language_label: stringOf(row.language_label), lesson_noun: stringOf(row.lesson_noun), status: stringOf(row.status),
    featured: row.featured === true, source_id: nullableText(row.source_id), license_code: nullableText(row.license_code),
    attribution_text: nullableText(row.attribution_text), canonical_url: nullableText(row.canonical_url),
    rights_status: stringOf(row.rights_status), rights_notes: nullableText(row.rights_notes),
    rights_checked_by: nullableText(row.rights_checked_by), rights_checked_at: iso(row.rights_checked_at),
    legacy: (row.legacy ?? null) as CatalogRow<"courses">["legacy"], area_id: nullableText(row.area_id), subarea_id: nullableText(row.subarea_id),
    published_at: iso(row.published_at),
    cover_from: stringOf(row.cover_from),
    shared_with: Array.isArray(row.shared_with) ? row.shared_with.filter((item): item is string => typeof item === "string") : [],
  };
}

function editionRow(courseId: string, edition: EditionFact): CatalogRow<"course_editions"> {
  return {
    id: edition.id, course_id: courseId, slug: edition.slug, label: edition.slug,
    term: edition.term, year: edition.year, position: edition.position, resolution: null, source_playlist_ids: [],
    variant_kind: edition.variant_kind, variant_label: edition.variant_label, language: edition.language,
  };
}

function lessonRow(courseId: string, lesson: LessonFact): CatalogRow<"lessons"> {
  return {
    id: lesson.id, course_id: courseId, edition_id: lesson.edition_id, part: "lectures", slug: lesson.id,
    position: lesson.position, kind: "lecture", youtube_title: "projection", duration_seconds: 1,
    visible: lesson.visible, license_code: null, attribution_text: null,
  };
}

function textRow(text: TextFact): CatalogRow<"catalog_texts"> {
  return {
    entity_kind: text.entity_kind, entity_id: text.entity_id, field: text.field, locale: text.locale,
    text: text.text, source: "manual", source_ref: "projection", confidence: "low", status: text.status,
    approved_by: null, approved_at: null, approved_sha256: text.approved_sha256,
  };
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function stringOf(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
