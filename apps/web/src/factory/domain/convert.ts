import { z } from "zod";
import { catalogBatchV2Schema, type BatchCourse, type CatalogBatchV2 } from "../../catalog/domain/schema/batch-v2.ts";
import { LIMITS, bundleCoverKinds } from "../../catalog/domain/schema/fields.ts";
import { unprocessable } from "../../kernel/errors.ts";
import { slugify } from "../../kernel/slug.ts";
import type { CuratedCourse, CuratedLesson, CuratedV1 } from "./curated.ts";
import { lessonLink } from "./lesson-link.ts";

// One converter (FACTORY.md). Ids and slugs come from the catalog slug functions. An over-long derived field is an
// error that names the course; nothing is cut to fit. Hold stays in the curated file and out of the batch.
// The batch is CatalogBatchV2: the institution offers the course, the lecturer is course.authorId (D-024).

export interface FactoryText {
  readonly entityKind: "course" | "lesson";
  /** Course id, or `${courseId}/${youtubeId}` for a lesson. */
  readonly entityId: string;
  readonly field: string;
  readonly text: string;
  readonly approved?: boolean;
  readonly approvedBy?: string | null;
  readonly approvedAt?: string | null;
}

export interface ConvertIssue { readonly name: string; readonly message: string; readonly course: string }

export interface Conversion {
  readonly batch: CatalogBatchV2;
  readonly held: readonly { readonly course: string; readonly reason: string }[];
  readonly excluded: number;
}

interface HeldCourse {
  readonly course: string;
  readonly reason: string;
  /** Set when the hold is a field problem. An empty batch refuses with these names. */
  readonly name?: string;
}

/** curated/v1 says `portal`; CatalogBatchV2 says `institution-site`. One mapping, one batch shape. */
const SOURCE_KIND = {
  "youtube-channel": "youtube-channel",
  "youtube-playlist": "youtube-playlist",
  portal: "institution-site",
} as const;

const HERO_KIND = {
  desktop: "hero_desktop_16x9",
  present: "hero_present",
  mobile: "hero_mobile_9x16",
  still: "still_16x9",
} as const satisfies Record<string, (typeof bundleCoverKinds)[number]>;

interface Lecturer {
  readonly id: string;
  readonly slug: string;
  readonly name: string;
  readonly monogram: string;
  readonly kind: "person" | "channel";
}

interface Included {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly originalTitle: string;
  readonly language: string;
  readonly areaId: string;
  readonly subareaId: string | null;
  readonly license: string;
  readonly rights: NonNullable<CuratedCourse["rights"]>;
  readonly canonicalUrl: string;
  readonly year: number;
  readonly coverFrom: string;
  readonly sharedWith: readonly string[];
  readonly cover: NonNullable<CuratedCourse["cover"]> | null;
  readonly lessons: readonly CuratedLesson[];
  readonly lecturer: Lecturer;
  readonly sourceId?: string;
}

function refuse(issues: readonly ConvertIssue[]): never {
  throw unprocessable(issues.map((issue) => issue.message).join("\n"), { issues });
}

function courseName(course: CuratedCourse): string {
  return course.id ?? course.title ?? "unnamed";
}

function lecturerOf(course: CuratedCourse): Lecturer | null {
  const lecturer = course.lecturer;
  if (!lecturer) return null;
  return { id: lecturer.id, slug: lecturer.slug, name: lecturer.name, monogram: lecturer.monogram, kind: lecturer.kind };
}

/** The batch for one approved curated run. Texts are attached as given; approval policy is S14. */
export function convertCurated(curated: CuratedV1, texts: readonly FactoryText[] = []): Conversion {
  const issues: ConvertIssue[] = [];
  if (curated.provenance.titles !== "original") {
    refuse([{ name: "provenance.titles", course: curated.institution.id, message: "provenance.titles: Translated titles are refused; originalTitle is the source title." }]);
  }
  const institution = curated.institution;
  if (institution.slug.length > LIMITS.homeRowId) {
    issues.push({ name: "institution.slug", course: institution.id, message: `institution.slug: ${String(institution.slug.length)} characters exceeds ${String(LIMITS.homeRowId)} (${institution.id}).` });
  }

  const held: HeldCourse[] = [];
  let excluded = 0;
  const included: Included[] = [];
  for (const course of curated.courses) {
    if (course.decision === "hold") {
      held.push({ course: courseName(course), reason: course.holdReason ?? "unspecified" });
      continue;
    }
    if (course.decision === "exclude") { excluded += 1; continue; }
    const named = includeOf(institution.id, course, issues, held);
    if (named) included.push(named);
  }
  const seen = new Set<string>();
  const lecturers = new Map<string, Lecturer>();
  const lecturerSlugs = new Map<string, string>();
  for (const course of included) {
    if (seen.has(course.id)) issues.push({ name: `courses.${course.id}.id`, course: course.id, message: `courses.${course.id}.id: duplicate id ${course.id}.` });
    seen.add(course.id);
    const lecturer = course.lecturer;
    if (lecturer.id === institution.id || lecturer.slug === institution.slug) {
      issues.push({ name: `courses.${course.id}.lecturer`, course: course.id, message: `courses.${course.id}.lecturer: a lecturer is not the institution (D-024).` });
    }
    const previous = lecturers.get(lecturer.id);
    if (previous && (previous.slug !== lecturer.slug || previous.name !== lecturer.name || previous.monogram !== lecturer.monogram || previous.kind !== lecturer.kind)) {
      issues.push({ name: `courses.${course.id}.lecturer`, course: course.id, message: `courses.${course.id}.lecturer: ${lecturer.id} is already a different lecturer.` });
    } else lecturers.set(lecturer.id, lecturer);
    const slugOwner = lecturerSlugs.get(lecturer.slug);
    if (slugOwner !== undefined && slugOwner !== lecturer.id) {
      issues.push({ name: `courses.${course.id}.lecturer.slug`, course: course.id, message: `courses.${course.id}.lecturer.slug: ${lecturer.slug} belongs to ${slugOwner}.` });
    } else lecturerSlugs.set(lecturer.slug, lecturer.id);
  }

  const courses = included.map((course) => toCourse(curated, course, texts, issues));
  if (issues.length > 0) refuse(issues);
  const batchCourses = courses.filter((course): course is BatchCourse => course !== null).sort((a, b) => (a.course.id < b.course.id ? -1 : 1));
  if (batchCourses.length === 0) refuse(heldIssues(held));

  const poster = institution.cover.poster;
  const og = institution.cover.og ?? undefined;
  const parsed = catalogBatchV2Schema.safeParse({
    version: 2,
    updateRefs: false,
    sources: curated.sources.map((source) => ({
      id: source.id, kind: SOURCE_KIND[source.kind], title: source.title, url: source.url,
      ...(source.youtubeChannelId === undefined ? {} : { youtubeChannelId: source.youtubeChannelId }),
    })),
    institutions: [{
      id: institution.id, slug: institution.slug, name: institution.name, monogram: institution.monogram, kind: "institution",
      cover: { poster, ...(og === undefined ? {} : { og }) },
    }],
    lecturers: [...lecturers.values()].sort((a, b) => (a.id < b.id ? -1 : 1)),
    licenses: curated.licenses ?? [],
    areas: curated.areas ?? [],
    subareas: curated.subareas ?? [],
    homeRows: [{
      id: institution.slug, institutionId: institution.id, title: institution.name, fullName: institution.fullName, place: institution.place,
      ...(institution.homeRow.after === undefined ? {} : { after: institution.homeRow.after }),
      visible: institution.homeRow.visible,
      cover: {
        sha: poster, alt: institution.cover.alt, credit: institution.cover.credit, sourceUrl: institution.cover.sourceUrl, license: institution.cover.license,
        ...(institution.cover.note === undefined ? {} : { note: institution.cover.note }),
      },
      ...(og === undefined ? {} : { og }),
    }],
    courses: batchCourses,
  });
  if (!parsed.success) refuse(schemaIssues(parsed.error, institution.id));
  return { batch: parsed.data, held: held.map(({ course, reason }) => ({ course, reason })), excluded };
}

function heldIssues(held: readonly HeldCourse[]): ConvertIssue[] {
  const named = held.filter((item) => item.name !== undefined);
  if (named.length > 0) return named.map((item) => ({ name: item.name ?? "courses", course: item.course, message: item.reason }));
  return [{ name: "courses", course: "batch", message: "Every course is held; a batch needs one included course." }];
}

export function curatedToBatch(curated: CuratedV1, texts: readonly FactoryText[] = []): CatalogBatchV2 {
  return convertCurated(curated, texts).batch;
}

function schemaIssues(error: z.ZodError, course: string): ConvertIssue[] {
  return error.issues.map((issue) => {
    const name = issue.path.length === 0 ? "batch" : issue.path.map((part) => String(part)).join(".");
    return { name, course, message: `${name}: ${issue.message}` };
  });
}

function hold(held: HeldCourse[], course: string, name: string, reason: string): null {
  held.push({ course, name, reason });
  return null;
}

function includeOf(institutionId: string, course: CuratedCourse, issues: ConvertIssue[], held: HeldCourse[]): Included | null {
  const name = courseName(course);
  const range = course.positions;
  let lessons = course.lessons;
  if (range && range.from > range.to) {
    issues.push({ name: `courses.${name}.positions`, course: name, message: `courses.${name}.positions: positions.from is after positions.to.` });
    return null;
  }
  if (range && lessons !== undefined) {
    lessons = lessons.filter((lesson) => lesson.position >= range.from && lesson.position <= range.to);
    if (lessons.length === 0) return hold(held, name, `courses.${name}.positions`, `courses.${name}.positions: no lesson falls inside ${String(range.from)}..${String(range.to)}.`);
  }
  const missing = (["title", "originalTitle", "language", "areaId", "license", "rights", "canonicalUrl", "lecturer"] as const)
    .filter((field) => course[field] === undefined).map(String);
  if (lessons === undefined || lessons.length === 0) missing.push("lessons");
  if (course.year == null) missing.push("year");
  if (course.coverFrom === undefined) missing.push("coverFrom");
  if (course.sharedWith === undefined) missing.push("sharedWith");
  if (course.coverFrom === "own" && course.cover === undefined) missing.push("cover");
  if (missing.length > 0) {
    const field = missing[0] ?? "course";
    return hold(held, name, `courses.${name}.${field}`, missing.map((item) => `courses.${name}.${item}: an included course names ${item}.`).join("\n"));
  }
  const slug = course.slug ?? deriveSlug(course.title ?? "", `courses.${name}.slug`, name, issues);
  const id = course.id ?? (slug === null ? null : fit(`${institutionId}-${slug}`, LIMITS.entityId, `courses.${name}.id`, name, issues));
  if (id === null || slug === null) return null;
  const coverFrom = course.coverFrom ?? "own";
  const lecturer = lecturerOf(course);
  if (course.title === undefined || course.originalTitle === undefined || course.language === undefined || course.areaId === undefined || course.license === undefined || course.rights === undefined || course.canonicalUrl === undefined || course.year == null || lessons === undefined || lecturer === null) return null;
  return {
    id, slug, title: course.title, originalTitle: course.originalTitle, language: course.language, areaId: course.areaId,
    subareaId: course.subareaId ?? null, license: course.license, rights: course.rights, canonicalUrl: course.canonicalUrl,
    year: course.year, coverFrom, sharedWith: course.sharedWith ?? [], cover: course.cover ?? null, lessons, lecturer,
    ...(course.sourceId === undefined ? {} : { sourceId: course.sourceId }),
  };
}

function deriveSlug(title: string, name: string, course: string, issues: ConvertIssue[]): string | null {
  const full = slugify(title, { fallback: "" });
  if (full.length === 0 || full.length > LIMITS.courseSlug) {
    issues.push({ name, course, message: `${name}: slug of "${title}" does not fit ${String(LIMITS.courseSlug)} characters (${course}).` });
    return null;
  }
  return full;
}

function fit(value: string, max: number, name: string, course: string, issues: ConvertIssue[]): string | null {
  if (value.length <= max && value.length > 0) return value;
  issues.push({ name, course, message: `${name}: ${String(value.length)} characters exceeds ${String(max)} (${course}).` });
  return null;
}

function toCourse(curated: CuratedV1, course: Included, texts: readonly FactoryText[], issues: ConvertIssue[]): BatchCourse | null {
  const editionId = fit(`${course.id}-ed`, LIMITS.entityId, `courses.${course.id}.edition.id`, course.id, issues);
  const sourceId = course.sourceId ?? (curated.sources.length === 1 ? curated.sources[0]?.id : undefined);
  if (sourceId === undefined) issues.push({ name: `courses.${course.id}.sourceId`, course: course.id, message: `courses.${course.id}.sourceId: name the source when the run has several (${course.id}).` });
  const editionLabel = String(course.year);
  const editionSlug = `y${String(course.year)}`;
  const taken = new Set<string>();
  const lessons = course.lessons.map((lesson) => {
    const id = fit(`${course.id}-${String(lesson.position).padStart(2, "0")}`, LIMITS.entityId, `courses.${course.id}.lessons.${String(lesson.position)}.id`, course.id, issues);
    return lessonLink(lesson, { title: course.title, slug: course.slug, year: course.year, institution: curated.institution.name }, editionId, id, taken);
  }).filter((lesson): lesson is NonNullable<typeof lesson> => lesson !== null);
  const covers = coversOf(course.cover).sort((left, right) => (left.kind < right.kind ? -1 : 1));
  if (editionId === null || sourceId === undefined || lessons.length !== course.lessons.length) return null;
  const orderedLessons = [...lessons].sort((left, right) => left.position - right.position || (left.id < right.id ? -1 : 1));
  const orderedTexts = textsFor(course, orderedLessons, texts).sort((left, right) => `${left.entityKind}:${left.entityId}:${left.field}`.localeCompare(`${right.entityKind}:${right.entityId}:${right.field}`));
  return {
    institutionId: curated.institution.id,
    homeRowId: curated.institution.slug,
    course: {
      id: course.id, slug: course.slug, title: course.title, authorId: course.lecturer.id, lessonNoun: "Lecture",
      languageLabel: course.language, areaId: course.areaId, subareaId: course.subareaId, licenseCode: course.license,
      sourceId, canonicalUrl: course.canonicalUrl, rightsStatus: course.rights, coverFrom: course.coverFrom, sharedWith: [...course.sharedWith],
    },
    editions: [{ id: editionId, slug: editionSlug, label: editionLabel, position: 1, year: course.year, ...(course.language ? { language: course.language } : {}) }],
    lessons: orderedLessons,
    texts: orderedTexts,
    covers,
  };
}

function textsFor(course: Included, lessons: readonly { readonly id: string; readonly youtubeId: string }[], texts: readonly FactoryText[]) {
  const lessonId = new Map(lessons.map((lesson) => [`${course.id}/${lesson.youtubeId}`, lesson.id]));
  return texts.flatMap((text) => {
    const entityId = text.entityKind === "course" ? (text.entityId === course.id ? course.id : null) : (lessonId.get(text.entityId) ?? null);
    if (entityId === null) return [];
    return [{ entityKind: text.entityKind, entityId, field: text.field, text: text.text, approved: text.approved ?? false, approvedBy: text.approvedBy ?? null, approvedAt: text.approvedAt ?? null }];
  });
}

function coversOf(cover: Included["cover"]): { kind: (typeof bundleCoverKinds)[number]; sha: string }[] {
  if (!cover) return [];
  const covers: { kind: (typeof bundleCoverKinds)[number]; sha: string }[] = [{ kind: "poster_9x16", sha: cover.poster }];
  const heroes = cover.heroes ?? {};
  for (const [name, kind] of Object.entries(HERO_KIND)) {
    const sha = heroes[name as keyof typeof heroes];
    if (sha !== undefined) covers.push({ kind, sha });
  }
  return covers;
}
