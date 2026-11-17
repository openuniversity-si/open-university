import { authorCoverSchema, type AuthorCover } from "../../../../src/catalog/domain/author-cover.ts";
import { MEDIA_BYTE_BUDGETS } from "../../../../src/media/domain/budget.ts";
import { objectKey } from "../../../../src/media/server/objects.ts";
import { uploadCatalogObject } from "../media-object.ts";
import { flag, positional, requireOption, stringOption } from "../args.ts";
import type { CommandSpec } from "../context.ts";
import { UsageError } from "../errors.ts";
import type { AuthorRow } from "../responses.ts";

/** Same budget as a course poster (9:16, shown at the same sizes). */
export const AUTHOR_COVER_BUDGET = MEDIA_BYTE_BUDGETS.poster_9x16;

/**
 * `author cover <author> --file f --alt … --credit … --source-url … --license … [--note …]` (docs/catalog/author-covers.md):
 * prepares the image exactly like the media pipeline (sharp, metadata stripped, content-addressed), stores it immutably in
 * the media API (`m/<sha256>.<ext>`, no R2 credentials), then sets
 * `authors.cover`. Publishing is a separate `release create` (rollback: `release activate <previous>`).
 * `--clear` sends `cover: null`. PATCH refuses that while a visible Authors-tab row points at this author (ADR-40). The stored object stays either way.
 */
export const authorCoverCommands: CommandSpec[] = [
  {
    name: "author cover", usage: "author cover <author> --file <img> --alt <text> --credit <text> --source-url <https://…> --license <text> [--note <text>] | --clear",
    summary: "upload an author cover (media bucket) and set authors.cover; publish with release create",
    options: {
      file: { type: "string", help: "9:16 image (JPEG, PNG, WebP, AVIF)", value: "<img>" }, alt: { type: "string", help: "alt text", value: "<text>" },
      credit: { type: "string", help: "shown on the Authors tab, e.g. \"Photo: Gage Skidmore, CC BY-SA 3.0\"", value: "<text>" },
      "source-url": { type: "string", help: "where the photo comes from", value: "<url>" }, license: { type: "string", help: "license/terms as stated by the source", value: "<text>" },
      note: { type: "string", help: "extra disclosure (e.g. AI-generated background)", value: "<text>" }, clear: { type: "boolean", help: "remove the cover" },
    },
    positionals: { min: 1, max: 1 }, routes: ["GET /authors", "PATCH /authors/:id"],
    async run(context) {
      const id = positional(context.args, 0, "author");
      const author = (await context.client.call("GET /authors")).data.authors.find((entry: AuthorRow) => entry.id === id);
      if (!author) throw new UsageError(`Unknown author ${id}.`);
      let cover: AuthorCover | null = null;
      if (!flag(context.args, "clear")) {
        if (context.target === "staging") throw new UsageError("The media bucket has no staging target; set author covers on preview or prod.");
        const { prepareMedia } = await import("../../media-storage.ts");
        const prepared = await prepareMedia(requireOption(context.args, "file"));
        if (prepared.bytes.length > AUTHOR_COVER_BUDGET) throw new UsageError(`The cover is ${String(Math.ceil(prepared.bytes.length / 1024))} KiB, over the ${String(AUTHOR_COVER_BUDGET / 1024)} KiB budget (WebP q≈72).`);
        const pathname = objectKey(prepared.sha256, prepared.extension);
        await context.confirm(`Upload ${pathname} and set the cover of ${id}`);
        const object = await uploadCatalogObject(context, prepared.bytes);
        cover = authorCoverSchema.parse({
          url: object.url, width: object.width, height: object.height, sha256: object.sha256, mediaSha256: object.sha256, alt: requireOption(context.args, "alt"),
          credit: requireOption(context.args, "credit"), sourceUrl: requireOption(context.args, "source-url"), license: requireOption(context.args, "license"),
          note: stringOption(context.args, "note") ?? null,
        });
      } else {
        await context.confirm(`Remove the cover of ${id}`);
      }
      const result = await context.client.call("PATCH /authors/:id", { params: { id }, body: { cover, expectedRevision: author.revision } });
      context.out.line(`${cover ? `Cover of ${id}: ${cover.url}` : `Cover of ${id} removed`} (revision ${String(result.data.author.revision)}). Publish with: release create`);
      context.out.result(result.envelope);
    },
  },
];
