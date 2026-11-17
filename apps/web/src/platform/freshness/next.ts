/** Tagged reads and path purges. Callers name a tag or a path. This file is the only Next cache client. */

import "server-only";
import { revalidatePath, revalidateTag, unstable_cache } from "next/cache";

export interface FreshnessProfile {
  readonly tags?: readonly string[];
  readonly revalidate?: number | false;
}

/** Remember a read under the host cache. The key and the tags are the caller's. */
export function remember<T>(read: () => Promise<T>, key: readonly string[], profile?: FreshnessProfile): () => Promise<T> {
  return unstable_cache(read, [...key], {
    ...(profile?.tags === undefined ? {} : { tags: [...profile.tags] }),
    ...(profile?.revalidate === undefined ? {} : { revalidate: profile.revalidate }),
  });
}

/** Expire one tag now. `expire` is the host's immediate profile, unchanged. */
export function expireTag(tag: string, expiry: { readonly expire: number }): void {
  revalidateTag(tag, expiry);
}

/** Purge one path. A type purges that segment; an absent type purges the path itself. */
export function expirePath(path: string, type?: "layout" | "page"): void {
  if (type === undefined) revalidatePath(path);
  else revalidatePath(path, type);
}
