import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { playbackEngine } from "@tower/playback-engine";
import type { LessonIdentity, PlaybackState } from "@/playback/domain/engine";
import type { PlaybackEngine } from "@/playback/ports/engine";
import type { PlaybackSession, PlaybackSource } from "@/playback/domain/types";

export interface PlaybackSnapshot {
  readonly state: PlaybackState;
  /**
   * The embed is the picture from here on: the video played, or the play was handed to YouTube's own controls
   * (paused before it ever played). Until then the poster covers it.
   */
  readonly started: boolean;
}
type Gesture = Pick<Event, "isTrusted" | "type">;
const initial: PlaybackSnapshot = { state: "idle", started: false };

/** Owns one lesson's session; opened on mount and disposed on unmount, so late events from a previous lesson are dropped. */
class PlaybackStore {
  private session: PlaybackSession | null = null;
  private snapshot = initial;
  private readonly listeners = new Set<() => void>();
  private readonly lesson: LessonIdentity;
  private readonly source: PlaybackSource;
  private readonly startAt: number;
  private readonly extend: (engine: PlaybackEngine) => () => void;

  /** `startAt` (signed in: saved position or `?t=`) is where playback begins. */
  constructor(lesson: LessonIdentity, source: PlaybackSource, startAt: number, extend: (engine: PlaybackEngine) => () => void) {
    this.lesson = lesson; this.source = source; this.startAt = startAt; this.extend = extend;
  }
  readonly subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  readonly read = () => this.snapshot;
  readonly readServer = () => initial;
  private update(patch: Partial<PlaybackSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }
  open(host: HTMLElement | null): () => void {
    const session = playbackEngine.open(this.lesson, this.source);
    this.session = session; session.attach(host); this.update(initial);
    const unsubscribe = session.engine.subscribe((event) => {
      if (event.type === "state") this.update({ state: event.state, started: this.snapshot.started || event.state === "playing" || event.state === "paused" });
    });
    if (this.startAt > 0) session.engine.seek(this.startAt);
    const release = this.extend(session.engine);
    return () => { release(); unsubscribe(); session.engine.dispose(); if (this.session === session) this.session = null; };
  }
  prepare(): void { this.session?.prepare(); }
  /** The first play, and Try again (the transport rebuilds its player after an error, so that is a fresh start). */
  play(gesture: Gesture): void { this.session?.engine.play(gesture); }
  pause(): void { this.session?.engine.pause(); }
  currentSecond(fallback: number): number {
    const engine = this.session?.engine;
    return !engine || engine.state === "idle" ? fallback : Math.floor(engine.position);
  }
}

/** `extend` attaches per-session observers (progress bridge, signed-out completion) and returns their cleanup. */
export function usePlayback(lesson: LessonIdentity, source: PlaybackSource, startAt = 0, extend: (engine: PlaybackEngine) => () => void = () => () => {}) {
  const [store] = useState(() => new PlaybackStore(lesson, source, startAt, extend));
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => store.open(host.current), [store]);
  const snapshot = useSyncExternalStore(store.subscribe, store.read, store.readServer);
  return { store, snapshot, host };
}
