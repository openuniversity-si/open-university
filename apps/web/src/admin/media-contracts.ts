import { z } from "zod";
import { LIMITS } from "../kernel/limits.ts";
import { ownerIdSchema, ownerSchema, transformSchema, variantSchema, type MediaOwner } from "../media/domain/types.ts";
import { EXTENT } from "../kernel/extent.ts";

const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);

/** Serverless hosts cap request bodies at a few MB; the admin edge rejects earlier. */
export const MEDIA_MAX_BYTES = LIMITS.mediaBodyBytes;

const ownerKey = z.object({ owner: ownerSchema, ownerId: ownerIdSchema });

const ownerToken = /^(institution|area|subarea|course|lesson):[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** One `media list` query. `--owners` is a comma-separated `type:id` list and cannot mix with a single owner. */
export const mediaListQuery = z.object({
  owner: ownerSchema.optional(),
  ownerId: ownerIdSchema.optional(),
  owners: z.string().optional(),
  kind: z.string().optional(),
  variant: variantSchema.optional(),
  all: z.literal("1").optional(),
}).superRefine((query, ctx) => {
  const fail = (message: string) => { ctx.addIssue({ code: "custom", message, path: ["owners"] }); };
  if (query.owners === undefined) return;
  if (query.owner !== undefined || query.ownerId !== undefined) fail("owners cannot be combined with owner or ownerId.");
  const tokens = query.owners.split(",").filter((token) => token.length > 0);
  if (tokens.length < 1 || tokens.length > 200) fail("owners needs 1 to 200 type:id tokens.");
  for (const token of tokens) if (!ownerToken.test(token)) fail(`Invalid owner ${token}.`);
});

export function parseMediaOwners(owners: string): { owner: MediaOwner; ownerId: string }[] {
  return owners.split(",").filter((token) => token.length > 0).map((token) => {
    const separator = token.indexOf(":");
    return { owner: ownerSchema.parse(token.slice(0, separator)), ownerId: token.slice(separator + 1) };
  });
}

export const mediaCheckBody = z.strictObject({ sha256: z.array(sha256Schema).max(LIMITS.mediaCheckBatch) });

export const mediaAttachBody = ownerKey.extend({
  kind: z.string(),
  variant: variantSchema.default("default"),
  sha256: sha256Schema,
  alt: z.string().trim().min(EXTENT.one).max(LIMITS.mediaAlt),
  designStatus: z.enum(["approved", "draft", "legacy"]).default("approved"),
  transform: transformSchema.default(null),
  forceOversize: z.boolean().default(false),
}).strict();

export const mediaRollbackBody = z.strictObject({
  owner: ownerSchema,
  ownerId: ownerIdSchema,
  kind: z.string(),
  variant: variantSchema.default("default"),
  version: z.number().int().positive(),
});

export const mediaDeleteBody = z.strictObject({
  owner: ownerSchema,
  ownerId: ownerIdSchema,
  kind: z.string(),
  variant: variantSchema.default("default"),
  version: z.number().int().positive().optional(),
  apply: z.boolean().default(false),
  keepBytes: z.boolean().default(false),
});

export const mediaPruneBody = z.strictObject({ apply: z.boolean().default(false) });

export const mediaUploadFields = ownerKey.extend({
  kind: z.string(),
  variant: variantSchema.default("default"),
  alt: z.string().trim().min(EXTENT.one).max(LIMITS.mediaAlt),
  designStatus: z.enum(["approved", "draft", "legacy"]).default("approved"),
  transform: z.string().optional(),
  forceOversize: z.literal("1").optional(),
});
