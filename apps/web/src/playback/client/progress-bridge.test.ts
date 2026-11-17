import { describe, expect, it, vi } from "vitest";
import type { ProgressUpdate } from "../../progress/client/client.ts";
import { CorePlaybackEngine } from "../domain/engine.ts";
import { YouTubeTransport, type YouTubePlayerOptions } from "./youtube-engine.ts";
import { bridgeProgress } from "./progress-bridge.ts";
import { FakeEngine } from "../testing/fake-engine.ts";

const lesson = { courseSlug: "genesis", lessonSlug: "iv" };
const gesture = { type: "click", isTrusted: true };
const flush = () => new Promise((resolve) => { setTimeout(resolve, 0); });

function page() {
  const document: { visibilityState: DocumentVisibilityState } = { visibilityState: "visible" };
  return Object.assign(new EventTarget(), { document });
}
function setup(options: { signedIn?: () => boolean; saved?: boolean } = {}) {
  let clock = 0;
  const sent: [ProgressUpdate, boolean][] = [];
  const send = vi.fn((update: ProgressUpdate, beacon: boolean) => { sent.push([update, beacon]); return Promise.resolve(options.saved ?? true); });
  const engine = new FakeEngine(lesson);
  const lifecycle = page();
  const onCompleted = vi.fn();
  const stop = bridgeProgress(engine, { lesson, send, isSignedIn: options.signedIn ?? (() => true), onCompleted, now: () => clock, page: lifecycle });
  return { engine, sent, send, lifecycle, onCompleted, stop, tick: (ms: number) => { clock += ms; } };
}

describe("bridgeProgress", () => {
  it("checkpoints every 15 s of playback, never faster than every 5 s", () => {
    const { engine, sent, tick } = setup();
    engine.play(gesture); engine.emit("playing");
    engine.time(10); expect(sent).toEqual([]);
    engine.time(15); expect(sent).toEqual([[{ ...lesson, positionSeconds: 15 }, false]]);
    tick(1000); engine.seek(100); expect(sent).toHaveLength(1);
    tick(5000); engine.time(101); expect(sent.at(-1)).toEqual([{ ...lesson, positionSeconds: 101 }, false]);
  });

  it("reports on pause and as a beacon on hide, pagehide and unmount, only when something changed", () => {
    const { engine, sent, lifecycle, stop } = setup();
    engine.play(gesture); engine.emit("playing"); engine.time(4);
    engine.pause(); expect(sent).toEqual([[{ ...lesson, positionSeconds: 4 }, false]]);
    lifecycle.document.visibilityState = "hidden"; lifecycle.dispatchEvent(new Event("visibilitychange")); expect(sent).toHaveLength(1);
    engine.seek(50); lifecycle.dispatchEvent(new Event("visibilitychange"));
    expect(sent.at(-1)).toEqual([{ ...lesson, positionSeconds: 50 }, true]);
    lifecycle.document.visibilityState = "visible"; engine.seek(60); lifecycle.dispatchEvent(new Event("visibilitychange")); expect(sent).toHaveLength(2);
    lifecycle.dispatchEvent(new Event("pagehide")); expect(sent.at(-1)).toEqual([{ ...lesson, positionSeconds: 60 }, true]);
    engine.seek(70); stop(); expect(sent.at(-1)).toEqual([{ ...lesson, positionSeconds: 70 }, true]);
    engine.seek(80); lifecycle.dispatchEvent(new Event("pagehide")); expect(sent).toHaveLength(4);
  });

  it("a tab that never played sends nothing, even after restoring the saved position", () => {
    const { engine, sent, lifecycle, stop } = setup();
    engine.seek(3134); lifecycle.dispatchEvent(new Event("pagehide")); stop();
    expect(sent).toEqual([]);
  });

  it("marks the lesson complete at the end and keeps unsaved checkpoints dirty", async () => {
    const failed = setup({ saved: false });
    failed.engine.play(gesture); failed.engine.emit("playing"); failed.engine.time(20); await flush();
    failed.engine.pause(); await flush();
    expect(failed.sent).toHaveLength(2);
    failed.engine.play(gesture); failed.engine.emit("playing"); failed.engine.emit("ended"); await flush();
    expect(failed.sent.at(-1)).toEqual([{ ...lesson, completed: true }, false]);
    expect(failed.onCompleted).not.toHaveBeenCalled();
    const saved = setup();
    saved.engine.play(gesture); saved.engine.emit("playing"); saved.engine.emit("ended"); await flush();
    expect(saved.onCompleted).toHaveBeenCalledOnce();
  });

  it("signed out sends nothing", () => {
    const { engine, send, stop } = setup({ signedIn: () => false });
    engine.play(gesture); engine.emit("playing"); engine.time(30); engine.pause(); engine.play(gesture); engine.emit("playing"); engine.emit("ended"); stop();
    expect(send).not.toHaveBeenCalled();
  });

  it("works over the real engine path (CorePlaybackEngine + YouTubeTransport, faked IFrame API)", async () => {
    let options: YouTubePlayerOptions | undefined;
    let time = 0;
    class Player {
      constructor(_element: HTMLElement, value: YouTubePlayerOptions) { options = value; }
      playVideo() { /* API event below acknowledges playback. */ }
      pauseVideo() { /* API event below acknowledges pause. */ }
      seekTo(seconds: number) { time = seconds; }
      getCurrentTime() { return time; }
      getDuration() { return 3200; }
      getPlayerState() { return 1; }
      getIframe() { return {} as HTMLIFrameElement; }
      destroy() { /* No network or DOM to release. */ }
    }
    vi.useFakeTimers();
    vi.stubGlobal("YT", { Player });
    vi.stubGlobal("document", { createElement: () => ({}) });
    vi.stubGlobal("location", { origin: "https://open-university.test" });
    const transport = new YouTubeTransport({ youtubeId: "video" });
    transport.attach({ replaceChildren() { /* Local fake host. */ } } as unknown as HTMLElement);
    const engine = new CorePlaybackEngine(transport, lesson);
    const sent: ProgressUpdate[] = [];
    const stop = bridgeProgress(engine, { lesson, send: (update) => { sent.push(update); return Promise.resolve(true); }, isSignedIn: () => true });
    try {
      engine.seek(3134);
      engine.play(gesture); await vi.advanceTimersByTimeAsync(0);
      expect(options).toBeDefined();
      options?.events.onReady();
      expect(options?.playerVars.start).toBe(3134);
      options?.events.onStateChange({ data: 1 });
      expect(engine.state).toBe("playing");
      time = 3150; await vi.advanceTimersByTimeAsync(250);
      expect(sent).toEqual([{ ...lesson, positionSeconds: 3150 }]);
      time = 3200;
      options?.events.onStateChange({ data: 2 });
      options?.events.onStateChange({ data: 0 });
      expect(sent.at(-1)).toEqual({ ...lesson, completed: true });
    } finally {
      stop(); engine.dispose(); vi.useRealTimers(); vi.unstubAllGlobals();
    }
  });
});
