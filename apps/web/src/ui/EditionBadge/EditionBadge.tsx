import styles from "./EditionBadge.module.css";

/** EditionBadge 575:2024: the lesson's edition in the Player meta, for a course with more than one edition. */
export function EditionBadge({ label }: { readonly label: string }) {
  return <span className={styles.badge} data-testid="edition-badge">{label}</span>;
}
