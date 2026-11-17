import styles from "./CoverGlass.module.css";

/** CoverGlass 380:118, G3b Armored Hairline (Addendum 2.9). Cards only; never intercepts input. */
export function CoverGlass() {
  return <span className={styles.glass} aria-hidden="true" data-testid="tower-cover-glass"><span className={styles.laminate} /></span>;
}
