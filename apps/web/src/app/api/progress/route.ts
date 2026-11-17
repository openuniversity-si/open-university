import { currentEnv } from "@/kernel/env.ts";
import { courseBySlug, lessonBySlug } from "@/catalog/domain/queries.ts";
import { readPreviewPage } from "@/app/catalog-preview";
import { resolveAuthBaseURL } from "@/identity/domain/settings.ts";
import { getVerifiedSession } from "@/identity/server/session.ts";
import { PRODUCTION_ORIGIN } from "@/site/domain/origin";
import { handleProgressPost } from "@/progress/server/handler";

export const dynamic = "force-dynamic";

export function POST(request: Request): Promise<Response> {
  return handleProgressPost(request, {
    expectedOrigin: () => resolveAuthBaseURL(currentEnv().AUTH_URL, PRODUCTION_ORIGIN),
    userId: async (headers) => (await getVerifiedSession(headers))?.user.id ?? null,
    resolvePublishedLesson: async (courseSlug, lessonSlug) => {
      const catalog = await readPreviewPage({ kind: "course", slug: courseSlug });
      const course = courseBySlug(catalog, courseSlug);
      const lesson = course ? lessonBySlug(catalog, course.id, lessonSlug) : undefined;
      return course && lesson ? { courseId: course.id, lessonId: lesson.id, durationSeconds: lesson.durationSeconds } : null;
    },
  });
}
