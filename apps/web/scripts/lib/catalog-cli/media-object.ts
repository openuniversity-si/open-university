import { prepareMedia } from "../../../src/media/server/prepare.ts";
import { mediaContentType } from "../../../src/media/server/storage.ts";
import type { PreparedMedia } from "./client.ts";
import { mediaKeyFor, uploadPrepared, type MediaIntent } from "./commands/media.ts";
import type { Context } from "./context.ts";

/** Only the API writes R2. Bytes stay in memory: check, then POST only what is missing. */
export async function uploadCatalogObject(context: Context, source: string | Uint8Array) {
  const prepared = await prepareMedia(source);
  const media: PreparedMedia = {
    bytes: prepared.bytes, sha256: prepared.sha256, extension: prepared.extension as PreparedMedia["extension"],
    contentType: mediaContentType(`file.${prepared.extension}`), width: prepared.width, height: prepared.height,
  };
  const intent: MediaIntent = { target: context.target === "prod" ? "prod" : "preview", owner: "course", ownerId: "object", kind: "poster_9x16", variant: "default", alt: "object", forceOversize: true };
  return uploadPrepared({
    client: { call: (input, decode) => context.client.adminCall(input, decode) },
    prepare: () => Promise.resolve(media),
    confirm: (question) => context.confirm(question, true),
    keyFor: mediaKeyFor,
    readOnly: context.client.readOnly,
  }, { media, intent, dryRun: context.dryRun, attach: false });
}
