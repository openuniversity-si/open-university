"use client";

import { usePathname } from "next/navigation";
import { Fragment, useEffect, useRef } from "react";
import { useShellCopy } from "@/config/client/shell-copy.tsx";
import { legalLabel } from "@/site/domain/reader-copy.ts";
import { TowerMark } from "@/ui/TowerMark/TowerMark";
import { distanceToPageEnd, footerOpacity } from "./fade";
import styles from "./Footer.module.css";

/**
 * Footer 21:155 (Addendum 2.5): TowerMark and Privacy · Terms · Contact on every device. It fades from Hidden to Visible over the last 80 px of the page; with
 * `prefers-reduced-motion: reduce` it stays fully visible. Server HTML renders it visible.
 */
export function Footer({ links }: { readonly links: readonly { readonly label: string; readonly href: string }[] }) {
  const copy = useShellCopy();
  const footer = useRef<HTMLElement>(null);
  const inCourse = usePathname().startsWith("/c/");

  useEffect(() => {
    const element = footer.current;
    if (!element) return;
    if (inCourse) { element.style.opacity = "1"; return; }
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    const update = () => {
      frame = 0;
      const root = document.documentElement;
      const distance = distanceToPageEnd(root.scrollHeight, window.scrollY, window.innerHeight);
      element.style.opacity = String(footerOpacity(distance, motion.matches));
    };
    const schedule = () => {
      if (frame === 0) frame = window.requestAnimationFrame(update);
    };
    update();
    const resize = new ResizeObserver(schedule);
    resize.observe(document.body);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    motion.addEventListener("change", schedule);
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      resize.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      motion.removeEventListener("change", schedule);
    };
  }, [inCourse]);

  return (
    <>
      <footer ref={footer} className={styles.footer} data-context={inCourse ? "course" : "home"} data-testid="tower-footer">
        <span className={styles.brand} data-testid="tower-footer-brand">
          <TowerMark className={styles.mark} />
        </span>
        <nav className={styles.links} aria-label={copy.legalLabel ?? legalLabel} data-testid="tower-footer-links">
          {links.map((link, index) => (
            <Fragment key={link.href}>
              {index > 0 ? <span className={styles.separator} aria-hidden="true">·</span> : null}
              <a className={[styles.link, "t-ui-label-12-medium"].join(" ")} href={link.href}>
                {link.label}
              </a>
            </Fragment>
          ))}
        </nav>
      </footer>
      {inCourse ? null : <div className={styles.scrim} aria-hidden="true" data-testid="tower-bottom-fade" data-fidelity-fixed="" />}
    </>
  );
}
