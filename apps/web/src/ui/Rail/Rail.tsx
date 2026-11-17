import type { ReactNode } from "react";
import { RailHeader } from "@/ui/RailHeader/RailHeader";
import styles from "./Rail.module.css";

interface RailProps {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
  readonly context?: "home" | "course";
  /** Trailing header link (Universities: "See all N", ADR-25). */
  readonly action?: ReactNode;
}

/** Spec 01: fixed-size cards, horizontal scrolling, and a trailing page gutter. */
export function Rail({ id, title, children, context = "home", action }: RailProps) {
  return (
    <section className={styles.rail} aria-labelledby={id} data-testid={`rail-${id}`} data-context={context}>
      <div className={styles.header} data-action={action ? "true" : undefined}><RailHeader id={id}>{title}</RailHeader>{action}</div>
      <div className={styles.row} data-testid={`rail-row-${id}`}><div className={styles.cards}>{children}</div></div>
    </section>
  );
}
