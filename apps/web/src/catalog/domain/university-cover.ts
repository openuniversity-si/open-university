import { z } from "zod";
import { mediaUrlSchema } from "../../media/domain/types.ts";
import { authorCoverSchema } from "./author-cover.ts";

/**
 * A university's cover (Daniel, 14/10/2026; docs/catalog/university-covers.md): one 9:16 image per institution (a
 * `curated` Home row, the Universities tab), shown in the Home "Universities" portal. Same shape and rules as an author
 * cover (author-cover.ts): stored as `home_rows.cover` (0011), set by a CatalogBatchV2 home row inside `tower-catalog ship`, published in the
 * release's `home.rows[].cover`; the credit is mandatory and shown on /credits (credits.ts).
 */
export const UNIVERSITY_COVER_KIND = "university_cover_9x16";
/** The 1200×630 JPEG link preview composed from the cover (media/og.ts; `tower-catalog home og`); optional, older releases have none. */
export const universityOgSchema = z.strictObject({
  mediaSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
  url: mediaUrlSchema, width: z.number().int().positive(), height: z.number().int().positive(), sha256: z.string().regex(/^[a-f0-9]{64}$/),
});
export const universityCoverSchema = authorCoverSchema.extend({ og: universityOgSchema.optional() });
export type UniversityCover = import("zod").infer<typeof universityCoverSchema>;
