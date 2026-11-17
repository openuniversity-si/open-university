import type { CSSProperties, ReactNode } from "react";
import { preconnect } from "react-dom";
import type { BillboardView } from "@/catalog/domain/view-model";
import { courseDetailsLabel, metaGap, resumeLabel, startLabel } from "@/site/domain/reader-copy.ts";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";
import { towerBreakpointDesktop } from "@/ui/tokens/values";
import styles from "./Billboard.module.css";
import { billboardMeta, withResume } from "./meta";

interface BillboardProps {
  readonly course: BillboardView;
  readonly selected?: boolean;
  readonly context?: "home" | "course";
  /** Course page of a course with editions: the meta of each edition, one shown at a time (ADR-21). */
  readonly meta?: { readonly mobile: ReactNode; readonly desktop: ReactNode };
  /** Universities (ADR-25): one CTA of its own ("Open MIT") instead of Start + Course details. */
  readonly primary?: { readonly href: string; readonly label: string };
  /** Rendered above the kicker (Universities: "‹ Universities"). */
  readonly back?: ReactNode;
}

/** Same breakpoint as the desktop rules of Billboard.module.css (TOWER_LAYOUT.breakpoints.desktop). */
const HERO_DESKTOP_MEDIA = `(width >= ${towerBreakpointDesktop})`;

/** Billboard 23:65: Spec 09 art crop, with its own scrims; CoverGlass is exclusive to cards. */
export function Billboard({ course, selected = false, context = "home", meta: editionMeta, primary, back }: BillboardProps) {
  const identity = [[1, 0, 0], [0, 1, 0]] as const;
  const mobileTransform = course.assets.heroMobile?.transform ?? identity;
  const desktopTransform = course.assets.heroDesktop?.transform ?? identity;

  const crop = {
    "--tower-hero-art-width-mobile": `${String(100 / mobileTransform[0][0])}%`,
    "--tower-hero-art-width-desktop": `${String(100 / desktopTransform[0][0])}%`,
    "--tower-hero-art-x": `${String(-100 * desktopTransform[0][2])}%`,
    "--tower-hero-art-y": `${String(-100 * desktopTransform[1][2])}%`,
    "--tower-hero-art-x-mobile": `${String(-100 * mobileTransform[0][2])}%`,
    "--tower-hero-art-y-mobile": `${String(-100 * mobileTransform[1][2])}%`,
  } as CSSProperties;
  const meta = editionMeta ?? (context === "course" ? { mobile: withResume(course, course.metaMobile), desktop: course.meta } : billboardMeta(course, selected));
  const cta = course.progress?.cta;
  // One <picture>: the browser downloads only the hero of the current viewport (both were preloaded before).
  const { heroDesktop: desktop, heroMobile: mobile } = course.assets;
  const art = mobile ?? desktop;
  // The hero is the Home's LCP (P8-BASELINE): open the media host's connection while the HTML is still parsing.
  if (art && URL.canParse(art.url)) preconnect(new URL(art.url).origin);
  return (
    <section className={styles.billboard} data-testid="tower-billboard" data-selected={selected} data-context={context} data-resume={cta?.kind === "resume"} aria-labelledby="billboard-title" style={crop}>
      <div className={styles.image} aria-hidden="true" data-testid="tower-billboard-media" data-cover-placeholder={art ? undefined : "true"}>
        {art ? (
          <picture>
            {desktop && desktop !== art ? <source media={HERO_DESKTOP_MEDIA} srcSet={desktop.url} width={desktop.width} height={desktop.height} /> : null}
            <img className={styles.art} src={art.url} width={art.width} height={art.height} alt="" fetchPriority="high" />
          </picture>
        ) : null}
        <span className={styles["scrim-left"]} />
        <span className={styles["scrim-bottom"]} data-testid="tower-billboard-scrim" />
      </div>
      {back ? <div className={styles.back}>{back}</div> : null}
      <div className={styles.content} data-testid="tower-billboard-text">
        <p className={styles.kicker}>{course.author}</p>
        <h1 id="billboard-title" className={styles.title}>{course.displayTitle}</h1>
        <p className={styles.meta}><span className={styles.mobile}>{meta.mobile}</span><span className={styles.desktop}>{meta.desktop}</span></p>
        <p className={styles.description}><span className={styles.mobile}>{course.billboardDescriptionMobile}</span><span className={styles.desktop}>{course.billboardDescription}</span></p>
        <div className={styles.actions}>
          {primary ? <PrimaryCTA href={primary.href} play prefetch={false}>{primary.label}</PrimaryCTA> : <>
          <PrimaryCTA href={cta?.href ?? course.startHref} play prefetch={false}>
            {cta?.kind === "resume" ? <><span className={styles.mobile}>{resumeLabel}</span><span className={styles.desktop}>{resumeLabel}{metaGap}{cta.lesson}</span></> : startLabel}
          </PrimaryCTA>
          {context === "home" ? <PrimaryCTA href={`/c/${course.slug}`} kind="secondary" arrow prefetch={false}>{courseDetailsLabel}</PrimaryCTA> : null}
          </>}
        </div>
      </div>
    </section>
  );
}
