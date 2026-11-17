import { z } from "zod";
import {
  DEFAULTS, LIMITS, authorSlugSchema, courseSlugSchema, editionYearSchema, entityIdSchema, homeRowIdSchema,
  httpsUrlSchema, label, lessonParts, licenseCodeSchema, monogramSchema, rightsStatuses, sourceIdSchema,
} from "../../catalog/domain/schema/fields.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { COVER_FROM_PATTERN } from "../../catalog/domain/cover-source.ts";
import { batchAreaSchema, batchLicenseSchema, batchSubareaSchema } from "../../catalog/domain/schema/batch-v2.ts";
import { sha256Schema } from "../../media/domain/objects.ts";
import { youtubeIdSchema } from "../../catalog/domain/youtube-identity.ts";

// curated/v1 (docs/architecture/FACTORY.md). Limits come from the catalog schema (INV-R1); this file only adds the
// run shape. A translated title, a zero duration and an over-long field fail here, by field name.

const playlistIdSchema = z.string().regex(/^[A-Za-z0-9_-]{10,64}$/);
const channelIdSchema = z.string().regex(/^UC[A-Za-z0-9_-]{22}$/);
const reasonSchema = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).max(LIMITS.curationReason);
const sourceKinds = ["youtube-channel", "youtube-playlist", "portal"] as const;

const lessonSchema = z.strictObject({
  youtubeId: youtubeIdSchema,
  originalTitle: label(LIMITS.lessonTitle),
  durationSeconds: z.number().int().positive().max(LIMITS.lessonSeconds),
  uploadDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  position: z.number().int().positive(),
  part: z.enum(lessonParts).default(DEFAULTS.lessonPart),
});

const coverSchema = z.strictObject({
  poster: sha256Schema,
  og: sha256Schema.nullable().optional(),
  heroes: z.strictObject({
    desktop: sha256Schema.optional(),
    present: sha256Schema.optional(),
    mobile: sha256Schema.optional(),
    still: sha256Schema.optional(),
  }).optional(),
});

const lecturerSchema = z.strictObject({
  id: entityIdSchema,
  slug: authorSlugSchema,
  name: label(LIMITS.authorName),
  monogram: monogramSchema,
  kind: z.enum(["person", "channel"]),
});

const courseSchema = z.strictObject({
  sourcePlaylistId: playlistIdSchema,
  decision: z.enum(["include", "hold", "exclude"]),
  holdReason: reasonSchema.optional(),
  /** The person or channel who teaches the course. The institution is not a lecturer (D-024). */
  lecturer: lecturerSchema.optional(),
  id: entityIdSchema.optional(),
  slug: courseSlugSchema.optional(),
  title: label(LIMITS.courseTitle).optional(),
  originalTitle: label(LIMITS.courseTitle).optional(),
  language: label(LIMITS.languageLabel).optional(),
  areaId: entityIdSchema.optional(),
  subareaId: entityIdSchema.nullable().optional(),
  license: licenseCodeSchema.optional(),
  rights: z.enum(rightsStatuses).optional(),
  canonicalUrl: httpsUrlSchema.optional(),
  year: editionYearSchema.nullable().optional(),
  /** D-031. An included course names it; a missing declaration is held, not guessed. */
  coverFrom: z.string().regex(COVER_FROM_PATTERN).optional(),
  /** D-032. Course ids this course shares a video with. An included course names the list, even when it is empty. */
  sharedWith: z.array(entityIdSchema).max(LIMITS.sharedWithCount).optional(),
  cover: coverSchema.optional(),
  variantOf: entityIdSchema.nullable().optional(),
  sourceId: sourceIdSchema.optional(),
  /** Inclusive playlist positions to keep. Absent means the whole playlist. */
  positions: z.strictObject({
    from: z.number().int().positive(),
    to: z.number().int().positive(),
  }).optional(),
  lessons: z.array(lessonSchema).optional(),
});

const sourceSchema = z.strictObject({
  id: sourceIdSchema,
  kind: z.enum(sourceKinds),
  title: label(LIMITS.courseTitle),
  url: httpsUrlSchema,
  youtubeChannelId: channelIdSchema.optional(),
});

/** Input shape of one curated/v1 document, before the cross-field rules. Used to render the doc. */
export const curatedDocSchema = z.strictObject({
  format: z.literal("curated/v1"),
  run: z.strictObject({
    id: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).max(LIMITS.curationRunId),
    createdAt: z.string().min(EXTENT.one).max(LIMITS.isoTimestamp),
    adapter: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*@[1-9][0-9]*$/),
  }),
  institution: z.strictObject({
    id: entityIdSchema,
    slug: authorSlugSchema,
    name: label(LIMITS.authorName),
    fullName: label(LIMITS.authorName),
    place: label(LIMITS.areaTitle),
    kind: z.literal("institution", { error: "An institution has kind institution; a lecturer is a course author (D-024)." }),
    monogram: monogramSchema,
    cover: z.strictObject({
      poster: sha256Schema,
      og: sha256Schema.nullable().optional(),
      alt: label(LIMITS.coverAlt),
      credit: label(LIMITS.coverCredit),
      sourceUrl: httpsUrlSchema,
      license: label(LIMITS.licenseName),
      note: label(LIMITS.coverNote).optional(),
    }),
    homeRow: z.strictObject({
      after: homeRowIdSchema.optional(),
      visible: z.boolean(),
    }),
  }),
  sources: z.array(sourceSchema).min(EXTENT.one),
  /** Optional so a new area, its covers and a license can travel with the courses (D-031). */
  licenses: z.array(batchLicenseSchema).optional(),
  areas: z.array(batchAreaSchema).optional(),
  subareas: z.array(batchSubareaSchema).optional(),
  courses: z.array(courseSchema),
  provenance: z.strictObject({
    titles: z.enum(["original", "translated"]),
    fetchedAt: z.string().min(EXTENT.one).max(LIMITS.isoTimestamp),
    counts: z.strictObject({
      videos: z.number().int().nonnegative(),
      skippedScheduled: z.number().int().nonnegative(),
    }),
  }),
});

function curatedRules(doc: z.output<typeof curatedDocSchema>, context: z.RefinementCtx): void {
  if (doc.provenance.titles === "translated") {
    context.addIssue({ code: "custom", path: ["provenance", "titles"], message: "Translated titles are refused; originalTitle is the source title." });
  }
  doc.sources.forEach((source, index) => {
    if (source.kind !== "portal" && source.youtubeChannelId === undefined) {
      context.addIssue({ code: "custom", path: ["sources", index, "youtubeChannelId"], message: "A YouTube source names its channel id." });
    }
  });
  const seen = new Map<string, number>();
  doc.courses.forEach((course, index) => {
    if (course.decision === "hold" && course.holdReason === undefined) {
      context.addIssue({ code: "custom", path: ["courses", index, "holdReason"], message: "A held course names holdReason." });
    }
    if (course.decision !== "include") return;
    if (course.positions && course.positions.from > course.positions.to) {
      context.addIssue({ code: "custom", path: ["courses", index, "positions"], message: "positions.from is after positions.to." });
    }
    if (course.lessons === undefined || course.lessons.length === 0) {
      context.addIssue({ code: "custom", path: ["courses", index, "lessons"], message: "An included course has at least one lesson." });
    }
    if (course.id === undefined) return;
    const first = seen.get(course.id);
    if (first !== undefined) context.addIssue({ code: "custom", path: ["courses", index, "id"], message: `Duplicate id ${course.id}; also courses.${String(first)}.id.` });
    else seen.set(course.id, index);
  });
}

export const curatedDocumentSchema = curatedDocSchema.superRefine(curatedRules);

export type CuratedV1 = z.output<typeof curatedDocumentSchema>;
export type CuratedCourse = CuratedV1["courses"][number];
export type CuratedLesson = NonNullable<CuratedCourse["lessons"]>[number];

export interface CuratedIssue { readonly name: string; readonly message: string }

function issueName(path: readonly PropertyKey[]): string {
  return path.length === 0 ? "curated" : path.map((part) => String(part)).join(".");
}

/** Every problem, named by its field path (`provenance.titles`, `courses.0.lessons.0.durationSeconds`, `courses.0.id`). */
export function parseCurated(input: unknown): { readonly ok: true; readonly value: CuratedV1 } | { readonly ok: false; readonly issues: readonly CuratedIssue[] } {
  const parsed = curatedDocumentSchema.safeParse(input);
  if (parsed.success) return { ok: true, value: parsed.data };
  return {
    ok: false,
    issues: parsed.error.issues.map((issue) => {
      const name = issueName(issue.path);
      return { name, message: `${name}: ${issue.message}` };
    }),
  };
}
