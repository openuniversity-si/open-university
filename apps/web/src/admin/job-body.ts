import { z } from "zod";
import { LIMITS } from "../kernel/limits.ts";
import { JOB_STAGES } from "./ports/jobs.ts";
import { EXTENT } from "../kernel/extent.ts";

const sha256 = z.string().regex(/^[a-f0-9]{64}$/);
const key = z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/);
const stage = z.enum(JOB_STAGES);

export const jobClaimBody = z.strictObject({
  idempotencyKey: key,
  bundleSha256: sha256,
  environment: z.enum(["preview", "prod"]),
  draft: z.boolean(),
});

export const jobAdvanceBody = z.strictObject({
  token: z.number().int().positive(),
  expected: stage,
  draft: z.boolean(),
  checkpoint: z.strictObject({
    stage,
    draft: z.boolean().optional(),
    uploads: z.array(z.strictObject({ sha256, objectKey: z.string().min(EXTENT.one).max(LIMITS.objectKey) })).optional(),
    applyReceipt: z.strictObject({ bundleSha256: sha256, applied: z.boolean() }).optional(),
    release: z.strictObject({ number: z.number().int().positive(), hash: sha256 }).optional(),
    verification: z.strictObject({ ok: z.boolean(), reason: z.string().max(LIMITS.jobMessage).optional() }).optional(),
  }),
});

export const jobCompleteBody = z.strictObject({
  token: z.number().int().positive(),
  draft: z.boolean(),
  stage: z.enum(["VERIFIED", "FAILED", "PAUSED"]),
  error: z.string().max(LIMITS.jobMessage).optional(),
});

/** Heartbeat: extends the lease this token holds; a lapsed or newer lease is refused. */
export const jobRenewBody = z.strictObject({
  token: z.number().int().positive(),
  draft: z.boolean(),
});

export type JobClaimBody = z.infer<typeof jobClaimBody>;
export type JobAdvanceBody = z.infer<typeof jobAdvanceBody>;
export type JobCompleteBody = z.infer<typeof jobCompleteBody>;
export type JobRenewBody = z.infer<typeof jobRenewBody>;
