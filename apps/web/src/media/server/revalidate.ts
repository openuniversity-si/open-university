import { z } from "zod";
import { adminAuthorized } from "../../admin/auth.ts";
import { appPool } from "../../platform/db/pool.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { mediaInvalidation, MEDIA_TAG, type MediaInvalidation } from "../domain/tags.ts";
import type { MediaCourse } from "../ports/owner.ts";
import { ownerIdSchema, ownerSchema, variantSchema } from "../domain/types.ts";

export const revalidationSchema = z.strictObject({ courseId: ownerIdSchema.optional(), owner: ownerSchema.optional(), kind: z.string().optional(), variant: variantSchema.optional() });
/** The admin Bearer check (src/admin/guard.ts), under the name the media revalidation has always used. */
export const mediaAuthorized = adminAuthorized;
/**
 * The explicit, manual revalidation (`media:put`/`media:rollback` after a direct write, or an operator): one course's media
 * reads (published courses only), or with no courseId every media read. The admin API never calls it; it plans its own (tags.ts).
 */
export async function handleMediaRevalidation(request: Request, secret: string | undefined, invalidate: (plan: MediaInvalidation) => void, courseOf?: (courseId: string, db: () => Queryable) => Promise<MediaCourse | undefined>, db: () => Queryable = appPool) {
  if (!secret) return Response.json({ error: "Media revalidation is not configured." }, { status: 503 });
  if (!mediaAuthorized(request.headers.get("authorization"), secret)) return Response.json({ error: "Unauthorized." }, { status: 401 });
  let body: unknown;
  try { body = await request.json(); } catch { return Response.json({ error: "Invalid JSON." }, { status: 400 }); }
  const result = revalidationSchema.safeParse(body);
  if (!result.success) return Response.json({ error: "Invalid media request." }, { status: 400 });
  let plan: MediaInvalidation = { tags: [MEDIA_TAG], paths: [] };
  if (result.data.courseId) {
    if (!courseOf) return Response.json({ error: "Course verification unavailable." }, { status: 503 });
    const course = await courseOf(result.data.courseId, db);
    if (!course) return Response.json({ error: "Unknown course." }, { status: 404 });
    plan = mediaInvalidation({ ...course, owner: result.data.owner ?? "course", kind: result.data.kind ?? "poster_9x16", variant: result.data.variant });
  }
  if (plan.tags.length) invalidate(plan);
  return Response.json({ revalidated: plan.tags });
}
