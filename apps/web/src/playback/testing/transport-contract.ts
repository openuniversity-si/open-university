import { expect } from "vitest";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import { CorePlaybackEngine } from "../domain/engine.ts";
import { institutionalUrlDriver } from "../domain/drivers/institutional-url.ts";
import { youtubeSourceDriver } from "../domain/drivers/youtube.ts";
import type { MediaEvent } from "../domain/engine.ts";
import type { PlaybackTransport } from "../ports/engine.ts";

export interface TransportBench {
  readonly port: PlaybackTransport;
  reset(): Promise<void>;
  dispose(): Promise<void>;
  emit(event: MediaEvent, attempt: number): void;
  started(): boolean;
  disposeCount(): number;
}

const gesture = { isTrusted: true, type: "click" } as const;
const lesson = { courseSlug: "course-ready", lessonSlug: "lesson-ready" };

/** Transport attempts, seek-before-load, disposal and the two source drivers. No video is loaded. */
export function transportContract(): ContractSuite<TransportBench> {
  return {
    portId: "PlaybackTransport",
    cases: [
      { id: "playback.transport.stale", run(harness) {
        const engine = new CorePlaybackEngine(harness.port, lesson, () => 0);
        expect(engine.play(gesture)).toBe(true);
        harness.emit("playing", 1);
        expect(engine.state).toBe("playing");
        engine.pause();
        harness.emit("playing", 1);
        expect(engine.state).toBe("paused");
        engine.dispose();
        return Promise.resolve();
      } },
      { id: "playback.transport.seek", run(harness) {
        const engine = new CorePlaybackEngine(harness.port, lesson, () => 0);
        engine.seek(12);
        expect(harness.started()).toBe(false);
        expect(engine.position).toBe(12);
        engine.dispose();
        return Promise.resolve();
      } },
      { id: "playback.transport.dispose", run(harness) {
        const engine = new CorePlaybackEngine(harness.port, lesson, () => 0);
        engine.dispose();
        engine.dispose();
        expect(harness.disposeCount()).toBe(1);
        return Promise.resolve();
      } },
      { id: "playback.driver.youtube", run() {
        expect(youtubeSourceDriver.validateSource({ provider: "youtube", videoId: "abcdefghijk" })).toEqual([]);
        expect(youtubeSourceDriver.toPlaybackDescriptor({ provider: "youtube", videoId: "abcdefghijk" })).toEqual({ kind: "youtube", videoId: "abcdefghijk" });
        expect(youtubeSourceDriver.validateSource({ provider: "youtube", videoId: "short" })).toEqual(["videoId"]);
        return Promise.resolve();
      } },
      { id: "playback.driver.institutional", run() {
        const driver = institutionalUrlDriver(["example.org"]);
        expect(driver.cspDomains).toEqual({ scriptSrc: [], frameSrc: [], mediaSrc: [], imgSrc: [], connectSrc: [] });
        expect(driver.validateSource({ provider: "institutional-url", url: "https://example.org/lecture" })).toEqual([]);
        expect(driver.toPlaybackDescriptor({ provider: "institutional-url", url: "https://example.org/lecture" })).toEqual({ kind: "external-link", url: "https://example.org/lecture" });
        expect(driver.validateSource({ provider: "institutional-url", url: "https://other.example/lecture" })).toEqual(["url"]);
        return Promise.resolve();
      } },
    ],
  };
}
