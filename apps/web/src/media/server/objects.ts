import { currentEnv } from "../../kernel/env.ts";
import { createHash } from "node:crypto";
import sharp from "sharp";
import { objectDescriptor as describeObject, objectKey, objectSchema, sha256Schema, type MediaObject } from "../domain/objects.ts";
import type { MediaDatabase } from "./repository.ts";
import { MediaInputError, prepareMedia } from "./prepare.ts";
import { type MediaObjectStore } from "./storage.ts";
import { StorageError } from "./storage-error.ts";
import { mediaContentType, mediaPolicy } from "../domain/types.ts";
import "./public-hosts.ts";
import { clearOrphaned } from "./lifecycle.ts";

export { objectKey, objectSchema, objectUrl, sha256Schema, type MediaObject, type ObjectExtension, type ObjectIdentity } from "../domain/objects.ts";
export const objectDescriptor = (object: MediaObject) => describeObject(object, mediaPolicy(currentEnv()));
const columns = 'sha256, ext, content_type AS "contentType", bytes::float8 AS bytes, width, height';

export async function readObjects(db: MediaDatabase, hashes: readonly string[]): Promise<MediaObject[]> {
  hashes.forEach((hash) => sha256Schema.parse(hash));
  if (!hashes.length) return [];
  return (await db.query(`SELECT ${columns} FROM media_objects WHERE sha256=ANY($1)`, [hashes])).rows.map((row) => objectSchema.parse(row));
}
/** INSERT is atomic; a race may reuse identical metadata, never replace it. */
export async function registerObject(db: MediaDatabase, value: MediaObject): Promise<MediaObject> {
  const object = objectSchema.parse(value);
  await db.query(`INSERT INTO media_objects (sha256,ext,content_type,bytes,width,height) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (sha256) DO NOTHING`,
    [object.sha256, object.ext, object.contentType, object.bytes, object.width, object.height]);
  await clearOrphaned(db, object.sha256);
  const saved = (await readObjects(db, [object.sha256]))[0];
  if (!saved || Object.keys(object).some((key) => saved[key as keyof MediaObject] !== object[key as keyof MediaObject])) throw new StorageError("Immutable media metadata conflicts with the object registry.");
  return saved;
}
/** Read the actual bytes, never trust a filename, ETag, size, or caller-supplied dimensions as a content checksum. */
export async function inspectObject(bytes: Buffer, sha256: string, ext: string): Promise<MediaObject> {
  if (createHash("sha256").update(bytes).digest("hex") !== sha256) throw new StorageError("Immutable media checksum mismatch.");
  const info = await sharp(bytes).metadata();
  const actualExt = info.format === "jpeg" ? "jpg" : info.format === "heif" ? "avif" : info.format;
  if (actualExt !== ext || (info.pages ?? 1) !== 1) throw new StorageError("Immutable media format mismatch.");
  return objectSchema.parse({ sha256, ext, contentType: mediaContentType(`file.${ext}`), bytes: bytes.length, width: info.width, height: info.height });
}
/** Shared R2, separate databases: discover and verify existing content without asking the caller to retransmit it. */
export async function checkObjects(db: MediaDatabase, store: MediaObjectStore, hashes: readonly string[]) {
  const unique = [...new Set(hashes.map((hash) => sha256Schema.parse(hash)))];
  const objects = await readObjects(db, unique);
  const found = new Set(objects.map((object) => object.sha256));
  for (const hash of unique.filter((hash) => !found.has(hash))) {
    for (const ext of objectSchema.shape.ext.options) {
      const key = objectKey(hash, ext);
      if (!await store.head(key)) continue;
      const bytes = await store.get(key);
      if (!bytes) throw new StorageError("Media disappeared during registration.");
      objects.push(await registerObject(db, await inspectObject(bytes, hash, ext)));
      found.add(hash);
      break;
    }
  }
  return { missing: unique.filter((hash) => !found.has(hash)), objects: objects.map((object) => ({ ...object, ...objectDescriptor(object) })) };
}
export async function uploadObject(db: MediaDatabase, store: MediaObjectStore, bytes: Uint8Array, expectedHash?: string): Promise<MediaObject> {
  const prepared = await prepareMedia(bytes);
  if (expectedHash && prepared.sha256 !== expectedHash) throw new MediaInputError("Prepared image does not match the requested sha256.");
  const found = (await checkObjects(db, store, [prepared.sha256])).objects[0];
  if (found) return objectSchema.parse(found);
  const key = objectKey(prepared.sha256, prepared.extension);
  await store.put(key, prepared.bytes);
  const stored = await store.get(key);
  if (!stored) throw new StorageError("Uploaded media is missing.");
  return registerObject(db, await inspectObject(stored, prepared.sha256, prepared.extension));
}

/** Author/university covers retain their release lifecycle, but are included in the same integrity inventory. */
export async function coverObjectInventory(db: MediaDatabase, entries: readonly { readonly ownerId: string; readonly kind: string; readonly cover: unknown }[]) {
  const covers: { ownerId: string; kind: string; variant: string; version: number; url: string; width: number; height: number; sha256: string; alt: string; active: boolean }[] = [];
  const add = (ownerId: string, kind: string, value: unknown) => {
    if (!value || typeof value !== "object") return;
    const cover = value as { url: string; width: number; height: number; sha256: string; alt?: string; og?: unknown };
    covers.push({ ownerId, kind, variant: "default", version: 1, url: cover.url, width: cover.width, height: cover.height, sha256: cover.sha256, alt: cover.alt ?? "University link preview", active: true });
    if (cover.og) add(ownerId, "university_og", cover.og);
  };
  for (const entry of entries) add(entry.ownerId, entry.kind, entry.cover);
  const objects = new Map((await readObjects(db, covers.map((cover) => cover.sha256))).map((object) => [object.sha256, object]));
  return covers.map((cover) => {
    const object = objects.get(cover.sha256);
    return object ? { ...cover, ...objectDescriptor(object) } : cover;
  });
}
