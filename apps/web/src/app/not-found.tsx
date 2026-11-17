import type { Metadata } from "next";
import { homeTitle, notFoundBody, notFoundKicker, notFoundTitle } from "@/site/domain/reader-copy.ts";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";
import styles from "./not-found.module.css";

/** Never indexed, and no canonical: the root layout's `index, follow` must not reach a 404 (ADR-14). */
export const metadata: Metadata = {
  title: notFoundTitle,
  robots: { index: false, follow: true },
};

/** ◆ 404 — Mobile 390 | Desktop 1920: kicker, h1, body and the PrimaryCTA "Home" (no play icon), centred; normal TopNav. */
export default function NotFound() {
  return (
    <div className={styles.page} data-testid="tower-not-found">
      <div className={styles.column} data-testid="tower-not-found-column">
        <p className={styles.kicker}>{notFoundKicker}</p>
        <h1 className={styles.title}>{notFoundTitle}</h1>
        <p className={styles.body}>{notFoundBody}</p>
        <div className={styles.action}><PrimaryCTA href="/">{homeTitle}</PrimaryCTA></div>
      </div>
    </div>
  );
}
