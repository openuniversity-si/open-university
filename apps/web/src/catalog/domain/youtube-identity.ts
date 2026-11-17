import { z } from "zod";
import { invalid } from "../../kernel/errors.ts";

/**
 * A YouTube video is one lesson inside a course. Another course may reuse it as its own lesson,
 * with its own id, slug and position. Release compile, course bundles, bulk ship and the lesson
 * service share this key. The id pattern lives here; the player imports it.
 */
export const youtubeIdSchema = z.string().regex(/^[A-Za-z0-9_-]{11}$/);
/** Playlist id from a youtube.com URL, or null when the URL is not one. */
export function playlistIdOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (!/(^|\.)youtube\.com$/.test(parsed.hostname)) return null;
    const list = parsed.searchParams.get("list");
    return list && /^[A-Za-z0-9_-]{10,64}$/.test(list) ? list : null;
  } catch {
    return null;
  }
}

/** Playlist id, or the same rejection the import route already returns. */
export function playlistIdFromUrl(url: string): string {
  const playlistId = playlistIdOf(url);
  if (!playlistId) throw invalid("playlistUrl must be a youtube.com URL with a list= playlist id.");
  return playlistId;
}

export function youtubeWithinCourseKey(courseId: string, youtubeId: string): string {
  return `${courseId}/${youtubeId}`;
}

/** Second and later lessons that repeat a YouTube video inside one course. */
export function duplicateYoutubeIdsInCourse(lessons: readonly { readonly courseId: string; readonly youtubeId: string }[]): { courseId: string; youtubeId: string }[] {
  const seen = new Set<string>();
  const duplicates: { courseId: string; youtubeId: string }[] = [];
  for (const lesson of lessons) {
    const key = youtubeWithinCourseKey(lesson.courseId, lesson.youtubeId);
    if (seen.has(key)) duplicates.push({ courseId: lesson.courseId, youtubeId: lesson.youtubeId });
    else seen.add(key);
  }
  return duplicates;
}
