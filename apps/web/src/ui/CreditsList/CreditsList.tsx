import type { ImageCredit } from "@/catalog/domain/credits";
import { coverKindLabel } from "@/ui/showcase/shelf-sentences.ts";
import styles from "./CreditsList.module.css";

/** /credits rows: subject, photographer/source link, license link (Figma 629:4681). */
export function CreditsList({ credits }: { readonly credits: readonly ImageCredit[] }) {
  return (
    <ul className={styles.list} data-testid="image-credits">
      {credits.map((entry) => (
        <li key={`${entry.kind}-${entry.subject}`} className={styles.row} data-testid="image-credit" data-cover={entry.coverUrl}>
          <span className={styles.subject}><span className={styles.name}>{entry.subject}</span><span className={styles.kind}>{coverKindLabel(entry.kind)}</span></span>
          <a className={styles.link} href={entry.sourceUrl} rel="noopener noreferrer" target="_blank">{entry.credit}</a>
          {entry.licenseUrl ? <a className={styles.license} href={entry.licenseUrl} rel="noopener noreferrer license" target="_blank">{entry.license}</a> : <span className={styles.license}>{entry.license}</span>}
        </li>
      ))}
    </ul>
  );
}
