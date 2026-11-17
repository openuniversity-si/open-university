import { authorCoverSchema } from "./author-cover.ts";
import { universityCoverSchema } from "./university-cover.ts";
import {
  EDITION_YEARS, LIMITS, authorKinds, authorSlugSchema, courseSlugSchema, editionSlugSchema, editionVariantSchema, editionYearSchema, entityIdSchema, homeRowIdSchema, httpsUrlSchema, label,
  lessonNouns, lessonParts, lessonSlugSchema, licenseCodeSchema, monogramSchema, revisionSchema, rightsStatuses, slugSchema, sourceIdSchema,
  textFieldSchema, youtubeIdSchema,
} from "./schema/fields.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { z } from "zod";
import { COVER_FROM_PATTERN } from "./cover-source.ts";
import { courseBodyStatuses, courseBulkStatuses, courseStatuses } from "./course-status.ts";
import { homeRowKinds } from "./home-row-kind.ts";
import { lessonKinds } from "./lesson-kind.ts";

// The admin catalog API contract (ADR-18, plan §3): request schemas, error codes and the response envelope.
// Pure Zod, no server code: the tower-catalog CLI (P5) and the tests import it as is.

export const ADMIN_CATALOG_BASE = "/api/admin/catalog";
/** Request bodies above 1 MB are refused with 413 before parsing. */
export const MAX_BODY_BYTES = 1024 * 1024;
export const DEFAULT_ACTOR = "cli:tower-catalog";
export const IDEMPOTENCY_HEADER = "idempotency-key";
export const ACTOR_HEADER = "x-tower-actor";
export const REPLAY_HEADER = "idempotent-replay";

/** Every error code the API answers with, and its HTTP status. */
export { errorCodes, type ErrorCode, type PreconditionFailure } from "../../kernel/errors.ts";
import type { ErrorCode } from "../../kernel/errors.ts";

export interface AdminSuccess<T = unknown> { readonly ok: true; readonly data: T; readonly requestId: string }
export interface AdminFailure {
  readonly ok: false;
  readonly error: { readonly code: ErrorCode; readonly message: string; readonly details?: unknown };
  readonly requestId: string;
}
export type AdminEnvelope<T = unknown> = AdminSuccess<T> | AdminFailure;

/** One unmet precondition (412 `details.failed`, `GET /courses/:id` `preconditions`). */



export const idempotencyKeySchema = z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/);
export const actorSchema = z.string().regex(/^[a-z0-9:@._ -]{1,64}$/);

// ---- Building blocks: one source, ./schema/fields.ts (INV-R1) ----
export {
  courseSlugSchema, editionSlugSchema, entityIdSchema, httpsUrlSchema, lessonParts, lessonSlugSchema, licenseCodeSchema, revisionSchema,
  rightsStatuses, slugSchema, sourceIdSchema, youtubeIdSchema,
};
export const catalogPathSchema = z.string().max(LIMITS.catalogPath).regex(/^\/c\/[a-z0-9]+(?:-[a-z0-9]+)*(?:\/[a-z0-9]+(?:-[a-z0-9]+)*)?$/);
const note = label(LIMITS.note);
const queryBoolean = z.enum(["true", "false"]).transform((value) => value === "true");
const queryInt = z.string().regex(/^\d{1,9}$/).transform(Number);

export { courseStatuses, lessonKinds };
export const textKinds = ["course", "lesson", "author"] as const;
export const textSources = ["figma", "dossier/catalog", "youtube", "llm", "manual"] as const;
export const textConfidences = ["figma-approved", "high", "medium", "low"] as const;
export const sourceKinds = ["youtube-playlist", "youtube-channel", "institution-site"] as const;
export const editionTerms = ["spring", "summer", "fall", "winter"] as const;
export type EditionTerm = (typeof editionTerms)[number];
export type LessonPart = (typeof lessonParts)[number];

export const idParams = z.strictObject({ id: entityIdSchema });
export const sourceParams = z.strictObject({ id: sourceIdSchema });
export const releaseParams = z.strictObject({ n: queryInt.pipe(z.number().int().positive()) });
export const importParams = z.strictObject({ id: z.string().regex(/^import-[A-Za-z0-9_-]+-\d{12}(?:-\d+)?$/).max(LIMITS.importId) });
export const noQuery = z.strictObject({});

// ---- Courses ----
/** One page of `GET /courses`. A full catalog (about 1,700 courses) stays more than one page. */
export const COURSE_LIST_LIMIT = 1000;
/** One page of `GET /redirects`. The CLI follows `nextCursor` until the list ends. */
export const REDIRECT_LIST_LIMIT = 100;
export const coursesQuery = z.strictObject({
  status: z.enum(courseStatuses).optional(),
  /** Page size. Omitted means `COURSE_LIST_LIMIT`. */
  limit: queryInt.pipe(z.number().int().min(EXTENT.one).max(COURSE_LIST_LIMIT)).optional(),
  /** Last course id of the previous page. Pages follow `id` order. */
  cursor: entityIdSchema.optional(),
});
export const subareasQuery = z.strictObject({
  /** `1` attaches each subarea's active catalog covers. Omitted leaves the list shape unchanged. */
  covers: z.literal("1").optional(),
});
export const redirectsQuery = z.strictObject({
  limit: queryInt.pipe(z.number().int().min(EXTENT.one).max(REDIRECT_LIST_LIMIT)).optional(),
  /** Last `from` path of the previous page. Pages follow `from_path` order. */
  cursor: catalogPathSchema.optional(),
});
export const courseCreate = z.strictObject({
  slug: courseSlugSchema, authorId: entityIdSchema, title: label(LIMITS.courseTitle),
  lessonNoun: z.enum(lessonNouns).optional(), languageLabel: label(LIMITS.languageLabel).optional(),
  sourceId: sourceIdSchema.optional(), licenseCode: licenseCodeSchema.optional(), canonicalUrl: httpsUrlSchema.optional(),
  attributionText: label(LIMITS.attributionText).optional(),
  /** D-031. Required. A draft does not silently become `own`. */
  coverFrom: z.string().regex(COVER_FROM_PATTERN),
});
export const coursePatch = z.strictObject({
  expectedRevision: revisionSchema,
  slug: courseSlugSchema.optional(), authorId: entityIdSchema.optional(), title: label(LIMITS.courseTitle).optional(),
  lessonNoun: z.enum(lessonNouns).optional(), languageLabel: label(LIMITS.languageLabel).optional(),
  sourceId: sourceIdSchema.nullable().optional(), licenseCode: licenseCodeSchema.nullable().optional(),
  canonicalUrl: httpsUrlSchema.nullable().optional(), attributionText: label(LIMITS.attributionText).nullable().optional(),
  rightsStatus: z.enum(rightsStatuses).optional(), rightsNotes: label(LIMITS.rightsNotes).nullable().optional(), rightsCheckedBy: label(LIMITS.actorId).optional(),
  areaId: entityIdSchema.nullable().optional(),
  /** ADR-26: a subarea of the course's (resulting) area, or null; changing the area of a course with a subarea needs this too. */
  subareaId: entityIdSchema.nullable().optional(),
  coverFrom: z.string().regex(COVER_FROM_PATTERN).optional(),
}).refine((body) => Object.keys(body).length > 1, { message: "Name at least one field to change." });
export const courseStatusBody = z.strictObject({ to: z.enum(courseBodyStatuses), expectedRevision: revisionSchema });
export const publishBody = z.strictObject({ expectedRevision: revisionSchema, note, allowOrphan: z.boolean().optional() });
/** POST /courses/publish-batch: many courses (review or published) in ONE release, all or nothing (docs/catalog/admin-api.md). */
export const BATCH_PUBLISH_MAX = 2000;
export const publishBatchBody = z.strictObject({
  courses: z.array(z.strictObject({ id: entityIdSchema, expectedRevision: revisionSchema })).min(EXTENT.one).max(BATCH_PUBLISH_MAX)
    .refine((courses) => new Set(courses.map((course) => course.id)).size === courses.length, { message: "Each course appears once." }),
  note, allowOrphan: z.boolean().optional(),
});
/** POST /courses/classify: set area and/or subarea of many courses in ONE transaction, all or nothing; idempotent (ADR-26). */
export const CLASSIFY_MAX = 2000;
export const classifyBody = z.strictObject({
  items: z.array(z.strictObject({ id: entityIdSchema, areaId: entityIdSchema.optional(), subareaId: entityIdSchema.nullable().optional() })
    .refine((item) => item.areaId !== undefined || item.subareaId !== undefined, { message: "Name areaId and/or subareaId." }))
    .min(EXTENT.one).max(CLASSIFY_MAX)
    .refine((items) => new Set(items.map((item) => item.id)).size === items.length, { message: "Each course appears once." }),
});
export const unpublishBody = z.strictObject({
  expectedRevision: revisionSchema, note, replacementFeaturedId: entityIdSchema.optional(), to: z.enum(courseBulkStatuses).optional(),
});
/** Explicit whitelist already checked on the peer environment; the server never expands it during deletion/retry. */
const checkedKeysQuery = z.string().max(MAX_BODY_BYTES).transform((value, context) => {
  try { return JSON.parse(value) as unknown; } catch { context.addIssue({ code: "custom", message: "Expected a JSON array of checked R2 keys." }); return z.NEVER; }
}).pipe(z.array(z.string().min(EXTENT.one).max(LIMITS.objectKey)).min(EXTENT.one).max(LIMITS.objectKeyBatch));

export const courseDeleteQuery = z.strictObject({
  mode: z.enum(["archive", "purge"]), confirm: queryBoolean.optional(), expectedRevision: queryInt.optional(),
  replacementFeaturedId: entityIdSchema.optional(), deleteBytes: queryBoolean.optional(), checkedKeys: checkedKeysQuery.optional(), note: label(LIMITS.note).optional(),
});

// ---- Editions (ADR-21) ----
const yearSchema = editionYearSchema;
const playlistIdSchema = z.string().regex(/^[A-Za-z0-9_-]{10,64}$/);
/** What names an edition: `label` is shown as is ("Fall 2024": term and year only). */
export const editionInput = z.strictObject({
  slug: editionSlugSchema, label: label(LIMITS.editionLabel), term: z.enum(editionTerms).nullable().optional(), year: yearSchema,
  variant: editionVariantSchema.optional(),
  /** D-035. The same string a language variant uses as its label. */
  language: label(LIMITS.languageLabel).optional(),
});
export const editionCreate = editionInput.extend({ resolution: label(LIMITS.resolutionLabel).nullable().optional(), sourcePlaylistIds: z.array(playlistIdSchema).max(LIMITS.sourcePlaylistCount).optional() });
export const editionPatch = z.strictObject({
  expectedRevision: revisionSchema, slug: editionSlugSchema.optional(), label: label(LIMITS.editionLabel).optional(), term: z.enum(editionTerms).nullable().optional(),
  year: yearSchema.optional(), variant: editionVariantSchema.nullable().optional(), language: label(LIMITS.languageLabel).nullable().optional(),
  resolution: label(LIMITS.resolutionLabel).nullable().optional(), sourcePlaylistIds: z.array(playlistIdSchema).max(LIMITS.sourcePlaylistCount).optional(),
}).refine((body) => Object.keys(body).length > 1, { message: "Name at least one field to change." });
/** A manual order (the exception to newest first): exactly the course's editions; `expectedRevision` is the course's. */
export const editionOrder = z.strictObject({ editionIds: z.array(entityIdSchema).min(EXTENT.one).max(LIMITS.editionReorderCount), expectedRevision: revisionSchema });
export const editionDeleteQuery = z.strictObject({
  confirm: queryBoolean.optional(), expectedRevision: queryInt.optional(), mode: z.enum(["empty", "with-lessons"]).optional(), deleteBytes: queryBoolean.optional(), checkedKeys: checkedKeysQuery.optional(),
});

const TERM_WORDS: Readonly<Partial<Record<string, EditionTerm>>> = { spring: "spring", sp: "spring", summer: "summer", su: "summer", fall: "fall", fa: "fall", autumn: "fall", winter: "winter", wi: "winter" };
/**
 * "Fall 2025", "SP25", "2026", "Spring 2024 Lectures" → `{ slug: "fall-2025", label: "Fall 2025", term: "fall", year: 2025 }`. The label
 * keeps only term and year (ADR-21); words such as "Lectures" or "Labs" name a part, not an edition. Null when no year is found.
 */
/** The label an edition shows: "Fall 2024", or "2026" without a term (ADR-21). */
export function editionLabel(term: EditionTerm | null, year: number): string {
  return term === null ? String(year) : `${term.charAt(0).toUpperCase()}${term.slice(1)} ${String(year)}`;
}

export function parseEditionLabel(text: string): z.infer<typeof editionInput> | null {
  const lower = text.toLowerCase();
  const short = /\b(sp|su|fa|wi)(\d{2})\b/.exec(lower);
  const full = /\b((?:19|20)\d{2})\b/.exec(lower);
  const named = /\b(spring|summer|fall|autumn|winter)\b/.exec(lower);
  const year = full ? Number(full[1]) : short ? 2000 + Number(short[2]) : null;
  const term = (named ? TERM_WORDS[named[1] ?? ""] : short ? TERM_WORDS[short[1] ?? ""] : undefined) ?? null;
  if (year === null || year < EDITION_YEARS.min || year > EDITION_YEARS.max) return null;
  return { slug: term === null ? String(year) : `${term}-${String(year)}`, label: editionLabel(term, year), term, year };
}

// ---- Lessons ----
export const lessonCreate = z.strictObject({
  editionId: entityIdSchema, part: z.enum(lessonParts).optional(),
  youtubeId: youtubeIdSchema, durationSeconds: z.number().int().positive().max(LIMITS.lessonSeconds),
  slug: lessonSlugSchema.optional(), displayTitle: z.string().max(LIMITS.lessonTitle).optional(), position: z.number().int().positive().optional(),
  kind: z.enum(lessonKinds).optional(),
});
export const lessonOrder = z.strictObject({ lessonIds: z.array(entityIdSchema).min(EXTENT.one).max(LIMITS.lessonWriteCount), expectedRevision: revisionSchema });
/** `?dryRun=true`: the report (changes, redirects) without writing. */
export const lessonPatchQuery = z.strictObject({ dryRun: queryBoolean.optional() });
/** PUT /lessons/slugs: one course's slug changes, all or nothing; `dryRun` answers the plan without writing. */
export const lessonSlugsPut = z.strictObject({
  courseId: entityIdSchema, expectedRevision: revisionSchema,
  changes: z.array(z.strictObject({ lessonId: entityIdSchema, slug: lessonSlugSchema })).min(EXTENT.one).max(LIMITS.lessonWriteCount),
  dryRun: z.boolean().optional(),
});
export const lessonPatch = z.strictObject({
  expectedRevision: revisionSchema, slug: lessonSlugSchema.optional(), kind: z.enum(lessonKinds).optional(), visible: z.boolean().optional(),
  editionId: entityIdSchema.optional(), part: z.enum(lessonParts).optional(),
  licenseCode: licenseCodeSchema.nullable().optional(), attributionText: label(LIMITS.attributionText).nullable().optional(),
}).refine((body) => Object.keys(body).length > 1, { message: "Name at least one field to change." });
export const lessonDeleteQuery = z.strictObject({ confirm: queryBoolean.optional(), expectedRevision: queryInt.optional(), deleteBytes: queryBoolean.optional(), checkedKeys: checkedKeysQuery.optional() });

/** POST /media/references: which of these R2 keys a media row of this database uses (the other environment's check before a byte delete). */
export const mediaReferencesBody = z.strictObject({ keys: z.array(z.string().min(EXTENT.one).max(LIMITS.objectKey)).min(EXTENT.one).max(LIMITS.objectKeyBatch) });
export type MediaReferencesBody = z.infer<typeof mediaReferencesBody>;

// ---- Authors ----
export const authorCreate = z.strictObject({
  slug: authorSlugSchema, name: label(LIMITS.authorName), monogram: monogramSchema, role: label(LIMITS.authorRole).optional(), kind: z.enum(authorKinds),
});
export const authorPatch = z.strictObject({
  expectedRevision: revisionSchema, slug: authorSlugSchema.optional(), name: label(LIMITS.authorName).optional(),
  monogram: monogramSchema.optional(), role: label(LIMITS.authorRole).optional(), kind: z.enum(authorKinds).optional(),
  cover: authorCoverSchema.nullable().optional(),
}).refine((body) => Object.keys(body).length > 1, { message: "Name at least one field to change." });
export const authorDeleteQuery = z.strictObject({ confirm: queryBoolean.optional(), expectedRevision: queryInt.optional() });

// ---- Texts ----
const entityRef = z.string().regex(/^(course|lesson|author):[a-z0-9]+(?:-[a-z0-9]+)*$/).max(LIMITS.entityRef);
export const textsQuery = z.strictObject({ entity: entityRef });
const textKey = { entityKind: z.enum(textKinds), entityId: entityIdSchema, field: textFieldSchema };
export const textsPut = z.array(z.strictObject({
  ...textKey, text: z.string().max(LIMITS.text), source: z.enum(textSources), sourceRef: label(LIMITS.textSourceRef), confidence: z.enum(textConfidences),
})).min(EXTENT.one).max(LIMITS.textBatchCount);
export const textsApprove = z.strictObject({
  items: z.array(z.strictObject({ ...textKey, sha256: z.string().regex(/^[a-f0-9]{64}$/) })).min(EXTENT.one).max(LIMITS.textBatchCount),
  approvedBy: label(LIMITS.actorId),
});
export const textsRevoke = z.strictObject({ items: z.array(z.strictObject(textKey)).min(EXTENT.one).max(LIMITS.textBatchCount) });

// ---- Home ----
/** Courses one Home row may list in `PUT /home` (a university row can hold a whole institute). */
export const HOME_ROW_MAX_COURSES = 250;
export const homePut = z.strictObject({
  featuredCourseId: entityIdSchema.nullable(),
  rows: z.array(z.strictObject({
    id: homeRowIdSchema, kind: z.enum(homeRowKinds), title: label(LIMITS.homeRowTitle).optional(),
    authorId: entityIdSchema.optional(), institutionId: entityIdSchema.optional(), visible: z.boolean().optional(), courseIds: z.array(entityIdSchema).max(HOME_ROW_MAX_COURSES),
    /** Curated rows only. Omitted: the row keeps its current cover. null is refused for a visible row (ADR-40). */
    cover: universityCoverSchema.nullable().optional(),
    /** Curated rows only (0013). Omitted: kept; null: removed. */
    fullName: label(LIMITS.authorName).nullable().optional(), place: label(LIMITS.placeName).nullable().optional(),
  })).max(LIMITS.homeRowCount),
  expectedRevision: revisionSchema,
  note: note.optional(),
  /** S08: run the whole change (rows, covers, rules, commit-time constraints, release compile) and roll it back. */
  dryRun: z.boolean().optional(),
});

// ---- Reference data ----
/** A new global subject area (ADR-25, docs/catalog/areas.md); without a position it goes last. */
export const areaCreate = z.strictObject({
  id: entityIdSchema, title: label(LIMITS.areaTitle), position: z.number().int().positive().max(LIMITS.areaPosition).optional(),
});
/** Moves one area to `position` (1..n); the others shift so positions stay 1..n. One release, like any catalog write. */
export const areaMove = z.strictObject({ position: z.number().int().positive().max(LIMITS.areaPosition), note: note.optional() });
/** Renames one area (its id, the URL segment, never changes). One release, like any catalog write. */
export const areaPatch = z.strictObject({ title: label(LIMITS.areaTitle), note: note.optional() });
/** A new subarea of an area (ADR-26, docs/catalog/subareas.md); appended last inside its area unless a free position is named. */
export const subareaCreate = z.strictObject({
  id: entityIdSchema, areaId: entityIdSchema, title: label(LIMITS.areaTitle), position: z.number().int().positive().max(LIMITS.areaPosition).optional(),
});
export const licenseCreate = z.strictObject({
  code: licenseCodeSchema, name: label(LIMITS.licenseName), url: httpsUrlSchema.nullable().optional(), requiresAttribution: z.boolean(),
  nonCommercial: z.boolean().optional(), shareAlike: z.boolean().optional(), embedOnly: z.boolean().optional(),
  attributionTemplate: label(LIMITS.attributionTemplate).nullable().optional(),
});
export const sourceCreate = z.strictObject({
  id: sourceIdSchema, kind: z.enum(sourceKinds), title: label(LIMITS.sourceTitle), publisher: label(LIMITS.sourcePublisher), url: httpsUrlSchema,
  youtubeChannelId: z.string().regex(/^UC[A-Za-z0-9_-]{22}$/).nullable().optional(),
  youtubePlaylistId: z.string().regex(/^[A-Za-z0-9_-]{10,64}$/).nullable().optional(),
});
export const sourcePatch = z.strictObject({
  expectedRevision: revisionSchema, kind: z.enum(sourceKinds).optional(), title: label(LIMITS.sourceTitle).optional(), publisher: label(LIMITS.sourcePublisher).optional(),
  url: httpsUrlSchema.optional(), youtubeChannelId: z.string().regex(/^UC[A-Za-z0-9_-]{22}$/).nullable().optional(),
  youtubePlaylistId: z.string().regex(/^[A-Za-z0-9_-]{10,64}$/).nullable().optional(),
}).refine((body) => Object.keys(body).length > 1, { message: "Name at least one field to change." });

// ---- Imports (storage only: the extractor runs in the CLI, P6) ----
export const importItem = z.strictObject({
  id: youtubeIdSchema, title: label(LIMITS.externalTitle), duration: z.number().nonnegative().nullable().optional(),
  availability: z.string().max(LIMITS.importToken).nullable().optional(), liveStatus: z.string().max(LIMITS.importToken).nullable().optional(),
  ageLimit: z.number().int().nonnegative().nullable().optional(), playableInEmbed: z.boolean().nullable().optional(),
  channelId: z.string().max(LIMITS.youtubeChannelId).nullable().optional(), channel: z.string().max(LIMITS.channelName).nullable().optional(),
  license: z.string().max(LIMITS.importToken).nullable().optional(), height: z.number().int().nonnegative().nullable().optional(),
  playlistIndex: z.number().int().positive().nullable().optional(),
});
export const importCreate = z.strictObject({
  playlistUrl: httpsUrlSchema, tool: label(LIMITS.importTool).optional(), playlistTitle: label(LIMITS.externalTitle).optional(),
  channelId: z.string().max(LIMITS.youtubeChannelId).optional(), channel: label(LIMITS.channelName).optional(),
  items: z.array(importItem).min(EXTENT.one).max(LIMITS.importItemCount),
});
/**
 * A draft from an import: a new course (`slug` and one of `authorId`/`newAuthor`), or a new or existing edition of an existing
 * course (`courseId` and `edition`; no course fields). `part` puts every lesson in that part; without it, the import's suggestion.
 */
export const importDraft = z.strictObject({
  slug: courseSlugSchema.optional(), authorId: entityIdSchema.optional(), newAuthor: authorCreate.optional(),
  courseId: entityIdSchema.optional(), edition: editionInput.optional(), part: z.enum(lessonParts).optional(),
  include: z.array(youtubeIdSchema).max(LIMITS.importSelectionCount).optional(), exclude: z.array(youtubeIdSchema).max(LIMITS.importSelectionCount).optional(),
  title: label(LIMITS.courseTitle).optional(), lessonNoun: z.enum(lessonNouns).optional(),
  sourceId: sourceIdSchema.optional(), licenseCode: licenseCodeSchema.optional(), canonicalUrl: httpsUrlSchema.optional(),
}).superRefine((body, ctx) => {
  const fail = (message: string) => { ctx.addIssue({ code: "custom", message }); };
  if (body.courseId === undefined) {
    if (body.slug === undefined) fail("Pass slug for a new course, or courseId and edition for an existing one.");
    if ((body.authorId === undefined) === (body.newAuthor === undefined)) fail("Pass exactly one of authorId and newAuthor.");
    return;
  }
  if (body.edition === undefined) fail("An import into an existing course needs the edition.");
  const courseFields = (["slug", "authorId", "newAuthor", "title", "lessonNoun", "sourceId", "licenseCode", "canonicalUrl"] as const).filter((field) => body[field] !== undefined);
  if (courseFields.length > 0) fail(`An import into an existing course takes no course fields (${courseFields.join(", ")}).`);
});

// ---- Releases, redirects, preview, audit ----
export const releasesCreateQuery = z.strictObject({ dryRun: queryBoolean.optional() });
export const releaseCreate = z.strictObject({ note }).optional();
export const releaseActivate = z.strictObject({ note });
export const redirectCreate = z.strictObject({ from: catalogPathSchema, to: catalogPathSchema });
export const redirectDeleteQuery = z.strictObject({ from: catalogPathSchema, confirm: queryBoolean.optional() });
export const previewTokenBody = z.strictObject({ courseId: entityIdSchema.optional(), ttlMinutes: z.number().int().min(EXTENT.one).max(LIMITS.previewTtlMinutes).optional() });
/** `kind:id`; ids include release numbers, license codes and redirect paths (`redirect:/c/old-slug`). */
export const auditQuery = z.strictObject({ entity: z.string().regex(/^[a-z]+:[A-Za-z0-9_./-]{1,300}$/), limit: queryInt.pipe(z.number().int().min(EXTENT.one).max(LIMITS.auditPageSize)).optional() });

export type CourseCreate = z.infer<typeof courseCreate>;
export type CoursePatch = z.infer<typeof coursePatch>;
export type CourseStatusBody = z.infer<typeof courseStatusBody>;
export type PublishBody = z.infer<typeof publishBody>;
export type PublishBatchBody = z.infer<typeof publishBatchBody>;
export type UnpublishBody = z.infer<typeof unpublishBody>;
export type CourseDeleteQuery = z.infer<typeof courseDeleteQuery>;
export type EditionInput = z.infer<typeof editionInput>;
export type EditionCreate = z.infer<typeof editionCreate>;
export type EditionPatch = z.infer<typeof editionPatch>;
export type EditionOrder = z.infer<typeof editionOrder>;
export type EditionDeleteQuery = z.infer<typeof editionDeleteQuery>;
export type LessonCreate = z.infer<typeof lessonCreate>;
export type LessonOrder = z.infer<typeof lessonOrder>;
export type LessonPatch = z.infer<typeof lessonPatch>;
export type LessonPatchQuery = z.infer<typeof lessonPatchQuery>;
export type LessonSlugsPut = z.infer<typeof lessonSlugsPut>;
export type AuthorCreate = z.infer<typeof authorCreate>;
export type AuthorPatch = z.infer<typeof authorPatch>;
export type TextsPut = z.infer<typeof textsPut>;
export type TextsApprove = z.infer<typeof textsApprove>;
export type TextsRevoke = z.infer<typeof textsRevoke>;
export type HomePut = z.infer<typeof homePut>;
export type LicenseCreate = z.infer<typeof licenseCreate>;
export type AreaCreate = z.infer<typeof areaCreate>;
export type AreaMove = z.infer<typeof areaMove>;
export type AreaPatch = z.infer<typeof areaPatch>;
export type SubareaCreate = z.infer<typeof subareaCreate>;
export type ClassifyBody = z.infer<typeof classifyBody>;
export type SourceCreate = z.infer<typeof sourceCreate>;
export type SourcePatch = z.infer<typeof sourcePatch>;
export type ImportItem = z.infer<typeof importItem>;
export type ImportCreate = z.infer<typeof importCreate>;
export type ImportDraft = z.infer<typeof importDraft>;
export type RedirectCreate = z.infer<typeof redirectCreate>;
export type PreviewTokenBody = z.infer<typeof previewTokenBody>;
