import type { MediaEvent } from "../domain/engine.ts";
import type { PlaybackTransport } from "../ports/engine.ts";
import type { PlaybackSource } from "../domain/types.ts";

type Emit = (event: MediaEvent, attempt: number) => void;
type Time = (seconds: number, attempt: number) => void;
interface Attempt { attempt: number; emit: Emit; time: Time }

/** The part of the IFrame Player API we use (developers.google.com/youtube/iframe_api_reference). */
export interface YouTubePlayer {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  getDuration(): number;
  getPlayerState(): number;
  getIframe(): HTMLIFrameElement;
  destroy(): void;
}
export interface YouTubePlayerOptions {
  host: string;
  videoId: string;
  width: string;
  height: string;
  playerVars: Record<string, string | number>;
  events: { onReady(): void; onStateChange(event: { data: number }): void; onError(event: { data: number }): void };
}
export interface YouTubeApi { Player: new (element: HTMLElement, options: YouTubePlayerOptions) => YouTubePlayer }

declare global {
  var YT: YouTubeApi | undefined;
  var onYouTubeIframeAPIReady: (() => void) | undefined;
}

const API_SRC = "https://www.youtube.com/iframe_api";
/**
 * The embed MUST load from the standard host. `youtube-nocookie.com` stops playing when the screen locks or the tab
 * is hidden (Opera Android, tested 2026-10-11 with a plain iframe and with the IFrame API); `www.youtube.com` keeps
 * playing audio like every other site. Locked by `youtube-engine.test.ts`; do not switch it back for privacy.
 */
const EMBED_HOST = "https://www.youtube.com";
/**
 * `compute-pressure`: the embed probes it, and Chrome Android logs a policy violation when the frame lacks it.
 * `fullscreen`: YouTube's own full-screen button; an `allow` list without it overrides the API's `allowfullscreen`.
 */
export const IFRAME_ALLOW = "accelerometer; autoplay; clipboard-write; compute-pressure; encrypted-media; fullscreen; gyroscope; picture-in-picture; web-share";
const ENDED = 0; const PLAYING = 1; const PAUSED = 2;
const TICK_MS = 250;
/**
 * A play that hasn't reached PLAYING this long after `playVideo()` is handed to YouTube's own controls: the engine
 * pauses (the poster lifts) without stopping the video. iOS refuses `playVideo()` from outside the iframe, so there
 * the viewer taps YouTube's play; a slow start simply carries on behind YouTube's spinner and is adopted when it plays.
 */
export const HANDOFF_MS = 3000;
/** YouTube can report a pause right before the end; within this margin only `ended` reaches the engine. */
const END_MARGIN_SECONDS = 0.5;

let api: Promise<YouTubeApi> | null = null;

/** Injects the IFrame API script once per page; a failed load can be retried. Chains any existing ready callback. */
export function loadYouTubeApi(): Promise<YouTubeApi> {
  api ??= new Promise<YouTubeApi>((resolve, reject) => {
    if (globalThis.YT?.Player) { resolve(globalThis.YT); return; }
    const previous = globalThis.onYouTubeIframeAPIReady;
    globalThis.onYouTubeIframeAPIReady = () => {
      previous?.();
      if (globalThis.YT) resolve(globalThis.YT);
    };
    const script = document.createElement("script");
    script.src = API_SRC; script.async = true;
    script.onerror = () => {
      api = null; globalThis.onYouTubeIframeAPIReady = previous; script.remove();
      reject(new Error("YouTube IFrame API failed to load"));
    };
    document.head.append(script);
  });
  return api;
}

/**
 * Production transport: the YouTube embed (www.youtube.com) with YouTube's own controls, created on the
 * first gesture inside our `.media` host. The Player only draws the poster and its first play button.
 * One YT.Player serves every attempt, so its events go to the current attempt only; pausing or a newer
 * start drops the older one, and a play started on YouTube's controls is adopted as a new attempt.
 * An error marks the player failed and the next start (Try again) rebuilds it.
 */
export class YouTubeTransport implements PlaybackTransport {
  private readonly videoId: string;
  private readonly load: () => Promise<YouTubeApi>;
  private host: HTMLElement | null = null;
  private player: YouTubePlayer | null = null;
  private ready = false;
  private failed = false;
  private seekOnReady = false;
  private startAt = 0;
  private external: (() => void) | undefined;
  private current: Attempt | null = null;
  private ticker: ReturnType<typeof setInterval> | undefined;
  private handoff: ReturnType<typeof setTimeout> | undefined;

  constructor(source: PlaybackSource, load: () => Promise<YouTubeApi> = loadYouTubeApi) {
    this.videoId = source.youtubeId; this.load = load;
  }

  attach(host: HTMLElement | null): void {
    if (host === this.host) return;
    this.unmount(); this.host = host;
  }

  /** Intent only: loads the API script, never a video. */
  prepare(): Promise<unknown> {
    return this.load();
  }

  start(attempt: number, emit: Emit, time: Time): void {
    if (this.failed) this.unmount();
    const current = { attempt, emit, time };
    this.current = current; clearTimeout(this.handoff);
    if (this.player) {
      if (this.ready) this.play();
      return;
    }
    this.load().then((youtube) => {
      if (this.current !== current) return;
      if (!this.host) { this.deliver("error"); return; }
      this.mount(youtube, this.host);
    }, () => { if (this.current === current) this.deliver("error"); });
  }

  pause(): void {
    this.current = null; this.stopTimers();
    if (this.ready) this.player?.pauseVideo();
  }

  seek(seconds: number): void {
    if (this.player && this.ready) { this.player.seekTo(seconds, true); this.report(); return; }
    this.startAt = seconds; this.seekOnReady = this.player !== null;
  }

  onExternalPlay(listener: () => void): void {
    this.external = listener;
  }

  dispose(): void {
    this.unmount(); this.host = null; this.external = undefined;
  }

  private mount(youtube: YouTubeApi, host: HTMLElement): void {
    const element = document.createElement("div");
    host.replaceChildren(element);
    try {
      const player = new youtube.Player(element, {
        host: EMBED_HOST, videoId: this.videoId, width: "100%", height: "100%",
        playerVars: { controls: 1, rel: 0, playsinline: 1, iv_load_policy: 3, origin: location.origin, start: Math.floor(this.startAt) },
        events: {
          onReady: () => { if (this.player === player) this.onReady(player); },
          onStateChange: ({ data }) => { if (this.player === player) this.onState(data); },
          onError: () => { if (this.player === player) { this.failed = true; this.stopTimers(); this.deliver("error"); } },
        },
      });
      this.player = player;
      const iframe = player.getIframe();
      iframe.title = "YouTube video player"; iframe.allow = IFRAME_ALLOW; iframe.referrerPolicy = "strict-origin-when-cross-origin";
    } catch {
      this.failed = true; this.deliver("error");
    }
  }

  private onReady(player: YouTubePlayer): void {
    this.ready = true;
    if (this.seekOnReady) { this.seekOnReady = false; player.seekTo(this.startAt, true); }
    if (this.current) this.play();
  }

  private play(): void {
    const player = this.player; const current = this.current;
    if (!player || !current) return;
    player.playVideo();
    if (player.getPlayerState() === PLAYING) { this.onState(PLAYING); return; }
    this.handoff = setTimeout(() => { if (this.current === current) this.deliver("paused"); }, HANDOFF_MS);
  }

  private onState(state: number): void {
    if (state === PLAYING) {
      // Nobody asked for this play: the viewer started it on YouTube's controls, so the engine adopts it.
      if (!this.current) { this.external?.(); return; }
      clearTimeout(this.handoff);
      clearInterval(this.ticker); this.ticker = setInterval(() => { this.report(); }, TICK_MS);
      this.report(); this.deliver("playing");
    } else if (state === PAUSED) {
      this.stopTimers();
      if (!this.nearEnd()) this.deliver("paused");
    } else if (state === ENDED) {
      this.stopTimers(); this.deliver("ended");
    }
  }

  private nearEnd(): boolean {
    const duration = this.player?.getDuration() ?? 0;
    return duration > 0 && (this.player?.getCurrentTime() ?? 0) >= duration - END_MARGIN_SECONDS;
  }

  private report(): void {
    const current = this.current;
    if (current && this.player) current.time(this.player.getCurrentTime(), current.attempt);
  }

  private deliver(event: MediaEvent): void {
    const current = this.current;
    if (!current) return;
    if (event !== "playing") this.current = null;
    current.emit(event, current.attempt);
  }

  private stopTimers(): void {
    clearInterval(this.ticker); clearTimeout(this.handoff);
    this.ticker = undefined; this.handoff = undefined;
  }

  private unmount(): void {
    this.current = null; this.stopTimers();
    if (!this.player) return;
    if (this.ready) this.startAt = this.player.getCurrentTime() || this.startAt;
    try { this.player.destroy(); } catch { /* The iframe may already be gone with its host. */ }
    this.player = null; this.ready = false; this.failed = false; this.seekOnReady = false;
    this.host?.replaceChildren();
  }
}
