import { z } from "zod";
import { authorCoverSchema } from "./author-cover.ts";
import { universityCoverSchema } from "./university-cover.ts";
import { COVER_FROM_PATTERN } from "./cover-source.ts";
import { indistinctEditionMessage, indistinctEditions } from "./edition-variant.ts";
import { homeRowKinds, homeRowSpec } from "./home-row-kind.ts";
import { lessonKinds } from "./lesson-kind.ts";
import { TEXT_FIELDS, type TextField } from "./fields.ts";
import { EDITION_YEARS, LIMITS, authorKinds, editionVariantSchema, lessonNouns } from "./schema/fields.ts";
import { duplicateYoutubeIdsInCourse, youtubeIdSchema } from "./youtube-identity.ts";
import { EXTENT } from "../../kernel/extent.ts";

// The public projection the site reads from the active catalog_releases row (plan §2.3).
// No fixed counts: any number of authors, courses, editions, lessons and rows is valid if the invariants hold.
// The site reads it through getCatalog() (src/catalog/server/read.ts, ADR-17). Version 2 adds course editions (ADR-21);
// stored releases are immutable, so a version 1 payload is normalized on read (parseRelease), never rewritten.
export const RELEASE_SCHEMA_VERSION = 2;

const text = z.string().trim().min(EXTENT.one);
const slug = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
const https = z.string().regex(/^https:\/\//);
const path = z.string().regex(/^\/c\//);

type TextZod<F> = F extends { readonly release: "required" }
  ? typeof text
  : F extends { readonly release: "nullable" }
    ? ReturnType<typeof text.nullable>
    : F extends { readonly release: "optional" }
      ? ReturnType<typeof text.optional>
      : never;

type ReleaseTextZod<Source> = { -readonly [Name in keyof Source]: TextZod<Source[Name]> };

function releaseTextShape(kind: "course"): ReleaseTextZod<typeof TEXT_FIELDS.course>;
function releaseTextShape(kind: "lesson"): ReleaseTextZod<typeof TEXT_FIELDS.lesson>;
function releaseTextShape(kind: "course" | "lesson"): Record<string, z.ZodType> {
  const shape: Record<string, z.ZodType> = {};
  for (const [name, spec] of Object.entries(TEXT_FIELDS[kind] as Record<string, TextField>)) {
    if (spec.release === "required") shape[name] = text;
    else if (spec.release === "nullable") shape[name] = text.nullable();
    else if (spec.release === "optional") shape[name] = text.optional();
  }
  return shape;
}

/** Course and lesson text keys, generated from the leaf. A key the leaf lacks is rejected. */
export const courseReleaseTextSchema = z.strictObject(releaseTextShape("course"));
export const lessonReleaseTextSchema = z.strictObject(releaseTextShape("lesson"));

const authorSchema = z.strictObject({
  id: text, slug, name: text, monogram: text.max(LIMITS.monogram), role: text, kind: z.enum(authorKinds),
  /** Optional (releases before 0010 have none); see author-cover.ts. */
  cover: authorCoverSchema.optional(),
});
const courseSchema = z.strictObject({
  id: text, slug: slug.max(LIMITS.courseSlug), authorId: text, title: text,
  /** The course's one subject area (ADR-25), optional (releases before 0012 have none); one of the release's `areas`. */
  areaId: slug.optional(),
  /** The course's optional subarea (ADR-26), one of the release's `subareas` of the same area; releases before 0014 have none. */
  subareaId: slug.optional(),
  /** D-031. New compiles always emit it. A stored release from before the declaration parses without it and inherits nothing. */
  coverFrom: z.string().regex(COVER_FROM_PATTERN).optional(),
  /** Retired by D-031. Kept so an old payload still parses; it does not grant a cover. */
  coverProvisional: z.boolean().optional(),
  ...courseReleaseTextSchema.shape,
  languageLabel: text, lessonNoun: z.enum(lessonNouns), featured: z.boolean(),
  rights: z.strictObject({
    licenseCode: text, licenseName: text, licenseUrl: https.nullable(), attribution: text.nullable(),
    canonicalUrl: https, sourceTitle: text, sourceUrl: https,
  }),
});
const count = z.number().int().nonnegative();
export const EDITION_TERMS = ["spring", "summer", "fall", "winter"] as const;
export const LESSON_PARTS = ["lectures", "labs"] as const;
const editionSchema = z.strictObject({
  id: text, slug: slug.max(LIMITS.editionSlug), label: text.max(LIMITS.editionLabel), term: z.enum(EDITION_TERMS).nullable(), year: z.number().int().min(EDITION_YEARS.min).max(EDITION_YEARS.max),
  position: z.number().int().positive(), resolution: text.nullable(), lessonCount: count, durationSeconds: count,
  parts: z.strictObject({ lectures: count, labs: count }),
  /** D-034. Omitted when the edition is the only offering of its year. Absence is not a second code path. */
  variant: editionVariantSchema.optional(),
  /** D-035. Omitted when the edition does not declare a language. A language variant uses this same string. */
  language: text.max(LIMITS.languageLabel).optional(),
});
const v1LessonSchema = z.strictObject({
  id: text, slug: slug.max(LIMITS.lessonSlug), courseId: text, order: z.number().int().positive(),
  kind: z.enum(lessonKinds),
  youtubeTitle: text, ...lessonReleaseTextSchema.shape,
  youtubeId: youtubeIdSchema, durationSeconds: z.number().int().positive(),
  rights: z.strictObject({ licenseCode: text, attribution: text.nullable() }).optional(),
});
const lessonSchema = v1LessonSchema.extend({ editionId: text, part: z.enum(LESSON_PARTS) });
const rowSchema = z.strictObject({
  id: slug, kind: z.enum(homeRowKinds), title: text, authorId: text.optional(), institutionId: text.optional(), courseIds: z.array(text),
  /** Curated rows only, optional (releases before 0011 have none); see university-cover.ts. */
  cover: universityCoverSchema.optional(),
  /** Curated rows only, optional (0013): "Yale University" and "New Haven, CT" under the university card. */
  fullName: text.optional(),
  place: text.optional(),
});

// Key order is the payload's byte order (releaseSha): head, then courses and lessons, then tail.
const releaseHead = { number: z.number().int().positive(), publishedAt: z.iso.datetime({ offset: true }), authors: z.array(authorSchema) };
const areaSchema = z.strictObject({ id: slug, title: text });
const subareaSchema = z.strictObject({ id: slug, areaId: slug, title: text });
const releaseTail = {
  home: z.strictObject({ featuredCourseId: text.nullable(), rows: z.array(rowSchema) }), redirects: z.array(z.strictObject({ from: path, to: path })),
  /** The global subject areas in their fixed order (ADR-25, docs/catalog/areas.md); optional (releases before 0012 have none). */
  areas: z.array(areaSchema).optional(),
  /** The subareas in display order (ADR-26, docs/catalog/subareas.md); optional (releases before 0014 have none). */
  subareas: z.array(subareaSchema).optional(),
};
type ReleaseBase = z.infer<z.ZodObject<typeof releaseHead & typeof releaseTail>> & { courses: { id: string; slug: string; authorId: string; featured: boolean; areaId?: string | undefined; subareaId?: string | undefined }[]; lessons: { id: string; slug: string; courseId: string; youtubeId: string }[] };

/** The invariants both versions share; `order` contiguity is per course in v1 and per edition in v2 (checked by the caller). */
function checkRelease(release: ReleaseBase, fail: (message: string) => void): void {
  const unique = (values: readonly string[], label: string) => {
    const seen = new Set<string>();
    for (const value of values) {
      if (seen.has(value)) fail(`Duplicate ${label}: ${value}.`);
      seen.add(value);
    }
  };
  unique(release.authors.map((entry) => entry.id), "author ID");
  unique(release.authors.map((entry) => entry.slug), "author slug");
  unique(release.courses.map((entry) => entry.id), "course ID");
  unique(release.courses.map((entry) => entry.slug), "course slug");
  unique(release.lessons.map((entry) => entry.id), "lesson ID");
  unique(release.lessons.map((entry) => `${entry.courseId}/${entry.slug}`), "lesson slug");
  for (const clash of duplicateYoutubeIdsInCourse(release.lessons)) fail(`Duplicate YouTube ID in ${clash.courseId}: ${clash.youtubeId}.`);

  const authorIds = new Set(release.authors.map((author) => author.id));
  const courses = new Map(release.courses.map((course) => [course.id, course]));
  for (const course of release.courses) {
    if (!authorIds.has(course.authorId)) fail(`Unknown author for ${course.id}.`);
    if (!release.lessons.some((lesson) => lesson.courseId === course.id)) fail(`Course ${course.id} has no lessons.`);
  }
  for (const lesson of release.lessons) if (!courses.has(lesson.courseId)) fail(`Unknown course for ${lesson.id}.`);
  unique((release.areas ?? []).map((area) => area.id), "area ID");
  const areaIds = new Set((release.areas ?? []).map((area) => area.id));
  for (const course of release.courses) if (course.areaId !== undefined && !areaIds.has(course.areaId)) fail(`Unknown area ${course.areaId} for ${course.id}.`);
  // ADR-26: subarea ids are global (never an area id, never repeated) and a course's subarea lies in the course's own area.
  unique((release.subareas ?? []).map((subarea) => subarea.id), "subarea ID");
  const subareas = new Map((release.subareas ?? []).map((subarea) => [subarea.id, subarea]));
  for (const subarea of release.subareas ?? []) {
    if (!areaIds.has(subarea.areaId)) fail(`Unknown area ${subarea.areaId} for subarea ${subarea.id}.`);
    if (areaIds.has(subarea.id)) fail(`Subarea ${subarea.id} reuses an area ID.`);
  }
  for (const course of release.courses) {
    if (course.subareaId === undefined) continue;
    const subarea = subareas.get(course.subareaId);
    if (!subarea) fail(`Unknown subarea ${course.subareaId} for ${course.id}.`);
    else if (subarea.areaId !== course.areaId) fail(`Subarea ${course.subareaId} of ${course.id} is in ${subarea.areaId}, not in the course's area ${String(course.areaId)}.`);
  }

  // Every course in a release is published, so the featured course must be one of them.
  const featured = release.courses.filter((course) => course.featured).map((course) => course.id);
  if (featured.length > 1) fail("More than one featured course.");
  const { featuredCourseId } = release.home;
  if (featuredCourseId !== null && !courses.has(featuredCourseId)) fail(`Featured course ${featuredCourseId} is not published.`);
  if (JSON.stringify(featured) !== JSON.stringify(featuredCourseId === null ? [] : [featuredCourseId])) fail("home.featuredCourseId differs from the featured flag.");

  unique(release.home.rows.map((row) => row.id), "row ID");
  for (const kind of homeRowKinds) {
    const cap = homeRowSpec(kind).maxRows;
    if (cap !== null && release.home.rows.filter((row) => row.kind === kind).length > cap) fail("More than one continue row.");
  }
  for (const row of release.home.rows) {
    unique(row.courseIds, `course in row ${row.id}`);
    const spec = homeRowSpec(row.kind);
    if (!spec.catalogCourses && !spec.author && (row.courseIds.length > 0 || row.authorId !== undefined)) fail("The continue row is derived from progress, not catalog course IDs.");
    if (spec.author && (row.authorId === undefined || !authorIds.has(row.authorId))) fail(`Unknown author for row ${row.id}.`);
    if (!spec.author && spec.catalogCourses && spec.cover === "own" && row.authorId !== undefined) fail(`Curated row ${row.id} must not name an author.`);
    for (const id of row.courseIds) if (!courses.has(id)) fail(`Unknown course ${id} in row ${row.id}.`);
  }

  // A redirect starts at a dead path and ends at a live one, which also rules out chains and cycles.
  const live = new Set(release.courses.map((course) => `/c/${course.slug}`));
  for (const lesson of release.lessons) {
    const course = courses.get(lesson.courseId);
    if (course) live.add(`/c/${course.slug}/${lesson.slug}`);
  }
  unique(release.redirects.map((redirect) => redirect.from), "redirect source");
  for (const { from, to } of release.redirects) {
    if (live.has(from)) fail(`Redirect ${from} shadows a live page.`);
    if (!live.has(to)) fail(`Redirect ${from} points to a missing page ${to}.`);
  }
}

const contiguous = (values: readonly number[]) => [...values].sort((a, b) => a - b).every((value, index) => value === index + 1);
const issue = (ctx: z.RefinementCtx) => (message: string) => { ctx.addIssue({ code: "custom", message }); };

/** One pass. Filtering the whole lesson list once per course or edition is quadratic on a full catalog. */
function groupBy<T>(rows: readonly T[], key: (row: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const id = key(row);
    const list = groups.get(id);
    if (list) list.push(row);
    else groups.set(id, [row]);
  }
  return groups;
}

/** Release #1 (before editions): lesson order is contiguous per course. Read-only: nothing writes version 1 anymore. */
export const releaseV1Schema = z.strictObject({
  schemaVersion: z.literal(1), ...releaseHead, courses: z.array(courseSchema), lessons: z.array(v1LessonSchema), ...releaseTail,
}).superRefine((release, ctx) => {
  const fail = issue(ctx);
  checkRelease(release, fail);
  const byCourse = groupBy(release.lessons, (lesson) => lesson.courseId);
  for (const course of release.courses) {
    if (!contiguous((byCourse.get(course.id) ?? []).map((lesson) => lesson.order))) fail(`Non-contiguous order in ${course.id}.`);
  }
});

export const releaseSchema = z.strictObject({
  schemaVersion: z.literal(RELEASE_SCHEMA_VERSION), ...releaseHead,
  courses: z.array(courseSchema.extend({ editions: z.array(editionSchema).min(EXTENT.one) })),
  lessons: z.array(lessonSchema),
  ...releaseTail,
}).superRefine((release, ctx) => {
  const fail = issue(ctx);
  checkRelease(release, fail);
  const editionCourse = new Map<string, string>();
  for (const course of release.courses) {
    for (const edition of course.editions) {
      if (editionCourse.has(edition.id)) fail(`Duplicate edition ID: ${edition.id}.`);
      editionCourse.set(edition.id, course.id);
    }
    if (new Set(course.editions.map((edition) => edition.slug)).size !== course.editions.length) fail(`Duplicate edition slug in ${course.id}.`);
    for (const clash of indistinctEditions(course.editions)) fail(indistinctEditionMessage(clash.year, clash.ids));
    if (!contiguous(course.editions.map((edition) => edition.position))) fail(`Non-contiguous edition positions in ${course.id}.`);
    if (course.editions.some((edition, index) => edition.position !== index + 1)) fail(`Editions of ${course.id} are not in position order.`);
  }
  for (const lesson of release.lessons) if (editionCourse.get(lesson.editionId) !== lesson.courseId) fail(`Lesson ${lesson.id} names an edition of another course.`);
  const byEdition = groupBy(release.lessons, (lesson) => lesson.editionId);
  for (const course of release.courses) {
    for (const edition of course.editions) {
      const lessons = byEdition.get(edition.id) ?? [];
      if (lessons.length === 0) fail(`Edition ${edition.id} has no lessons.`);
      if (!contiguous(lessons.map((lesson) => lesson.order))) fail(`Non-contiguous order in edition ${edition.id}.`);
      let lectures = 0;
      let labs = 0;
      let duration = 0;
      for (const lesson of lessons) {
        if (lesson.part === "lectures") lectures += 1;
        else labs += 1;
        duration += lesson.durationSeconds;
      }
      if (edition.lessonCount !== lessons.length || edition.parts.lectures !== lectures || edition.parts.labs !== labs || edition.durationSeconds !== duration) {
        fail(`Edition ${edition.id} counts differ from its lessons.`);
      }
    }
  }
});

export type PublicCatalog = z.infer<typeof releaseSchema>;
export type ReleaseCourse = PublicCatalog["courses"][number];
export type ReleaseEdition = ReleaseCourse["editions"][number];
export type ReleaseLesson = PublicCatalog["lessons"][number];
export type ReleaseV1 = z.infer<typeof releaseV1Schema>;
/** A catalog_releases payload as stored: any version the reader accepts. */
export type StoredRelease = ReleaseV1 | PublicCatalog;

/** The edition a version 1 course reads as: one per course, never shown (a single edition hides the selector, ADR-21). */
export function syntheticEditionId(courseId: string): string {
  return `${courseId}-edition`;
}

/** Version 1 → 2 at read time: one synthetic edition per course holding every lesson as a lecture, in the same order. */
export function normalizeRelease(release: StoredRelease): PublicCatalog {
  if (release.schemaVersion === RELEASE_SCHEMA_VERSION) return release;
  const year = new Date(release.publishedAt).getUTCFullYear();
  const byCourse = groupBy(release.lessons, (lesson) => lesson.courseId);
  return releaseSchema.parse({
    ...release,
    schemaVersion: RELEASE_SCHEMA_VERSION,
    courses: release.courses.map((course) => {
      const lessons = byCourse.get(course.id) ?? [];
      return {
        ...course,
        editions: [{
          id: syntheticEditionId(course.id), slug: String(year), label: String(year), term: null, year, position: 1, resolution: null,
          lessonCount: lessons.length, durationSeconds: lessons.reduce((sum, lesson) => sum + lesson.durationSeconds, 0), parts: { lectures: lessons.length, labs: 0 },
        }],
      };
    }),
    lessons: release.lessons.map((lesson) => ({ ...lesson, editionId: syntheticEditionId(lesson.courseId), part: "lectures" })),
  });
}

/** Any stored payload (version 1 or 2), validated and normalized to the current version. */
export function parseRelease(payload: unknown): PublicCatalog {
  const version = typeof payload === "object" && payload !== null && "schemaVersion" in payload ? payload.schemaVersion : undefined;
  return version === 1 ? normalizeRelease(releaseV1Schema.parse(payload)) : releaseSchema.parse(payload);
}

/** A stored payload validated as is (no normalization): what a snapshot writes back byte for byte. */
export function parseStoredRelease(payload: unknown): StoredRelease {
  const version = typeof payload === "object" && payload !== null && "schemaVersion" in payload ? payload.schemaVersion : undefined;
  return version === 1 ? releaseV1Schema.parse(payload) : releaseSchema.parse(payload);
}
