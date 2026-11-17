import { continueWatchingTitle } from "../../site/domain/reader-copy.ts";
import { authorCoverSchema } from "./author-cover.ts";
import { assertReleaseCovers } from "./cover-rule.ts";
import { courseStatus } from "./course-status.ts";
import { columnsToVariant } from "./edition-variant.ts";
import { releaseTextEntries, TEXT_FIELDS } from "./fields.ts";
import { projectHomeRow } from "./home-row-kind.ts";
import { RELEASE_SCHEMA_VERSION, releaseSchema, type PublicCatalog, type ReleaseEdition, type ReleaseLesson } from "./release.ts";
import { compareIds, type CatalogRow, type CatalogTables } from "./tables.ts";

const CONTINUE_TITLE = continueWatchingTitle;
type LessonTexts = Pick<ReleaseLesson, keyof typeof TEXT_FIELDS.lesson>;

function entityTexts(
  kind: "course" | "lesson",
  id: string,
  requiredText: (kind: string, entityId: string, field: string) => string,
  approvedText: (kind: string, entityId: string, field: string) => string | null,
): Record<string, string | null> {
  return releaseTextEntries(TEXT_FIELDS[kind], (name, presence) => (presence === "required" ? requiredText(kind, id, name) : approvedText(kind, id, name)));
}

/**
 * Redirects that resolve in this release: the target is a live page and the source is not. A redirect to an unpublished
 * course or a hidden lesson stays in the table, dormant, and comes back when its target does (the doctor lists them).
 */
function liveRedirects(redirects: CatalogTables["slug_redirects"], courses: readonly CatalogRow<"courses">[], lessons: readonly CatalogRow<"lessons">[]) {
  const slugs = new Map(courses.map((course) => [course.id, course.slug]));
  const live = new Set([...slugs.values()].map((slug) => `/c/${slug}`));
  for (const lesson of lessons) live.add(`/c/${slugs.get(lesson.course_id) ?? ""}/${lesson.slug}`);
  return redirects.filter((redirect) => live.has(redirect.to_path) && !live.has(redirect.from_path))
    .map((redirect) => ({ from: redirect.from_path, to: redirect.to_path })).sort((a, b) => a.from.localeCompare(b.from));
}

export interface CompileOptions {
  /** The active release. A published course outside `fresh` keeps its live text while an edited text waits for approval. */
  readonly previous?: PublicCatalog;
  /** Courses whose table text is authoritative because they are being (re)published now. */
  readonly fresh?: ReadonlySet<string>;
}

/**
 * The public projection of the published courses (plan §2.3). Required texts must be approved; an unapproved
 * About is omitted (null). With `options.previous`, an unapproved text of a course outside `options.fresh` falls back to its
 * value in that release, so editing a published course never changes the site, nor blocks another publish, before the
 * edit is approved and the course published again (ADR-18). Courses follow id order, editions their position, lessons their
 * course, edition and position (visible lessons renumbered 1..N per edition, ADR-21), rows their position.
 */
export function compileRelease(tables: CatalogTables, release: { number: number; publishedAt: string }, options: CompileOptions = {}): PublicCatalog {
  const byId = <T extends { id: string }>(rows: readonly T[]) => new Map(rows.map((row) => [row.id, row]));
  const require = <T>(value: T | undefined, message: string): T => {
    if (value === undefined) throw new Error(message);
    return value;
  };
  const texts = new Map(tables.catalog_texts.filter((row) => row.locale === "en").map((row) => [`${row.entity_kind}/${row.entity_id}/${row.field}`, row]));
  const lessonCourse = new Map(tables.lessons.map((lesson) => [lesson.id, lesson.course_id]));
  const live = (kind: string, id: string, field: string): string | null => {
    const { previous, fresh } = options;
    if (!previous || fresh?.has(kind === "course" ? id : lessonCourse.get(id) ?? "")) return null;
    const entity: Readonly<Record<string, unknown>> | undefined = kind === "course" ? previous.courses.find((course) => course.id === id) : previous.lessons.find((lesson) => lesson.id === id);
    const value = entity?.[field];
    return typeof value === "string" ? value : null;
  };
  const approved = (kind: string, id: string, field: string) => {
    const row = texts.get(`${kind}/${id}/${field}`);
    return row?.status === "approved" ? row.text : live(kind, id, field);
  };
  const required = (kind: string, id: string, field: string) => require(approved(kind, id, field) ?? undefined, `${kind} ${id} has no approved ${field}.`);

  const courses = tables.courses.filter((course) => course.status === courseStatus.published).sort((a, b) => compareIds(a.id, b.id));
  const published = new Set(courses.map((course) => course.id));
  const authors = byId(tables.authors);
  const licenses = new Map(tables.licenses.map((license) => [license.code, license]));
  const sources = byId(tables.content_sources);
  const youtube = new Map(tables.lesson_videos.filter((video) => video.provider === "youtube" && video.status === "ok").map((video) => [video.lesson_id, video.external_id]));
  const rows = tables.home_rows.filter((row) => row.visible).sort((a, b) => a.position - b.position);
  const authorIds = new Set([...courses.map((course) => course.author_id), ...rows.flatMap((row) => (row.author_id ? [row.author_id] : []))]);
  const order = new Map(courses.map((course, index) => [course.id, index]));
  const editionPosition = new Map(tables.course_editions.map((edition) => [edition.id, edition.position]));
  const lessons = tables.lessons.filter((lesson) => lesson.visible && published.has(lesson.course_id))
    .sort((a, b) => (order.get(a.course_id) ?? 0) - (order.get(b.course_id) ?? 0)
      || (editionPosition.get(a.edition_id) ?? 0) - (editionPosition.get(b.edition_id) ?? 0) || a.position - b.position);
  // A hidden lesson leaves no gap: the release order counts visible lessons only, per edition (ADR-21).
  const rank = new Map<string, number>();
  const seen = new Map<string, number>();
  for (const lesson of lessons) {
    const next = (seen.get(lesson.edition_id) ?? 0) + 1;
    seen.set(lesson.edition_id, next);
    rank.set(lesson.id, next);
  }
  // Likewise an edition without a visible lesson leaves no gap in the edition positions.
  // Group once. Filtering every lesson for every course is what made a full release take ~30s.
  const editionsByCourse = new Map<string, CatalogRow<"course_editions">[]>();
  for (const edition of tables.course_editions) {
    if (!seen.has(edition.id)) continue;
    const list = editionsByCourse.get(edition.course_id);
    if (list) list.push(edition);
    else editionsByCourse.set(edition.course_id, [edition]);
  }
  const lessonsByEdition = new Map<string, typeof lessons>();
  for (const lesson of lessons) {
    const list = lessonsByEdition.get(lesson.edition_id);
    if (list) list.push(lesson);
    else lessonsByEdition.set(lesson.edition_id, [lesson]);
  }
  const editions = (courseId: string) => (editionsByCourse.get(courseId) ?? [])
    .sort((a, b) => a.position - b.position).map((edition, index) => {
      const members = lessonsByEdition.get(edition.id) ?? [];
      const variant = columnsToVariant(edition.variant_kind, edition.variant_label);
      return {
        id: edition.id, slug: edition.slug, label: edition.label, term: edition.term as ReleaseEdition["term"], year: edition.year, position: index + 1,
        resolution: edition.resolution, lessonCount: members.length, durationSeconds: members.reduce((sum, lesson) => sum + lesson.duration_seconds, 0),
        parts: { lectures: members.filter((lesson) => lesson.part === "lectures").length, labs: members.filter((lesson) => lesson.part === "labs").length },
        ...(variant ? { variant } : {}),
        ...(typeof edition.language === "string" ? { language: edition.language } : {}),
      };
    });

  const courseRights = (course: CatalogRow<"courses">) => {
    const license = require(licenses.get(course.license_code ?? ""), `Course ${course.id} has no license.`);
    const source = require(sources.get(course.source_id ?? ""), `Course ${course.id} has no source.`);
    return {
      licenseCode: license.code, licenseName: license.name, licenseUrl: license.url, attribution: course.attribution_text,
      canonicalUrl: require(course.canonical_url ?? undefined, `Course ${course.id} has no canonical URL.`), sourceTitle: source.title, sourceUrl: source.url,
    };
  };
  const payload: PublicCatalog = {
    schemaVersion: RELEASE_SCHEMA_VERSION,
    number: release.number,
    publishedAt: release.publishedAt,
    authors: [...authorIds].sort(compareIds).map((id) => {
      const author = require(authors.get(id), `Unknown author ${id}.`);
      return { id: author.id, slug: author.slug, name: author.name, monogram: author.monogram, role: author.role, kind: author.kind as PublicCatalog["authors"][number]["kind"], ...(author.cover ? { cover: authorCoverSchema.parse(author.cover) } : {}) };
    }),
    courses: courses.map((course) => ({
      id: course.id, slug: course.slug, authorId: course.author_id, title: course.title, ...(course.area_id === null ? {} : { areaId: course.area_id }), ...(course.subarea_id === null ? {} : { subareaId: course.subarea_id }),       coverFrom: course.cover_from,
      ...entityTexts("course", course.id, required, approved) as Pick<PublicCatalog["courses"][number], keyof typeof TEXT_FIELDS.course>,
      languageLabel: course.language_label, lessonNoun: course.lesson_noun as PublicCatalog["courses"][number]["lessonNoun"], featured: course.featured,
      rights: courseRights(course), editions: editions(course.id),
    })),
    lessons: lessons.map((lesson) => ({
      id: lesson.id, slug: lesson.slug, courseId: lesson.course_id, editionId: lesson.edition_id, part: lesson.part as ReleaseLesson["part"], order: rank.get(lesson.id) ?? lesson.position,
      kind: lesson.kind as PublicCatalog["lessons"][number]["kind"], youtubeTitle: lesson.youtube_title,
      ...entityTexts("lesson", lesson.id, required, approved) as LessonTexts,
      youtubeId: require(youtube.get(lesson.id), `Lesson ${lesson.id} has no checked YouTube video.`), durationSeconds: lesson.duration_seconds,
      ...(lesson.license_code === null ? {} : { rights: { licenseCode: lesson.license_code, attribution: lesson.attribution_text } }),
    })),
    home: {
      featuredCourseId: courses.find((course) => course.featured)?.id ?? null,
      rows: rows.map((row) => projectHomeRow({
        id: row.id,
        kind: row.kind as PublicCatalog["home"]["rows"][number]["kind"],
        title: row.title ?? (row.author_id ? require(authors.get(row.author_id), `Unknown author ${row.author_id}.`).name : CONTINUE_TITLE),
        authorId: row.author_id,
        institutionId: row.institution_id,
        courseIds: tables.home_row_items.filter((item) => item.row_id === row.id && published.has(item.course_id))
          .sort((a, b) => a.position - b.position).map((item) => item.course_id),
        cover: row.cover,
        fullName: row.full_name,
        place: row.place,
      })),
    },
    redirects: liveRedirects(tables.slug_redirects, courses, lessons),
    ...(courses.some((course) => course.area_id !== null) ? { areas: [...tables.subject_areas].sort((a, b) => a.position - b.position).map((area) => ({ id: area.id, title: area.title })) } : {}),
    // ADR-26: the subareas (area order, then their position) once a published course has one.
    ...(courses.some((course) => course.subarea_id !== null) ? { subareas: subareasInOrder(tables) } : {}),
  };
  // Universities only. Author rows in the frozen v1 snapshot have no covers; the admin cutter checks those (ADR-40).
  const catalog = releaseSchema.parse(payload);
  assertReleaseCovers(catalog, "university");
  return catalog;
}

/** Every subarea in display order: its area's fixed position first, then its own position inside the area. */
export function subareasInOrder(tables: Pick<CatalogTables, "subject_areas" | "subject_subareas">): { id: string; areaId: string; title: string }[] {
  const areaPosition = new Map(tables.subject_areas.map((area) => [area.id, area.position]));
  return [...tables.subject_subareas]
    .sort((a, b) => (areaPosition.get(a.area_id) ?? Number.MAX_SAFE_INTEGER) - (areaPosition.get(b.area_id) ?? Number.MAX_SAFE_INTEGER) || a.position - b.position)
    .map((subarea) => ({ id: subarea.id, areaId: subarea.area_id, title: subarea.title }));
}
