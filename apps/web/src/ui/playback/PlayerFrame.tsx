"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/identity/client/AuthProvider";
import { captureSignedOutCompletion, sessionCompletionStore } from "@/playback/client/completion";
import type { PlaybackEngine } from "@/playback/ports/engine";
import { bridgeProgress } from "@/playback/client/progress-bridge";
import { sendProgress } from "@/progress/client/client";
import type { PlaybackSource } from "@/playback/domain/types";
import { PlayButton, PlayerError, PlayerLoading } from "./PlayerControls";
import { usePlayback } from "./usePlayback";
import styles from "./PlayerFrame.module.css";

/**
 * Player (ADR-11, "nativo total"): the build's engine (the YouTube embed with YouTube's own controls in production,
 * FakeEngine in build:test) under the lesson's opaque poster. Ours: the glass play button over the poster (idle only),
 * the loading spinner and the error panel. Everything else (pause, seek, speed, captions, full screen, shortcuts) is
 * YouTube's. The poster covers the embed until it starts: the video plays, or the play is handed to YouTube's controls
 * (the engine pauses before it ever played); from then on the embed is the picture, also at the end.
 * Mount one per lesson (keyed by the page) so a lesson change disposes the previous session.
 */
export function PlayerFrame({ poster, second, startAt = 0, route, lesson, source }: {
  readonly poster: ReactNode;
  readonly second: number;
  /** Signed in only: the saved position (or `?t=`), played from. Signed out always starts at 0:00 (D1). */
  readonly startAt?: number;
  readonly route: string;
  readonly lesson: { readonly courseSlug: string; readonly lessonSlug: string };
  readonly source: PlaybackSource;
}) {
  const { registerPlayback, viewer } = useAuth();
  const router = useRouter();
  const signedIn = useRef(false);
  useEffect(() => { signedIn.current = viewer !== null; }, [viewer]);
  const { store, snapshot, host } = usePlayback(lesson, source, startAt, (engine: PlaybackEngine) => {
    const isSignedIn = () => signedIn.current;
    const stopCapture = captureSignedOutCompletion(engine, sessionCompletionStore(sessionStorage), isSignedIn);
    const stopBridge = bridgeProgress(engine, { lesson, isSignedIn, page: window, send: sendProgress, onCompleted: () => { router.refresh(); } });
    return () => { stopBridge(); stopCapture(); };
  });
  const { state, started } = snapshot;
  useEffect(() => registerPlayback({ currentSecond: () => store.currentSecond(second), pause: () => { store.pause(); }, returnRoute: route }), [registerPlayback, route, second, store]);
  return (
    <div className={styles.frame} data-testid="player-frame" data-state={state} data-started={started} data-requested-second={second}>
      <div className={styles.poster} data-testid="player-poster">{poster}</div>
      <div className={styles.media} ref={host} data-testid="player-media" />
      {state === "idle" ? <PlayButton onPlay={(event) => { store.play(event.nativeEvent); }} onIntent={() => { store.prepare(); }} />
        : state === "loading" ? <PlayerLoading />
          : state === "error" ? <PlayerError onRetry={(event) => { store.play(event.nativeEvent); }} /> : null}
    </div>
  );
}
