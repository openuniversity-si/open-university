import type { ReactNode } from "react";
import styles from "./EmptyCatalog.module.css";

interface EmptyCatalogProps {
  readonly title: string;
  readonly body: string | null;
  readonly action?: ReactNode;
  /** `h1` when the panel is the page's subject (404/500, D6). */
  readonly headingLevel?: "h1" | "h2";
}

/** EmptyState / Catalog 293:14484. The caller passes the title and body; D6 reuses the composition for the error page. */
export function EmptyCatalog({ title, body, action, headingLevel = "h2" }: EmptyCatalogProps) {
  const Heading = headingLevel;
  return (
    <section className={styles.panel} data-testid="tower-empty-catalog">
      <Heading className={styles.title}>{title}</Heading>
      {body === null ? null : <p className={styles.body}>{body}</p>}
      {action === undefined ? null : <div className={styles.action}>{action}</div>}
    </section>
  );
}
