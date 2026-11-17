import { CorePlaybackEngine, type LessonIdentity } from "../domain/engine.ts";
import { YouTubeTransport } from "./youtube-engine.ts";
import type { PlaybackEngineModule, PlaybackSource } from "../domain/types.ts";

/** Production engine: the core state machine over the YouTube embed. Nothing from YouTube loads before intent or a gesture. */
export const playbackEngine = {
  id: "tower-playback-engine:youtube" as const,
  open(lesson: LessonIdentity, source: PlaybackSource) {
    const transport = new YouTubeTransport(source);
    return {
      engine: new CorePlaybackEngine(transport, lesson),
      attach(host: HTMLElement | null) { transport.attach(host); },
      prepare() { transport.prepare().catch(() => { /* start() reports load failures as a retryable error. */ }); },
    };
  },
} satisfies PlaybackEngineModule;
