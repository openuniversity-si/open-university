import { z } from "zod";
import { editionLanguageProblems, indistinctEditionMessage, indistinctEditions } from "../edition-variant.ts";
import { COVER_FROM_PATTERN, coverDeclarationProblem } from "../cover-source.ts";
import { youtubeWithinCourseKey } from "../youtube-identity.ts";
import { EXTENT } from "../../../kernel/extent.ts";
import {
  DEFAULTS, LIMITS, authorKinds, authorSlugSchema, bundleCoverKinds, courseSlugSchema, editionSlugSchema, editionVariantSchema, editionYearSchema, entityIdSchema,
  homeRowIdSchema, httpsUrlSchema, label, lessonNouns, lessonParts, lessonSlugSchema, licenseCodeSchema, monogramSchema,
  revisionSchema, rightsStatuses, sourceIdSchema, textFieldSchema, youtubeIdSchema,
} from "./fields.ts";

// CourseBundleV1 (docs/catalog/schema.md): built only from ./fields.ts, so a bundle and an admin route accept the same ids.

/** Absent or null collections are empty: absence is merge, not deletion. */
const many = <T extends z.ZodType>(item: T) => z.array(item).nullish().transform((value) => value ?? []);
/** Absent, null and blank are all "not stated". */
const optionalText = z.string().nullish().transform((value) => {
  const trimmed = value?.trim() ?? "";
  return trimmed === "" ? null : trimmed;
});

export const bundleAuthorSchema = z.object({
  id: entityIdSchema, slug: authorSlugSchema, name: label(LIMITS.authorName), monogram: monogramSchema, kind: z.enum(authorKinds),
});

export const bundleCourseSchema = z.object({
  id: entityIdSchema, slug: courseSlugSchema, title: label(LIMITS.courseTitle), authorId: entityIdSchema,
  lessonNoun: z.enum(lessonNouns).default(DEFAULTS.lessonNoun),
  languageLabel: label(LIMITS.languageLabel).optional(),
  areaId: entityIdSchema.optional(),
  subareaId: entityIdSchema.nullable().optional(),
  licenseCode: licenseCodeSchema.optional(),
  sourceId: sourceIdSchema.optional(),
  attributionText: label(LIMITS.attributionText).nullable().optional(),
  canonicalUrl: httpsUrlSchema.optional(),
  rightsStatus: z.enum(rightsStatuses).optional(),
  /** D-031: own, subarea:<id> or area:<id>. Required. Nothing is assumed. */
  coverFrom: z.string().regex(COVER_FROM_PATTERN),
  /** D-032. Course ids this course shares a video with. An empty list declares no share. Omission is refused. */
  sharedWith: z.array(entityIdSchema).max(LIMITS.sharedWithCount),
});

export const bundleEditionSchema = z.object({
  id: entityIdSchema, slug: editionSlugSchema, label: label(LIMITS.editionLabel), position: z.number().int().positive(),
  /** A known year. Null is refused: a missing year holds the course instead of being invented (D-031). */
  year: editionYearSchema.nullable(),
  /** D-034. Absent means this is the only offering of its year. Kind and label come from editionVariantSchema. */
  variant: editionVariantSchema.optional(),
  /** D-035. The edition's language. The course language is the default edition's. A language variant uses this same string. */
  language: label(LIMITS.languageLabel).optional(),
});

export const bundleLessonSchema = z.object({
  id: entityIdSchema, editionId: entityIdSchema, slug: lessonSlugSchema, title: label(LIMITS.lessonTitle),
  position: z.number().int().positive(), youtubeId: youtubeIdSchema,
  durationSeconds: z.number().positive().max(LIMITS.lessonSeconds),
  part: z.enum(lessonParts).default(DEFAULTS.lessonPart),
});

export const bundleTextSchema = z.object({
  entityKind: z.enum(["course", "lesson"]), entityId: entityIdSchema, field: textFieldSchema, text: label(LIMITS.text),
  approved: z.boolean().default(false), approvedBy: optionalText, approvedAt: optionalText,
});

export const bundleHomeSchema = z.object({ rowId: homeRowIdSchema, expectedRevision: revisionSchema });

const COVER_PATH = /^[A-Za-z0-9._/-]+$/;
export const bundleCoverSchema = z.object({
  kind: z.enum(bundleCoverKinds),
  path: z.string().trim().min(EXTENT.one).regex(COVER_PATH).refine((path) => !path.startsWith("/") && !path.split("/").includes(".."), {
    message: "A cover path is relative and stays inside the bundle directory.",
  }),
});

const bundleFields = z.object({
  version: z.literal(1, { error: "Only CourseBundleV1 is accepted." }),
  author: bundleAuthorSchema,
  course: bundleCourseSchema,
  editions: many(bundleEditionSchema),
  lessons: many(bundleLessonSchema),
  texts: many(bundleTextSchema),
  home: bundleHomeSchema.nullish().transform((value) => value ?? null),
  covers: many(bundleCoverSchema),
});

/** Cross-field rules of one bundle; their messages are the ones the API and the CLI print. */
export function bundleProblems(bundle: z.output<typeof bundleFields>): string[] {
  const problems: string[] = [];
  const { author, course } = bundle;
  if (course.authorId !== author.id) problems.push("The course author is not the bundle author.");
  if (typeof course.subareaId === "string" && course.areaId === undefined) problems.push("A subarea needs its area.");
  const declared = coverDeclarationProblem({ id: course.id, areaId: course.areaId ?? null, subareaId: course.subareaId ?? null }, course.coverFrom);
  if (declared) problems.push(declared);
  if (course.sharedWith.includes(course.id)) problems.push("A course does not declare a share with itself.");
  if (new Set(course.sharedWith).size !== course.sharedWith.length) problems.push("A share is declared once.");
  const kinds = new Set<string>();
  for (const cover of bundle.covers) {
    if (kinds.has(cover.kind)) problems.push(`Duplicate cover ${cover.kind}.`);
    kinds.add(cover.kind);
  }
  if (bundle.editions.length === 0) problems.push("A bundle has at least one edition.");
  const editionIds = new Set<string>();
  for (const edition of bundle.editions) {
    if (editionIds.has(edition.id)) problems.push(`Duplicate edition ${edition.id}.`);
    if (edition.year === null) problems.push(`Edition ${edition.id} has no known year; name the year before writing it.`);
    editionIds.add(edition.id);
  }
  for (const clash of indistinctEditions(bundle.editions)) problems.push(indistinctEditionMessage(clash.year, clash.ids));
  problems.push(...editionLanguageProblems(course.languageLabel, bundle.editions));
  const lessonIds = new Set<string>();
  const videos = new Set<string>();
  for (const lesson of bundle.lessons) {
    if (!editionIds.has(lesson.editionId)) problems.push(`Lesson ${lesson.id} references missing edition ${lesson.editionId}.`);
    if (lessonIds.has(lesson.id)) problems.push(`Duplicate lesson ${lesson.id}.`);
    const video = youtubeWithinCourseKey(course.id, lesson.youtubeId);
    if (videos.has(video)) problems.push(`Duplicate video ${lesson.youtubeId}.`);
    lessonIds.add(lesson.id);
    videos.add(video);
  }
  for (const text of bundle.texts) {
    if (text.entityKind === "course" && text.entityId !== course.id) problems.push(`Text ${text.field} is not for this course.`);
    if (text.entityKind === "lesson" && !lessonIds.has(text.entityId)) problems.push(`Text ${text.field} references missing lesson ${text.entityId}.`);
    if (text.approved !== (text.approvedBy !== null && text.approvedAt !== null)) problems.push(`Text ${text.entityId}.${text.field} approval is incomplete.`);
  }
  return problems;
}

/** The one CourseBundleV1 schema: shape, cross-field rules and the canonical order (editions, lessons, texts, covers). */
export const courseBundleSchema = bundleFields.superRefine((bundle, context) => {
  for (const message of bundleProblems(bundle)) context.addIssue({ code: "custom", message });
}).transform((bundle) => ({
  ...bundle,
  editions: [...bundle.editions].sort((a, b) => a.position - b.position),
  lessons: [...bundle.lessons].sort((a, b) => a.position - b.position || (a.id < b.id ? -1 : 1)),
  texts: [...bundle.texts].sort((a, b) => `${a.entityKind}:${a.entityId}:${a.field}`.localeCompare(`${b.entityKind}:${b.entityId}:${b.field}`)),
  covers: [...bundle.covers].sort((a, b) => (a.kind < b.kind ? -1 : 1)),
}));

/** The input side, for the generated doc (docs/catalog/schema.md). */
export const courseBundleDocSchema = bundleFields;
