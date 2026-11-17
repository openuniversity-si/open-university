import { CACHE } from "../../kernel/cache.ts";

/** How long a video check still serves before publish asks the lesson again. The watcher's sheet is twenty-four hours and stays there. */
export const VIDEO_CHECK_FRESH_DAYS = 7;

/** Checks older than this are redone before publish. */
export function videoCheckCutoff(now: Date): string {
  return new Date(now.getTime() - VIDEO_CHECK_FRESH_DAYS * CACHE.dayMs).toISOString();
}
