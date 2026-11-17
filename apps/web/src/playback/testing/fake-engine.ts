import { CorePlaybackEngine, type LessonIdentity, type MediaEvent } from "../domain/engine.ts";
import type { PlaybackTransport } from "../ports/engine.ts";
import type { PlaybackEngineModule } from "../domain/types.ts";

/** No media URLs, timers or network. Tests explicitly deliver events, including stale ones. */
export class FakeEngine extends CorePlaybackEngine {
  readonly starts: number[];
  readonly seeks: number[];
  readonly tokens: string[] = [];
  private readonly callbacks: Map<number, { emit: (event: MediaEvent, attempt: number) => void; time: (seconds: number, attempt: number) => void }>;
  constructor(lesson: LessonIdentity, now = Date.now) {
    const starts: number[] = []; const seeks: number[] = [];
    const callbacks = new Map<number, { emit: (event: MediaEvent, attempt: number) => void; time: (seconds: number, attempt: number) => void }>();
    const transport: PlaybackTransport = {
      start(attempt, emit, time) { starts.push(attempt); callbacks.set(attempt, { emit, time }); },
      pause() {}, seek(seconds) { seeks.push(seconds); }, dispose() { callbacks.clear(); },
    };
    super(transport, lesson, now); this.starts = starts; this.seeks = seeks; this.callbacks = callbacks;
  }
  emit(event: MediaEvent, attempt = this.starts.at(-1)): void {
    if (attempt !== undefined) this.callbacks.get(attempt)?.emit(event, attempt);
  }
  time(seconds: number, attempt = this.starts.at(-1)): void {
    if (attempt !== undefined) this.callbacks.get(attempt)?.time(seconds, attempt);
  }
}

declare global {
  /** Test build only: e2e drives the engines the Player opened, oldest first. */
  var __towerFakePlayback: FakeEngine[] | undefined;
}

export const playbackEngine = {
  id: "tower-playback-engine:fake" as const,
  open(lesson: LessonIdentity) {
    const engine = new FakeEngine(lesson);
    (globalThis.__towerFakePlayback ??= []).push(engine);
    return { engine, attach() {}, prepare() {}, setToken(token: string) { engine.tokens.push(token); } };
  },
} satisfies PlaybackEngineModule;
