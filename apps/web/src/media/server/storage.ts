import { currentEnv } from "../../kernel/env.ts";
import { assertWithinBudget } from "../domain/budget.ts";
import type { MediaObjectStore } from "../ports/storage.ts";
import { type AssetInput, type MediaKind, type MediaOwner, MEDIA_CACHE_CONTROL, mediaContentType, mediaKey, mediaUrlSchemaFor } from "../domain/types.ts";
export { MEDIA_CACHE_CONTROL, mediaContentType } from "../domain/types.ts";
export type { MediaObjectStore } from "../ports/storage.ts";
import { mediaPublicHost, mediaPublicHosts } from "./public-hosts.ts";
import { prepareMedia } from "./prepare.ts";
import { createS3Bucket, hasR2Credentials, r2Config, type R2Access } from "./r2-budget.ts";
import { StorageError } from "./storage-error.ts";

type Env = Readonly<Record<string, string | undefined>>;

/** The public media bucket (custom domain `MEDIA_PUBLIC_HOST` points at it). */
export const R2_MEDIA_BUCKET_DEFAULT = "open-university-media";

/** The writable store admin and catalog open. Same object as today's R2 store. */
export function createWritableMediaStore(env: Env = currentEnv()): MediaObjectStore {
  return createR2MediaStore(env, "rw");
}

export function createR2MediaStore(env: Env, access: R2Access): MediaObjectStore {
  const host = mediaPublicHost(env);
  const bucket = createS3Bucket(r2Config(env, env.R2_MEDIA_BUCKET ?? R2_MEDIA_BUCKET_DEFAULT, access));
  return {
    publicUrl: (pathname) => `https://${host}/${pathname}`,
    head: (pathname) => bucket.head(pathname),
    get: (pathname) => bucket.get(pathname),
    put: (pathname, bytes) => bucket.put(pathname, bytes, { contentType: mediaContentType(pathname), cacheControl: MEDIA_CACHE_CONTROL }),
    copy: (source, target) => bucket.copy(source, target, mediaContentType(target), MEDIA_CACHE_CONTROL),
    delete: (pathname) => bucket.delete(pathname),
  };
}

/** The write store for `media:put` (rw) or the read store for checks/cache (ro). */
export function createMediaStore(env: Env = currentEnv(), access: R2Access = "rw"): MediaObjectStore {
  return createR2MediaStore(env, access);
}
/** Read store when credentials exist; undefined means "use the public URL". */
export function optionalReadStore(env: Env = currentEnv()): MediaObjectStore | undefined {
  return hasR2Credentials(env, "ro") ? createR2MediaStore(env, "ro") : undefined;
}

/** `forceOversize` stores an asset above its kind's byte budget (a conscious exception); otherwise MediaBudgetError. */
export async function uploadMedia(owner: MediaOwner, ownerId: string, kind: string, variant: string, file: string | Uint8Array, store: MediaObjectStore, descriptor: Pick<AssetInput, "alt" | "designStatus" | "transform">, options: { forceOversize?: boolean } = {}): Promise<AssetInput> {
  mediaKey(owner, ownerId, kind, variant);
  const prepared = await prepareMedia(file);
  assertWithinBudget(kind as MediaKind, prepared.bytes.length, options.forceOversize);
  const pathname = `m/${prepared.sha256}.${prepared.extension}`;
  const url = store.publicUrl(pathname);
  mediaUrlSchemaFor(mediaPublicHosts(currentEnv())).parse(url);
  // Deterministic bytes and pathname: reuse on restart; never overwrite an existing immutable key.
  const existing = await store.head(pathname);
  if (existing && existing.size !== prepared.bytes.length) throw new StorageError("An object with this immutable key already exists with different bytes.");
  if (!existing) await store.put(pathname, prepared.bytes);
  return { ownerId, kind: kind as MediaKind, variant, url, pathname, width: prepared.width, height: prepared.height, sha256: prepared.sha256, ...descriptor };
}
