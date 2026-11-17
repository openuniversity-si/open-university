import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProgressUpdate } from "../../progress/client/client.ts";
import { captureSignedOutCompletion, sessionCompletionStore } from "./completion.ts";
import { playbackEngine } from "./youtube.ts";
import { bridgeProgress } from "./progress-bridge.ts";
import type { YouTubeApi, YouTubePlayerOptions } from "./youtube-engine.ts";

const lesson = { courseSlug: "genesis", lessonSlug: "iv" };
const gesture = { type: "click", isTrusted: true };
const flush = () => vi.advanceTimersByTimeAsync(0);
const PLAYING = 1; const PAUSED = 2; const ENDED = 0;
const START_AT = 3125;

let players: FakePlayer[] = [];
/** IFrame API player whose clock runs on the fake timers while it plays; state changes are fired by the test. */
class FakePlayer {
  state = -1; duration = 3600; private base: number; private since = 0;
  readonly iframe = { title: "", allow: "", referrerPolicy: "" };
  readonly playVideo = vi.fn(); readonly pauseVideo = vi.fn(); readonly destroy = vi.fn();
  readonly seekTo = vi.fn((seconds: number) => { this.base = seconds; this.since = Date.now(); });
  readonly options: YouTubePlayerOptions;
  constructor(_element: HTMLElement, options: YouTubePlayerOptions) { this.options = options; this.base = Number(options.playerVars.start); players.push(this); }
  getCurrentTime() { return this.state === PLAYING ? this.base + (Date.now() - this.since) / 1000 : this.base; }
  getDuration() { return this.duration; }
  getPlayerState() { return this.state; }
  getIframe() { return this.iframe as unknown as HTMLIFrameElement; }
  ready() { this.options.events.onReady(); }
  change(state: number) {
    this.base = this.getCurrentTime(); this.since = Date.now(); this.state = state;
    this.options.events.onStateChange({ data: state });
  }
}
const youtube: YouTubeApi = { Player: FakePlayer };
const player = () => {
  const found = players.at(-1);
  if (!found) throw new Error("No YT.Player was created.");
  return found;
};

/** Wired like PlayerFrame: the production engine module, resume seek, signed-out capture, then the bridge. */
function open(options: { signedIn?: boolean } = {}) {
  const sent: { update: ProgressUpdate; beacon: boolean; at: number }[] = [];
  const send = vi.fn((update: ProgressUpdate, beacon: boolean) => { sent.push({ update, beacon, at: Date.now() }); return Promise.resolve(true); });
  const values = new Map<string, string>();
  const store = sessionCompletionStore({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); }, removeItem: (key) => { values.delete(key); } });
  const document: { visibilityState: DocumentVisibilityState } = { visibilityState: "visible" };
  const lifecycle = Object.assign(new EventTarget(), { document });
  const onCompleted = vi.fn();
  const times: number[] = [];
  const isSignedIn = () => options.signedIn ?? true;

  const session = playbackEngine.open(lesson, { youtubeId: "Ifi5KkXig3s" });
  const { engine } = session;
  session.attach({ dataset: {}, replaceChildren: vi.fn() } as unknown as HTMLElement);
  engine.subscribe((event) => { if (event.type === "time") times.push(event.seconds); });
  engine.seek(START_AT);
  const stopCapture = captureSignedOutCompletion(engine, store, isSignedIn);
  const stopBridge = bridgeProgress(engine, { lesson, send, isSignedIn, onCompleted, now: Date.now, page: lifecycle });
  const close = () => { stopBridge(); stopCapture(); engine.dispose(); };
  return { engine, send, sent, store, lifecycle, onCompleted, times, close };
}
async function play(engine: ReturnType<typeof open>["engine"]) {
  engine.play(gesture); await flush();
  player().ready(); player().change(PLAYING);
}

beforeEach(() => {
  vi.useFakeTimers({ now: 1_000_000 }); players = [];
  vi.stubGlobal("YT", youtube);
  vi.stubGlobal("document", { createElement: () => ({}) });
  vi.stubGlobal("location", { origin: "https://thetower.test" });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("YouTube engine + progress bridge", () => {
  it("resumes at the saved second and reports nothing from a tab that only opened the lesson", async () => {
    const { engine, send, lifecycle, times, close } = open();
    lifecycle.dispatchEvent(new Event("pagehide"));
    lifecycle.document.visibilityState = "hidden"; lifecycle.dispatchEvent(new Event("visibilitychange"));
    expect(send).not.toHaveBeenCalled();

    await play(engine);
    expect(player().options.playerVars.start).toBe(START_AT);
    expect(player().seekTo).not.toHaveBeenCalled();
    expect(times[0]).toBe(START_AT);
    expect(Math.min(...times)).toBeGreaterThanOrEqual(START_AT);
    expect(send).not.toHaveBeenCalled();
    close();
  });

  it("checkpoints while playing, sends at once on pause and with a beacon on pagehide", async () => {
    const { engine, sent, lifecycle, close } = open();
    await play(engine);
    await vi.advanceTimersByTimeAsync(40_000);
    expect(engine.position).toBeGreaterThanOrEqual(START_AT + 39);
    expect(sent.map(({ update }) => update.positionSeconds)).toEqual([START_AT + 15, START_AT + 30]);
    expect(sent.every(({ beacon, update }) => !beacon && update.completed === undefined)).toBe(true);
    sent.slice(1).forEach(({ at }, index) => { expect(at - (sent[index]?.at ?? 0)).toBeGreaterThanOrEqual(5000); });

    player().change(PAUSED);
    expect(engine.state).toBe("paused");
    expect(sent.at(-1)).toMatchObject({ update: { ...lesson, positionSeconds: START_AT + 40 }, beacon: false });

    player().change(PLAYING);
    expect(engine.state).toBe("playing");
    await vi.advanceTimersByTimeAsync(3000);
    const before = sent.length;
    lifecycle.dispatchEvent(new Event("pagehide"));
    expect(sent).toHaveLength(before + 1);
    expect(sent.at(-1)).toMatchObject({ update: { positionSeconds: START_AT + 43 }, beacon: true });
    close();
  });

  it("reports completion when signed in", async () => {
    const { engine, send, store, onCompleted, close } = open();
    await play(engine);
    player().change(ENDED);
    expect(engine.state).toBe("ended");
    expect(send).toHaveBeenLastCalledWith({ ...lesson, completed: true }, false);
    await flush();
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(store.read()).toBeNull();
    close();
  });

  it("keeps a signed-out completion pending and sends nothing", async () => {
    const { engine, send, store, lifecycle, onCompleted, close } = open({ signedIn: false });
    await play(engine);
    await vi.advanceTimersByTimeAsync(20_000);
    player().change(ENDED);
    lifecycle.dispatchEvent(new Event("pagehide"));
    close(); await flush();
    expect(send).not.toHaveBeenCalled();
    expect(onCompleted).not.toHaveBeenCalled();
    expect(store.read()).toEqual({ ...lesson, endedAt: Date.now() });
  });

  it("follows a seek on YouTube's own scrubber and checkpoints from the new position", async () => {
    const { engine, sent, close } = open();
    await play(engine);
    await vi.advanceTimersByTimeAsync(16_000);
    expect(sent.map(({ update }) => update.positionSeconds)).toEqual([START_AT + 15]);

    // The viewer drags YouTube's scrubber: the engine learns the new position from the next tick.
    player().seekTo(START_AT + 600);
    await vi.advanceTimersByTimeAsync(250);
    expect(Math.floor(engine.position)).toBe(START_AT + 600);
    // Within 5 s of the last write; the next tick after the window sends it.
    expect(sent).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(3750);
    expect(sent.map(({ update }) => update.positionSeconds)).toEqual([START_AT + 15, START_AT + 604]);
    close();
  });

  it("flushes once when the lesson changes and leaves no timers or late events", async () => {
    const { engine, sent, lifecycle, times, close } = open();
    await play(engine);
    await vi.advanceTimersByTimeAsync(7000);
    expect(sent).toHaveLength(0);

    close();
    expect(sent).toEqual([{ update: { ...lesson, positionSeconds: START_AT + 7 }, beacon: true, at: Date.now() }]);
    expect(player().destroy).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    const seen = times.length;
    player().change(PLAYING); player().change(ENDED);
    lifecycle.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(sent).toHaveLength(1);
    expect(times).toHaveLength(seen);
  });
});
