import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CorePlaybackEngine } from "../domain/engine.ts";
import { HANDOFF_MS, IFRAME_ALLOW, loadYouTubeApi, YouTubeTransport, type YouTubeApi, type YouTubePlayerOptions } from "./youtube-engine.ts";

const lesson = { courseSlug: "course", lessonSlug: "lesson" };
const gesture = { type: "click", isTrusted: true };
const flush = () => vi.advanceTimersByTimeAsync(0);
const PLAYING = 1; const PAUSED = 2; const ENDED = 0; const BUFFERING = 3;

let players: FakePlayer[] = [];
/** IFrame API player: commands are spies, events are fired by the test. */
class FakePlayer {
  state = -1; time = 0; duration = 600;
  readonly iframe = { title: "", allow: "", referrerPolicy: "" };
  readonly playVideo = vi.fn(); readonly pauseVideo = vi.fn(); readonly destroy = vi.fn();
  readonly seekTo = vi.fn((seconds: number) => { this.time = seconds; });
  readonly options: YouTubePlayerOptions;
  constructor(_element: HTMLElement, options: YouTubePlayerOptions) { this.options = options; players.push(this); }
  getCurrentTime() { return this.time; }
  getDuration() { return this.duration; }
  getPlayerState() { return this.state; }
  getIframe() { return this.iframe as unknown as HTMLIFrameElement; }
  ready() { this.options.events.onReady(); }
  change(state: number) { this.state = state; this.options.events.onStateChange({ data: state }); }
  fail(code: number) { this.options.events.onError({ data: code }); }
}
const youtube: YouTubeApi = { Player: FakePlayer };
const player = (index = -1) => {
  const found = players.at(index);
  if (!found) throw new Error("No YT.Player was created.");
  return found;
};

/** The real engine over the real transport and loader; only the global `YT` and the DOM host are faked. */
function open(load = loadYouTubeApi) {
  const host = { dataset: {} as DOMStringMap, replaceChildren: vi.fn() };
  const transport = new YouTubeTransport({ youtubeId: "Ifi5KkXig3s" }, load);
  transport.attach(host as unknown as HTMLElement);
  return { host, transport, engine: new CorePlaybackEngine(transport, lesson) };
}
async function playing(engine: CorePlaybackEngine) {
  engine.play(gesture); await flush();
  player().ready(); player().change(PLAYING);
}

beforeEach(() => {
  vi.useFakeTimers(); players = [];
  vi.stubGlobal("YT", youtube);
  vi.stubGlobal("document", { createElement: () => ({}) });
  vi.stubGlobal("location", { origin: "https://thetower.test" });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("YouTubeTransport", () => {
  it("creates one player with YouTube's own controls and keyboard, and maps its states", async () => {
    const { engine } = open();
    engine.play(gesture); await flush();
    expect(players).toHaveLength(1);
    expect(player().options).toMatchObject({ host: "https://www.youtube.com", videoId: "Ifi5KkXig3s",
      playerVars: { controls: 1, rel: 0, playsinline: 1, iv_load_policy: 3, origin: "https://thetower.test", start: 0 } });
    expect(Object.keys(player().options.playerVars)).not.toContain("disablekb"); expect(Object.keys(player().options.playerVars)).not.toContain("fs");
    expect(IFRAME_ALLOW).toContain("fullscreen");
    expect(player().iframe).toEqual({ title: "YouTube video player", allow: IFRAME_ALLOW, referrerPolicy: "strict-origin-when-cross-origin" });
    expect(player().playVideo).not.toHaveBeenCalled();
    player().ready(); expect(player().playVideo).toHaveBeenCalledTimes(1);
    player().change(BUFFERING); expect(engine.state).toBe("loading");
    player().change(PLAYING); expect(engine.state).toBe("playing");
    player().change(PAUSED); expect(engine.state).toBe("paused");
    engine.play(gesture); expect(player().playVideo).toHaveBeenCalledTimes(2); expect(players).toHaveLength(1);
    player().change(PLAYING); expect(engine.state).toBe("playing");
  });

  /**
   * Guardian (2026-10-11): the embed must NOT use youtube-nocookie.com. On Opera Android the nocookie host stops audio
   * when the screen locks or the tab is hidden (plain iframe and IFrame API alike), while www.youtube.com keeps playing
   * in the background like every other site. Do not "improve privacy" by switching it back.
   */
  it("embeds from the standard YouTube host, never youtube-nocookie.com (background play on Opera Android)", async () => {
    const { engine } = open();
    engine.play(gesture); await flush();
    const { host } = player().options;
    expect(new URL(host).hostname).toBe("www.youtube.com");
    expect(host).not.toContain("nocookie");
  });

  it("reports the end as ended, never as a pause first", async () => {
    const { engine } = open();
    const ended = vi.fn(); engine.subscribe((event) => { if (event.type === "ended") ended(); });
    await playing(engine);
    player().time = 600; player().change(PAUSED); expect(engine.state).toBe("playing");
    player().change(ENDED); expect(engine.state).toBe("ended"); expect(ended).toHaveBeenCalledTimes(1);
  });

  it("surfaces player errors and rebuilds the player on Try again", async () => {
    const { engine } = open();
    await playing(engine);
    player().fail(150); expect(engine.state).toBe("error");
    engine.play(gesture); await flush();
    expect(player(0).destroy).toHaveBeenCalledTimes(1); expect(players).toHaveLength(2);
    player().ready(); player().change(PLAYING); expect(engine.state).toBe("playing");
  });

  it("reports time every 250 ms while playing, once after a seek, and stops when paused", async () => {
    const { engine } = open();
    await playing(engine);
    player().time = 12; await vi.advanceTimersByTimeAsync(250); expect(engine.position).toBe(12);
    player().seekTo.mockImplementationOnce(() => { player().time = 99; });
    engine.seek(100); expect(player().seekTo).toHaveBeenCalledWith(100, true); expect(engine.position).toBe(99);
    engine.pause(); expect(player().pauseVideo).toHaveBeenCalledTimes(1);
    player().time = 140; await vi.advanceTimersByTimeAsync(1000); expect(engine.position).toBe(99);
  });

  it("never loads YouTube for a seek before the first start, and starts the player there", async () => {
    const load = vi.fn(loadYouTubeApi);
    const { engine } = open(load);
    engine.seek(42.7);
    expect(load).not.toHaveBeenCalled(); expect(players).toHaveLength(0);
    engine.play(gesture); await flush();
    expect(player().options.playerVars.start).toBe(42);
  });

  it("drops events for an older attempt", async () => {
    const { transport } = open();
    const first = vi.fn(); const second = vi.fn(); const time = vi.fn();
    transport.start(1, first, time); transport.pause(); await flush();
    expect(players).toHaveLength(0);
    transport.start(3, second, time); await flush();
    player().ready(); player().change(PLAYING);
    expect(first).not.toHaveBeenCalled(); expect(second).toHaveBeenCalledWith("playing", 3);
  });

  it("destroys the player and clears its timers on dispose", async () => {
    const { engine, host } = open();
    await playing(engine);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    engine.dispose();
    expect(player().destroy).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0); expect(host.replaceChildren).toHaveBeenLastCalledWith();
  });

  it("hands the play to YouTube's controls when it isn't playing 3 s after playVideo(), without stopping the video", async () => {
    const { engine } = open();
    engine.play(gesture); await flush(); player().ready();
    await vi.advanceTimersByTimeAsync(HANDOFF_MS - 1); expect(engine.state).toBe("loading");
    await vi.advanceTimersByTimeAsync(1);
    expect(engine.state).toBe("paused"); expect(player().pauseVideo).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
    const quick = open();
    await playing(quick.engine); await vi.advanceTimersByTimeAsync(HANDOFF_MS);
    expect(quick.engine.state).toBe("playing");
  });

  it("lets a slow start carry on after the handoff and adopts it when it plays", async () => {
    const { engine } = open();
    engine.play(gesture); await flush(); player().ready(); player().change(BUFFERING);
    await vi.advanceTimersByTimeAsync(HANDOFF_MS); expect(engine.state).toBe("paused");
    player().time = 3; player().change(PLAYING);
    expect(engine.state).toBe("playing"); expect(engine.position).toBe(3); expect(player().pauseVideo).not.toHaveBeenCalled();
  });

  it("adopts plays and follows pauses made on YouTube's controls (handoff, native pause, our pause, replay)", async () => {
    const { engine } = open();
    const states: string[] = []; engine.subscribe((event) => { if (event.type === "state") states.push(event.state); });
    engine.play(gesture); await flush(); player().ready();
    await vi.advanceTimersByTimeAsync(HANDOFF_MS);
    player().time = 42; player().change(PLAYING);
    expect(engine.state).toBe("playing"); expect(engine.position).toBe(42);
    player().time = 43; await vi.advanceTimersByTimeAsync(250); expect(engine.position).toBe(43);
    player().change(PAUSED); expect(engine.state).toBe("paused"); expect(player().pauseVideo).not.toHaveBeenCalled();
    player().change(PLAYING); expect(engine.state).toBe("playing");
    engine.pause(); player().change(PAUSED); expect(engine.state).toBe("paused");
    player().change(PLAYING); expect(engine.state).toBe("playing");
    player().change(ENDED); expect(engine.state).toBe("ended");
    player().time = 0; player().change(PLAYING); expect(engine.state).toBe("playing"); expect(engine.position).toBe(0);
    expect(states).toEqual(["loading", "paused", "loading", "playing", "paused", "loading", "playing", "paused", "loading", "playing", "ended", "loading", "playing"]);
    expect(players).toHaveLength(1); expect(player().playVideo).toHaveBeenCalledTimes(5);
  });
});

describe("loadYouTubeApi", () => {
  it("injects the IFrame API script once and chains an existing ready callback", async () => {
    vi.resetModules(); vi.stubGlobal("YT", undefined);
    const append = vi.fn(); const previous = vi.fn();
    vi.stubGlobal("document", { createElement: () => ({}), head: { append } });
    vi.stubGlobal("onYouTubeIframeAPIReady", previous);
    const { loadYouTubeApi: load } = await import("./youtube-engine.ts");
    const first = load(); const second = load();
    expect(first).toBe(second); expect(append).toHaveBeenCalledTimes(1);
    expect(append).toHaveBeenCalledWith(expect.objectContaining({ src: "https://www.youtube.com/iframe_api" }));
    vi.stubGlobal("YT", youtube); globalThis.onYouTubeIframeAPIReady?.();
    await expect(first).resolves.toBe(youtube); expect(previous).toHaveBeenCalledTimes(1);
  });
});
