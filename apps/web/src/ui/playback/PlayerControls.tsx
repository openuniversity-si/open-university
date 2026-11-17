import type { MouseEvent } from "react";
import { lectureUnavailable, loadingLecture, playLecture, tryAgainLabel } from "@/site/domain/reader-copy.ts";
import { PlayIcon } from "@/ui/icons/icons";
import styles from "./PlayerFrame.module.css";

/** Clear glass play button over the poster. 40 px, 24 px on mobile with a 44 px target. */
export function PlayButton({ onPlay, onIntent }: {
  readonly onPlay: (event: MouseEvent<HTMLButtonElement>) => void;
  readonly onIntent: () => void;
}) {
  return (
    <div className={styles.anchor}>
      <button className={`tower-glass tower-glass--clear tower-play ${styles.play ?? ""}`} type="button" aria-label={playLecture}
        data-testid="player-play" onClick={onPlay} onPointerEnter={onIntent} onPointerDown={onIntent} onFocus={onIntent}>
        <PlayIcon className={styles.nudge} />
      </button>
    </div>
  );
}

/** PlayerFrame State=Loading: spinner only, over the poster. */
export function PlayerLoading() {
  return (
    <div className={styles.loading} role="status" aria-label={loadingLecture} data-testid="player-loading">
      <svg viewBox="0 0 40 40" aria-hidden="true">
        <circle className={styles.ring} cx="20" cy="20" r="19" vectorEffect="non-scaling-stroke" />
        <circle className={styles.arc} cx="20" cy="20" r="19" pathLength="100" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

/** PlayerFrame State=Error: still kept under tower-veil-panel; Try again rebuilds the player and plays. */
export function PlayerError({ onRetry }: { readonly onRetry: (event: MouseEvent<HTMLButtonElement>) => void }) {
  return (
    <div className={styles.error} role="alert" data-testid="player-error">
      <p>{lectureUnavailable}</p>
      <button type="button" onClick={onRetry} data-testid="player-retry">{tryAgainLabel}</button>
    </div>
  );
}
