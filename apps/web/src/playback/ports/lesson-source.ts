import type { PlaybackSource } from "../domain/types.ts";

/** The source the lesson page hands the player. The provider field stays in the playback adapter. */
export function lessonPlaybackSource(lesson: { readonly youtubeId: string }): PlaybackSource {
  return { youtubeId: lesson.youtubeId };
}
