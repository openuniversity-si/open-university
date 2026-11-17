import type React from "react";
import Link from "next/link";
import type { HomePortal } from "@/catalog/domain/home";
import { exploreLabel } from "@/site/domain/reader-copy.ts";
import { ChevronRightIcon } from "@/ui/icons/icons";
import { LazyPoster } from "@/ui/LazyPoster/LazyPoster";
import styles from "./HomePortals.module.css";

const cx = (...names: (string | undefined)[]): string => names.filter(Boolean).join(" ");

/**
 * Home "Portais" (Figma: Home 1920 562:55931, 1366 563:949, 390 563:57913 — section "Portals"). One glass portal per tab,
 * leading to /universities and /authors. The collage posters load lazily and at low priority: the Billboard hero stays the LCP.
 */
export function HomePortals({ portals }: { readonly portals: readonly HomePortal[] }) {
  if (portals.length === 0) return null;
  return (
    <section className={styles.section} aria-labelledby="home-portals-title" data-testid="tower-home-portals">
      <h2 id="home-portals-title" className={styles.title}>{exploreLabel}</h2>
      <div className={styles.cards}>
        {portals.map((portal) => (
          <Link key={portal.tab} href={portal.href} className={styles.portal} data-testid={`home-portal-${portal.tab}`} aria-label={`${portal.title}: ${portal.names.join(", ")}`}>
            <span className={styles.collage} aria-hidden="true" style={{ "--portal-covers": String(Math.max(1, portal.covers.length)) } as React.CSSProperties}>
              {portal.covers.map((cover, index) => cover.placeholder
                ? <span key={`${portal.tab}-placeholder-${String(index)}`} className={cx(styles.cover, styles.placeholder)} data-testid="home-portal-placeholder" />
                : <LazyPoster key={cover.url} className={cx(styles.cover, styles["cover-top"])} src={cover.url} width={cover.width} height={cover.height} />)}
            </span>
            {portal.more > 0 ? <span className={cx("tower-glass", "tower-glass--regular", styles.more)} aria-hidden="true" data-testid="home-portal-more">+{portal.more}</span> : null}
            <span className={styles.scrim} aria-hidden="true" />
            <span className={cx("tower-glass", "tower-glass--regular", styles.label)}>
              <span className={styles.text}>
                <span className={styles.name}>{portal.title}</span>
                <span className={cx(styles.sub, styles.wide)}>{portal.namesLabel}</span>
                <span className={cx(styles.sub, styles.narrow)}>{portal.countLabel}</span>
              </span>
              <span className={cx("tower-glass", "tower-glass--regular", styles.chevron)} aria-hidden="true"><ChevronRightIcon className={styles.icon} /></span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
