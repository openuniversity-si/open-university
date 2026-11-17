"use client";

import { useEffect, useRef } from "react";
import { viewLectures } from "@/site/domain/reader-copy.ts";
import styles from "./LecturesAnchor.module.css";

/** Same-page anchor: 300 ms ease-out, with reduced motion and focus support. */
export function LecturesAnchor() {
  const animation = useRef(0);
  useEffect(() => () => { cancelAnimationFrame(animation.current); }, []);
  return <a className={styles.anchor} href="#player-lectures" data-testid="player-view-lectures" onClick={(event) => {
    event.preventDefault();
    const rail = document.getElementById("player-lectures");
    if (!rail) return;
    cancelAnimationFrame(animation.current);
    const start = window.scrollY;
    const offset = window.innerWidth >= 1024 ? 80 : 56;
    const destination = Math.min(Math.max(0, start + rail.getBoundingClientRect().top - offset), Math.max(0, document.documentElement.scrollHeight - window.innerHeight));
    const finish = () => { window.scrollTo(0, destination); rail.focus({ preventScroll: true }); };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { finish(); return; }
    const began = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - began) / 300);
      window.scrollTo(0, start + (destination - start) * (1 - (1 - progress) ** 3));
      if (progress < 1) animation.current = requestAnimationFrame(step); else finish();
    };
    animation.current = requestAnimationFrame(step);
  }}><svg viewBox="0 0 22 22" aria-hidden="true"><path d="M4.033333 5.683333h13.933334v1.833334H4.033333zM4.033333 10.083333h13.933334v1.833334H4.033333zM4.033333 14.483333h13.933334v1.833334H4.033333z" fill="currentColor" /></svg><span>{viewLectures}</span></a>;
}
