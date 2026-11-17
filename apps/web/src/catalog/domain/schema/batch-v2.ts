import { z } from "zod";
import { coverFieldByKind, coverKindsByOwner } from "../../../kernel/cover-kinds.ts";
import { EXTENT } from "../../../kernel/extent.ts";
import { coverKindAllowed } from "../../../media/domain/cover-choice.ts";
import { bundleCourseSchema, bundleEditionSchema, bundleLessonSchema, bundleTextSchema } from "./bundle.ts";
import {
  LIMITS, authorSlugSchema, bundleCoverKinds, entityIdSchema, homeRowIdSchema, httpsUrlSchema, label, lecturerKinds, licenseCodeSchema, mediaShaSchema,
  monogramSchema, sourceIdSchema,
} from "./fields.ts";

// CatalogBatchV2 (docs/domain/CONTRACT.md §5, S07): the declarative desired state of a set of courses and everything they
// reference. Built only from ./fields.ts and the CourseBundleV1 parts (INV-R1). Covers travel as content addresses: the
// bytes are uploaded before, by sha. Semantics are additive upsert by id; nothing is deleted by omission.

const many = <T extends z.ZodType>(item: T) => z.array(item).nullish().transform((value) => value ?? []);

export const batchSourceSchema = z.strictObject({
  id: sourceIdSchema, kind: z.enum(["youtube-channel", "youtube-playlist", "institution-site"]), title: label(LIMITS.courseTitle),
  url: httpsUrlSchema, publisher: label(LIMITS.authorName).optional(), youtubeChannelId: z.string().min(EXTENT.one).max(LIMITS.youtubeChannelId).optional(),
});

/** An institution offers courses and owns at most one University row (D-016, D-024). Its poster is its own (INV-M4). */
export const batchInstitutionSchema = z.strictObject({
  id: entityIdSchema, slug: authorSlugSchema, name: label(LIMITS.authorName), monogram: monogramSchema,
  kind: z.literal("institution", { error: "An institution has kind institution; a lecturer is a course author (D-024)." }),
  cover: z.strictObject({ poster: mediaShaSchema, og: mediaShaSchema.nullish() }),
});

/** A lecturer (person or channel) teaches courses; it may teach at several institutions (D-024). */
export const batchLecturerSchema = z.strictObject({
  id: entityIdSchema, slug: authorSlugSchema, name: label(LIMITS.authorName), monogram: monogramSchema,
  kind: z.enum(lecturerKinds),
});

/** Cover object for one taxonomy owner. Optional fields exist only when that owner accepts the kind (D-035). */
function taxonomyCoverSchema(owner: "area" | "subarea") {
  const accepts = (kind: string) => (coverKindsByOwner[owner] as readonly string[]).includes(kind);
  return z.strictObject({
    poster: mediaShaSchema,
    heroDesktop: mediaShaSchema,
    heroPresent: mediaShaSchema,
    heroMobile: mediaShaSchema,
    ...(accepts("og") ? { og: mediaShaSchema.nullish() } : {}),
    ...(accepts("still_16x9") ? { still: mediaShaSchema.nullish() } : {}),
    ...(accepts("lesson_default") ? { lessonDefault: mediaShaSchema.nullish() } : {}),
  });
}
export const batchAreaCoverSchema = taxonomyCoverSchema("area");
export const batchSubareaCoverSchema = taxonomyCoverSchema("subarea");
export const batchAreaSchema = z.strictObject({ id: entityIdSchema, title: label(LIMITS.areaTitle), cover: batchAreaCoverSchema.optional() });
export const batchSubareaSchema = z.strictObject({ id: entityIdSchema, areaId: entityIdSchema, title: label(LIMITS.areaTitle), cover: batchSubareaCoverSchema.optional() });

export const batchLicenseSchema = z.strictObject({
  code: licenseCodeSchema,
  name: label(LIMITS.authorName),
  url: httpsUrlSchema.nullish(),
  requiresAttribution: z.boolean(),
  nonCommercial: z.boolean().default(false),
  shareAlike: z.boolean().default(false),
  embedOnly: z.boolean().default(true),
  attributionTemplate: label(LIMITS.attributionText).nullish(),
});

/** The cover kinds present on a taxonomy node, in the shared field order. `allowed` is false when that owner does not accept the kind (D-035). */
export function taxonomyCoverEntries(owner: "area" | "subarea", cover: object | undefined): { kind: string; sha: string; allowed: boolean }[] {
  if (!cover) return [];
  const fields = cover as Readonly<Record<string, unknown>>;
  return (Object.entries(coverFieldByKind) as [string, string][]).flatMap(([kind, field]) => {
    const sha = fields[field];
    return typeof sha === "string" ? [{ kind, sha, allowed: coverKindAllowed(owner, kind) }] : [];
  });
}

export const batchHomeRowSchema = z.strictObject({
  id: homeRowIdSchema, institutionId: entityIdSchema, title: label(LIMITS.courseTitle), fullName: label(LIMITS.courseTitle).nullish(),
  place: label(LIMITS.courseTitle).nullish(), after: homeRowIdSchema.nullish(), visible: z.boolean().default(true),
  /** The row's own 9:16 cover; its credit is shown on /credits (university-cover.ts). */
  cover: z.strictObject({
    sha: mediaShaSchema, alt: label(LIMITS.coverAlt), credit: label(LIMITS.coverCredit), sourceUrl: httpsUrlSchema, license: label(LIMITS.licenseName), note: label(LIMITS.coverNote).nullish(),
  }),
  og: mediaShaSchema.nullish(),
});

export const batchCourseSchema = z.strictObject({
  /** The offering institution (D-024); course.authorId is the lecturer. */
  institutionId: entityIdSchema,
  course: bundleCourseSchema,
  editions: many(bundleEditionSchema),
  lessons: many(bundleLessonSchema),
  texts: many(bundleTextSchema),
  covers: many(z.strictObject({ kind: z.enum(bundleCoverKinds), sha: mediaShaSchema })),
  /** The University row the course is placed on, if any; it must be its institution's row (INV-H5). */
  homeRowId: homeRowIdSchema.nullish(),
});

export const catalogBatchV2Schema = z.strictObject({
  version: z.literal(2, { error: "Only CatalogBatchV2 is accepted here." }),
  /** Overwrite a stored reference whose content differs instead of reporting a conflict. */
  updateRefs: z.boolean().default(false),
  sources: many(batchSourceSchema),
  licenses: many(batchLicenseSchema),
  institutions: many(batchInstitutionSchema),
  lecturers: many(batchLecturerSchema),
  areas: many(batchAreaSchema),
  subareas: many(batchSubareaSchema),
  homeRows: many(batchHomeRowSchema),
  courses: z.array(batchCourseSchema).min(EXTENT.one),
});

export type CatalogBatchV2 = z.output<typeof catalogBatchV2Schema>;
export type BatchInstitution = CatalogBatchV2["institutions"][number];
export type BatchLecturer = CatalogBatchV2["lecturers"][number];
export type BatchSource = CatalogBatchV2["sources"][number];
export type BatchArea = CatalogBatchV2["areas"][number];
export type BatchSubarea = CatalogBatchV2["subareas"][number];
export type BatchHomeRow = CatalogBatchV2["homeRows"][number];
export type BatchCourse = CatalogBatchV2["courses"][number];
