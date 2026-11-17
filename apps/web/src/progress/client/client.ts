import { CACHE } from "../../kernel/cache.ts";
import type { LessonIdentity } from "../../playback/domain/engine.ts";

export interface ProgressUpdate extends LessonIdentity {
  readonly positionSeconds?: number;
  readonly completed?: boolean;
}

/** Same-origin POST with the session cookie. `keepalive` is the beacon: it survives pagehide and navigation. */
export async function sendProgress(update: ProgressUpdate, keepalive = false): Promise<boolean> {
  try {
    const response = await fetch("/api/progress", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update), credentials: "same-origin", cache: CACHE.fetchNoStore, keepalive,
    });
    return response.ok;
  } catch { return false; }
}
