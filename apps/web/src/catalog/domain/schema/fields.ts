import { z } from "zod";
import { EDITION_YEARS, LIMITS } from "../../../kernel/limits.ts";
import { youtubeIdSchema } from "../youtube-identity.ts";
import { EXTENT } from "../../../kernel/extent.ts";

export { EDITION_YEARS, LIMITS };

/** Course cover kinds a batch may attach. The owner lists live in kernel/cover-kinds.ts (D-035). */
export { batchCourseCoverKinds as bundleCoverKinds } from "../../../kernel/cover-kinds.ts";

// INV-R1 (docs/domain/CONTRACT.md §4): every catalog id, slug, label limit, enum and default lives here once.
// The numbers are the kernel limit object, because the database checks read that same object.
// The bundle validator (./bundle.ts), the admin route contracts (../contracts.ts) and docs/catalog/schema.md derive from it.

export const lessonNouns = ["Lecture", "Episode"] as const;
export const lessonParts = ["lectures", "labs"] as const;
export const rightsStatus = {
  unverified: "unverified",
  cleared: "cleared",
  permissionRequested: "permission-requested",
  acceptedRisk: "accepted-risk",
  restricted: "restricted",
} as const;
export const rightsStatuses = [rightsStatus.unverified, rightsStatus.cleared, rightsStatus.permissionRequested, rightsStatus.acceptedRisk, rightsStatus.restricted] as const;
/** Rights a course may carry while published. The other statuses are not publishable. */
export const publishableRights = [rightsStatus.cleared, rightsStatus.acceptedRisk] as const;

/** What an omitted field means. `editionYear: null` is "unknown": a year is never invented (X3). */
export const DEFAULTS = {
  lessonNoun: "Lecture",
  lessonPart: "lectures",
  editionYear: null,
} as const satisfies { lessonNoun: (typeof lessonNouns)[number]; lessonPart: (typeof lessonParts)[number]; editionYear: null };

export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export const slugSchema = z.string().regex(SLUG_PATTERN);
export const entityIdSchema = slugSchema.max(LIMITS.entityId);
export const authorSlugSchema = slugSchema.max(LIMITS.authorSlug);
export const courseSlugSchema = slugSchema.max(LIMITS.courseSlug);
export const lessonSlugSchema = slugSchema.max(LIMITS.lessonSlug);
export const editionSlugSchema = slugSchema.max(LIMITS.editionSlug);
export const homeRowIdSchema = slugSchema.max(LIMITS.homeRowId);
export const httpsUrlSchema = z.string().max(LIMITS.url).regex(/^https:\/\/[^\s/]+/);
export const licenseCodeSchema = z.string().regex(/^[a-z0-9]+(?:[-.][a-z0-9]+)*$/).max(LIMITS.licenseCode);

/**
 * YouTube's license is CC BY 3.0 and embed-only (D-035). One value: the batch, the plan and the store use it.
 * It is a license code, not a rights status.
 */
export const ccByLicense = {
  code: "cc-by",
  name: "CC BY 3.0",
  url: "https://creativecommons.org/licenses/by/3.0/",
  embedOnly: true,
  requiresAttribution: true,
  nonCommercial: false,
  shareAlike: false,
} as const;
export const sourceIdSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/);
export const editionYearSchema = z.number().int().min(EDITION_YEARS.min).max(EDITION_YEARS.max);
export const revisionSchema = z.number().int().positive();
export const textFieldSchema = z.string().regex(/^[A-Za-z]{1,40}$/);
export const monogramSchema = z.string().trim().min(EXTENT.one).max(LIMITS.monogram);
/** A media object's content address (lowercase hex sha256); covers in a batch travel as this. */
export const mediaShaSchema = z.string().regex(/^[a-f0-9]{64}$/);
export { youtubeIdSchema };

/** Trimmed, non-empty text of at most `max` characters. */
export const label = (max: number) => z.string().trim().min(EXTENT.one).max(max);

/** Institution kind is always declared (INV-H1); it has no default. */
export const authorKind = { person: "person", institution: "institution", channel: "channel" } as const;
export const authorKinds = [authorKind.person, authorKind.institution, authorKind.channel] as const;
/** A lecturer teaches courses. An institution is not a lecturer (D-024). */
export const lecturerKinds = [authorKind.person, authorKind.channel] as const;

/** What distinguishes two offerings of one course and year (D-034). One list; the database check uses these words. */
export const editionVariantKinds = ["language", "term", "group"] as const;
export const editionVariantSchema = z.strictObject({
  kind: z.enum(editionVariantKinds),
  label: label(LIMITS.editionVariantLabel),
});
export type EditionVariant = z.infer<typeof editionVariantSchema>;
