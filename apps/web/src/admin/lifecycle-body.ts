import { z } from "zod";
import { LIMITS } from "../kernel/limits.ts";

const sha256 = z.string().regex(/^[a-f0-9]{64}$/);

export const lifecycleGcBody = z.discriminatedUnion("op", [
  z.strictObject({ op: z.literal("storage-list"), cursor: z.string().max(LIMITS.storageCursor).nullable() }),
  z.strictObject({ op: z.literal("mark"), sha256 }),
  z.strictObject({ op: z.literal("clear"), sha256 }),
  z.strictObject({ op: z.literal("barrier") }),
  z.strictObject({ op: z.literal("revalidate") }),
  z.strictObject({ op: z.literal("delete-row"), sha256 }),
  z.strictObject({ op: z.literal("copy-aside"), sha256 }),
  z.strictObject({ op: z.literal("remove"), sha256 }),
  z.strictObject({ op: z.literal("exists"), sha256 }),
]);

export const lifecycleResetBody = z.strictObject({ dryRun: z.boolean() });
