import type { ProgressUpdate } from "../../progress/client/client.ts";
import type { LessonIdentity } from "../domain/engine.ts";
import type { PlaybackEngine } from "../ports/engine.ts";

/** A checkpoint every 15 s of played media; pause, hide, unmount and the end always report. */
export const CHECKPOINT_SECONDS = 15;
/** The server applies at most one checkpoint per 5 s per lesson; don't send faster than that. */
export const MIN_SEND_INTERVAL_MS = 5000;

export interface ProgressBridgeOptions {
  readonly lesson: LessonIdentity;
  /** `beacon` writes must survive the page going away (pagehide, navigation). Resolves false when nothing was saved. */
  readonly send: (update: ProgressUpdate, beacon: boolean) => Promise<boolean>;
  /** Signed out sends nothing. Read on every event, so signing out mid-lesson stops the writes. */
  readonly isSignedIn: () => boolean;
  readonly onCompleted?: () => void;
  readonly now?: () => number;
  /** Page lifecycle source; `window` in the browser. */
  readonly page?: Pick<Window, "addEventListener" | "removeEventListener"> & { readonly document: Pick<Document, "visibilityState"> };
}

/**
 * Turns engine events into progress writes. Nothing is reported before this tab plays: a tab that only
 * opened the lesson (or restored its saved position) never overwrites what another tab or device saved.
 */
export function bridgeProgress(engine: PlaybackEngine, options: ProgressBridgeOptions): () => void {
  const { lesson, send, isSignedIn, onCompleted, now = Date.now, page } = options;
  let played = false;
  let dirty = false;
  let lastSent = engine.position;
  let lastSentAt = -Infinity;

  const flush = (beacon: boolean, force: boolean) => {
    if (!dirty || !isSignedIn() || (!force && now() - lastSentAt < MIN_SEND_INTERVAL_MS)) return;
    const positionSeconds = Math.floor(engine.position);
    dirty = false; lastSent = positionSeconds; lastSentAt = now();
    void send({ ...lesson, positionSeconds }, beacon).then((saved) => { if (!saved) dirty = true; });
  };
  const unsubscribe = engine.subscribe((event) => {
    if (event.type === "state") {
      if (event.state === "loading" || event.state === "playing") played = true;
      if (event.state === "paused") flush(false, true);
    } else if (event.type === "time") {
      if (!played) return;
      dirty = true;
      if (engine.state === "playing" && Math.abs(event.seconds - lastSent) >= CHECKPOINT_SECONDS) flush(false, false);
    } else if (isSignedIn()) {
      dirty = false;
      void send({ ...lesson, completed: true }, false).then((saved) => { if (saved) onCompleted?.(); });
    }
  });
  const onHide = () => { if (page?.document.visibilityState === "hidden") flush(true, true); };
  const onPageHide = () => { flush(true, true); };
  page?.addEventListener("visibilitychange", onHide);
  page?.addEventListener("pagehide", onPageHide);
  return () => {
    page?.removeEventListener("visibilitychange", onHide);
    page?.removeEventListener("pagehide", onPageHide);
    unsubscribe();
    flush(true, true);
  };
}
