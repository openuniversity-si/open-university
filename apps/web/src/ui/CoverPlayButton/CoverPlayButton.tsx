import { PlayIcon } from "@/ui/icons/icons";
import styles from "./CoverPlayButton.module.css";

/** CoverPlayButton 504:53064: decorative clear-glass play centered on a selected cover; the card stays the link. */
export function CoverPlayButton() {
  return (
    <span className={styles.slot} aria-hidden="true" data-testid="tower-cover-play">
      <span className={`tower-glass tower-glass--clear ${styles.button ?? ""}`}>
        <PlayIcon className={styles.icon} />
      </span>
    </span>
  );
}
