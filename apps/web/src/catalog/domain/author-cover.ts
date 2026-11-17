import { z } from "zod";
import { mediaUrlSchema } from "../../media/domain/types.ts";
import { EXTENT } from "../../kernel/extent.ts";

/**
 * An author's cover (Daniel, 14/10/2026; docs/catalog/author-covers.md): one 9:16 portrait per author, shown in the Home
 * "Authors" portal (one cover per author). Stored as `authors.cover` (0010), set by `tower-catalog author cover`, which
 * uploads the image through the media store (content-addressed, immutable, the media public host), and published in
 * the release's `authors[].cover`. The credit is mandatory: it is shown on /credits (credits.ts).
 */
export const AUTHOR_COVER_KIND = "author_cover_9x16";
const text = (max: number) => z.string().trim().min(EXTENT.one).max(max);
export const authorCoverSchema = z.strictObject({
  mediaSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
  url: mediaUrlSchema,
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  alt: text(200),
  /** Shown on the Authors tab, e.g. "Photo: Gage Skidmore, CC BY-SA 3.0". */
  credit: text(200),
  /** Where the photo comes from. */
  sourceUrl: z.string().regex(/^https:\/\//).max(500),
  /** License or terms as stated by the source ("CC BY-SA 3.0", "not stated"). */
  license: text(120),
  /** Anything else a reader must know (e.g. an AI-generated background). */
  note: text(300).nullable(),
});
export type AuthorCover = z.infer<typeof authorCoverSchema>;
