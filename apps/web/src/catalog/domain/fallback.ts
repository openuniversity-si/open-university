import { bakedReleaseSchema } from "./baked.ts";
import { normalizeRelease, type PublicCatalog } from "./release.ts";

/** Normalizes a baked release the caller already loaded. The domain does not read the file. */
export function normalizeBakedRelease(generated: unknown): { source: "database" | "fixture"; sha: string; release: PublicCatalog } {
  const parsed = bakedReleaseSchema.parse(generated);
  return { ...parsed, release: normalizeRelease(parsed.release) };
}
