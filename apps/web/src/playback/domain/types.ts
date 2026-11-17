import type { LessonIdentity } from "./engine.ts";
import type { PlaybackEngine } from "../ports/engine.ts";

/** `youtubeId` drives the production (YouTube) engine. */
export interface PlaybackSource {
  readonly youtubeId: string;
}

/** One lesson's playback, owned by the Player UI from mount to unmount. */
export interface PlaybackSession {
  readonly engine: PlaybackEngine;
  /** Element the engine may render media into after the first gesture. */
  attach(host: HTMLElement | null): void;
  /** Warms the engine code on intent (hover, focus, pointerdown). Never requests a video. */
  prepare(): void;
}

/**
 * Build-time seam for the video engine (ADR-11). `pnpm build` resolves
 * `@tower/playback-engine` to engine.ts; `pnpm build:test` resolves it to fake-engine.ts.
 */
export interface PlaybackEngineModule {
  /** Unique string; bundle:check uses it to prove which engine a build contains. */
  readonly id: "tower-playback-engine:youtube" | "tower-playback-engine:fake";
  open(lesson: LessonIdentity, source: PlaybackSource): PlaybackSession;
}
