import { objectUrl, type MediaObject } from "../../media/domain/objects.ts";
import { productionMediaPolicy, type PublicMediaPolicy } from "../../media/domain/types.ts";
import type { AuthorCover } from "./author-cover.ts";
import type { PublicCatalog } from "./release.ts";

/** Legacy cover JSON remains readable; a new hash attachment must match a registered, immutable descriptor. */
export function coverObjectReference(object: MediaObject | undefined, cover: AuthorCover | null, policy: PublicMediaPolicy = productionMediaPolicy): string | null {
  if (!cover) return null;
  if (!object) {
    if (cover.mediaSha256 || new URL(cover.url).pathname.startsWith("/m/")) throw new Error("Cover object must be registered through the media API first.");
    return null;
  }
  if (cover.width !== object.width || cover.height !== object.height || (cover.mediaSha256 && cover.mediaSha256 !== object.sha256)) throw new Error("Cover descriptor differs from its object.");
  if (new URL(cover.url).pathname.startsWith("/m/") && cover.url !== objectUrl(object, policy)) throw new Error("Cover URL differs from its object.");
  return object.sha256;
}

export function coverHashes(release: PublicCatalog): string[] {
  return [...release.authors.flatMap((author) => author.cover ? [author.cover.sha256] : []), ...release.home.rows.flatMap((row) => row.cover ? [row.cover.sha256, ...(row.cover.og ? [row.cover.og.sha256] : [])] : [])];
}

/** Resolve old release JSON through a preloaded object list. Does not read a database. */
export function resolveCatalogCoverObjects(objects: readonly MediaObject[], release: PublicCatalog, policy: PublicMediaPolicy = productionMediaPolicy): PublicCatalog {
  const byHash = new Map(objects.map((object) => [object.sha256, object]));
  const resolve = <T extends { sha256: string; url: string }>(cover: T): T => {
    const object = byHash.get(cover.sha256);
    return object ? { ...cover, url: objectUrl(object, policy) } : cover;
  };
  return { ...release, authors: release.authors.map((author) => author.cover ? { ...author, cover: resolve(author.cover) } : author),
    home: { ...release.home, rows: release.home.rows.map((row) => row.cover ? { ...row, cover: { ...resolve(row.cover), ...(row.cover.og ? { og: resolve(row.cover.og) } : {}) } } : row) } };
}
