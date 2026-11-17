import { CorePlaybackEngine } from "../domain/engine.ts";
import { institutionalUrlDriver } from "../domain/drivers/institutional-url.ts";
import { youtubeSourceDriver } from "../domain/drivers/youtube.ts";
import type { MediaEvent } from "../domain/engine.ts";
import type { PlaybackTransport } from "../ports/engine.ts";
import type { SourceDriver } from "../ports/source-driver.ts";
import type { TransportBench } from "./transport-contract.ts";

export interface MemoryTransport extends TransportBench {
  readonly engine: CorePlaybackEngine;
}

/** A controllable transport. `start` is the only call that marks media as loaded; seek before that does not. */
export function createInMemoryPlaybackTransport(): TransportBench {
  let loaded = false;
  let disposed = 0;
  let emitEvent: ((event: MediaEvent, attempt: number) => void) | null = null;
  let closed = false;
  const transport: PlaybackTransport = {
    start(_attempt, emit) {
      loaded = true;
      emitEvent = emit;
    },
    pause() { /* The engine already moved to paused. */ },
    seek() { /* Position is recorded by the engine. Loading waits for start. */ },
    dispose() { disposed += 1; emitEvent = null; },
  };
  return {
    port: transport,
    reset() {
      if (closed) throw new Error("The in-memory transport is closed.");
      loaded = false;
      disposed = 0;
      emitEvent = null;
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    emit(event, attempt) { emitEvent?.(event, attempt); },
    started: () => loaded,
    disposeCount: () => disposed,
  };
}

/** The pure engine over the memory transport, for cases that want both. */
export function createInMemoryPlayback(lesson = { courseSlug: "course-ready", lessonSlug: "lesson-ready" }, now = () => 0): MemoryTransport {
  const transport = createInMemoryPlaybackTransport();
  return { ...transport, engine: new CorePlaybackEngine(transport.port, lesson, now) };
}

/** Both source drivers. They are pure and do not need a store. */
export function playbackDrivers(allowlist: readonly string[] = ["example.org"]): readonly SourceDriver[] {
  return [youtubeSourceDriver, institutionalUrlDriver(allowlist)];
}
