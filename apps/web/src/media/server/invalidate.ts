import "server-only";
import { expirePath, expireTag } from "../../platform/freshness/next.ts";
import { CACHE } from "../../kernel/cache.ts";
import type { MediaInvalidation } from "../domain/tags.ts";

/** Expires the planned media tags now, and purges the planned static pages (`mediaInvalidation`, src/media/domain/tags.ts). */
export function invalidateMedia(plan: MediaInvalidation) {
  for (const tag of plan.tags) expireTag(tag, { expire: CACHE.immediateExpiry });
  for (const path of plan.paths) expirePath(path);
}
