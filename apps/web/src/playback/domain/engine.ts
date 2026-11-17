export type PlaybackState = "idle" | "loading" | "playing" | "paused" | "ended" | "error";
export type MediaEvent = "playing" | "paused" | "ended" | "error";
export interface LessonIdentity { courseSlug: string; lessonSlug: string }
export interface Completion extends LessonIdentity { endedAt: number }
export type PlaybackEvent = { type: "state"; state: PlaybackState } | { type: "ended"; completion: Completion } | { type: "time"; seconds: number };

export interface PlaybackTransport {
  /** `time` reports media position for the same attempt; stale attempts are dropped like other events. */
  start(attempt: number, emit: (event: MediaEvent, attempt: number) => void, time: (seconds: number, attempt: number) => void): void;
  pause(): void;
  /** Before the first start this only records the position; it must never load media. */
  seek?(seconds: number): void;
  /**
   * Playback the viewer started with the provider's own controls (YouTube's play, replay or keyboard), outside `play(gesture)`.
   * That tap is the gesture, so the engine adopts it as a new attempt without the gesture gate.
   */
  onExternalPlay?(listener: () => void): void;
  dispose(): void;
}

export interface PlaybackEngine {
  readonly state: PlaybackState;
  readonly position: number;
  play(gesture: Pick<Event, "isTrusted" | "type">): boolean;
  pause(): void;
  seek(seconds: number): void;
  subscribe(listener: (event: PlaybackEvent) => void): () => void;
  dispose(): void;
}

/** Each play/retry owns an epoch. Pausing, disposal and terminal events invalidate it. */
export class CorePlaybackEngine implements PlaybackEngine {
  private current: PlaybackState = "idle";
  private seconds = 0;
  private attempt = 0;
  private disposed = false;
  private readonly listeners = new Set<(event: PlaybackEvent) => void>();
  private readonly transport: PlaybackTransport;
  private readonly lesson: LessonIdentity;
  private readonly now: () => number;

  constructor(transport: PlaybackTransport, lesson: LessonIdentity, now = Date.now) {
    this.transport = transport; this.lesson = lesson; this.now = now;
    transport.onExternalPlay?.(() => { if (this.current !== "playing" && this.current !== "loading") this.begin(); });
  }
  get state(): PlaybackState { return this.current; }
  get position(): number { return this.seconds; }
  subscribe(listener: (event: PlaybackEvent) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
  private publish(event: PlaybackEvent): void {
    for (const listener of this.listeners) listener(event);
  }
  private transition(state: PlaybackState): void {
    this.current = state; this.publish({ type: "state", state });
  }
  play(gesture: Pick<Event, "isTrusted" | "type">): boolean {
    if (this.disposed || !gesture.isTrusted || !["click", "pointerup", "keydown"].includes(gesture.type) || this.current === "playing" || this.current === "loading") return false;
    this.begin();
    return true;
  }
  private begin(): void {
    if (this.disposed) return;
    const attempt = ++this.attempt;
    this.transition("loading");
    if (attempt !== this.attempt) return;
    try { this.transport.start(attempt, (event, epoch) => { this.receive(event, epoch); }, (seconds, epoch) => { if (epoch === this.attempt) this.moveTo(seconds); }); }
    catch { this.receive("error", attempt); }
  }
  private receive(event: MediaEvent, attempt: number): void {
    if (this.disposed || attempt !== this.attempt) return;
    if (event === "playing" && this.current === "loading") this.transition("playing");
    // The media already stopped (the viewer's native pause, or the transport handing over), so it isn't paused again.
    else if (event === "paused" && (this.current === "playing" || this.current === "loading")) { ++this.attempt; this.transition("paused"); }
    else if (event === "error" && (this.current === "loading" || this.current === "playing")) {
      ++this.attempt; this.transition("error");
    } else if (event === "ended" && this.current === "playing") {
      ++this.attempt;
      const completion = { ...this.lesson, endedAt: this.now() };
      this.transition("ended"); this.publish({ type: "ended", completion });
    }
  }
  seek(seconds: number): void {
    if (this.disposed || this.current === "error" || !this.moveTo(seconds)) return;
    try { this.transport.seek?.(this.seconds); } catch { /* The next start begins from the recorded position. */ }
  }
  private moveTo(seconds: number): boolean {
    if (this.disposed || !Number.isFinite(seconds)) return false;
    this.seconds = Math.max(0, seconds); this.publish({ type: "time", seconds: this.seconds });
    return true;
  }
  pause(): void {
    if (this.disposed || (this.current !== "playing" && this.current !== "loading")) return;
    ++this.attempt; this.transition("paused");
    try { this.transport.pause(); } catch { this.transition("error"); }
  }
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true; ++this.attempt; this.listeners.clear(); this.transport.dispose();
  }
}
