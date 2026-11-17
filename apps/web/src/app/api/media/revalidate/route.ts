import "server-only";
import { currentEnv } from "@/kernel/env.ts";
import { catalogCourseOf } from "@/catalog/server/media-owners.ts";
import { invalidateMedia } from "@/media/server/invalidate.ts";
import { handleMediaRevalidation } from "@/media/server/revalidate.ts";

export const runtime = "nodejs";
export async function POST(request: Request) {
  return handleMediaRevalidation(request, currentEnv().TOWER_MEDIA_REVALIDATE_SECRET, invalidateMedia, (id, db) => catalogCourseOf(db)("course", id));
}
