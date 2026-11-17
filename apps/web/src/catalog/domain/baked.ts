import { z } from "zod";
import { releaseSchema, releaseV1Schema } from "./release.ts";

/**
 * `src/catalog/domain/generated/release.json` (gitignored), written by `pnpm catalog:bake` before each build: the active
 * release of the target's database, or a synthetic current-schema fixture when the build has no database. The payload is
 * kept as stored (version 1 or 2, so `sha` still matches it); normalizeBakedRelease() normalizes it (ADR-21).
 */
export const bakedReleaseSchema = z.strictObject({
  source: z.enum(["database", "fixture"]),
  sha: z.string().regex(/^[a-f0-9]{64}$/),
  release: z.union([releaseSchema, releaseV1Schema]),
});
export type BakedRelease = z.infer<typeof bakedReleaseSchema>;
