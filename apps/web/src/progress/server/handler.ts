import { CACHE } from "../../kernel/cache.ts";
import { appPool } from "../../platform/db/pool.ts";
import { requestContextFrom, REQUEST_ID_HEADER } from "../../platform/observability/context.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import type { PublishedLessonLookup } from "../ports/lessons.ts";
import { saveProgress, type ProgressDatabase } from "./repo.ts";

export interface ProgressRequestDependencies extends PublishedLessonLookup {
  readonly uuid?: () => string;
  /** Omitted by the route. Tests pass a database; the app pool is the default. */
  readonly db?: () => ProgressDatabase;
  readonly expectedOrigin: () => string;
  /** Must observe DB revocation immediately (no session cookie cache). */
  readonly userId: (headers: Headers) => Promise<string | null>;
}

/** `POST /api/progress`: `{ courseSlug, lessonSlug, positionSeconds?, completed? }` for the signed-in viewer. */
export async function handleProgressPost(request: Request, deps: ProgressRequestDependencies): Promise<Response> {
  const context = requestContextFrom(request, "/api/progress", deps.uuid);
  const headers = { "Cache-Control": CACHE.responseNoStore, [REQUEST_ID_HEADER]: context.requestId };
  const json = (status: number, body: object) => Response.json(body, { status, headers });
  try {
    if (request.headers.get("origin") !== deps.expectedOrigin()) return json(403, { error: "origin" });
    const userId = await deps.userId(request.headers);
    if (!userId) return json(401, { error: "unauthenticated" });
    let body: unknown;
    try {
      const text = await request.text();
      if (text.length > 1024) return json(413, { error: "too_large" });
      body = JSON.parse(text);
    } catch { return json(400, { error: "invalid" }); }
    if (typeof body !== "object" || body === null) return json(400, { error: "invalid" });
    const { courseSlug, lessonSlug, positionSeconds, completed } = body as Record<string, unknown>;
    const position = typeof positionSeconds === "number" && Number.isFinite(positionSeconds) ? positionSeconds : undefined;
    const completion = typeof completed === "boolean" ? completed : undefined;
    if (typeof courseSlug !== "string" || typeof lessonSlug !== "string" || (positionSeconds !== undefined && position === undefined)
      || (completed !== undefined && completion === undefined) || (position === undefined && completion === undefined)) return json(400, { error: "invalid" });
    const lesson = await deps.resolvePublishedLesson(courseSlug, lessonSlug);
    if (!lesson) return json(404, { error: "unknown_lesson" });
    const durationSeconds = Math.max(Math.round(lesson.durationSeconds), 1);
    const db = deps.db ?? appPool;
    const saved = await saveProgress(db(), {
      userId, courseId: lesson.courseId, lessonId: lesson.lessonId, durationSeconds,
      ...(position === undefined ? {} : { positionSeconds: Math.min(Math.max(Math.floor(position), 0), durationSeconds) }),
      ...(completion === undefined ? {} : { completed: completion }),
    });
    return saved ? new Response(null, { status: 204, headers }) : json(429, { error: "throttled" });
  } catch (error) {
    logStructured("error", "PROGRESS_WRITE_FAILED", {}, context);
    throw error;
  }
}
