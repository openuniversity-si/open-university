import "server-only";
import { logStructured } from "../../platform/observability/logger.ts";
import { getSession } from "../../identity/server/session.ts";
import { appPool } from "../../platform/db/pool.ts";
import { readProgress, type ProgressDatabase } from "./repo.ts";
import type { ProgressRow } from "../domain/rules.ts";

const database: () => ProgressDatabase = appPool;

export type ViewerProgress = readonly (ProgressRow & { readonly courseId: string })[];

/** The signed-in viewer's rows, or null when signed out (pages then render the signed-out screens). */
export async function getViewerProgress(requestHeaders: Headers): Promise<ViewerProgress | null> {
  let userId: string;
  try {
    const session = await getSession(requestHeaders);
    if (!session) return null;
    userId = session.user.id;
  } catch {
    logStructured("error", "PROGRESS_SESSION_FAILED");
    return null;
  }
  try {
    return await readProgress(database(), userId);
  } catch {
    logStructured("error", "PROGRESS_READ_FAILED");
    return [];
  }
}

