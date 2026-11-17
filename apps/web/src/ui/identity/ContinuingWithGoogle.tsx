"use client";

import { continuingWithGoogle } from "@/site/domain/reader-copy.ts";
import { OverlayLayer } from "@/ui/OverlayLayer/OverlayLayer";
import { useEffect, useRef } from "react";
import styles from "./ContinuingWithGoogle.module.css";

export function ContinuingWithGoogle() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const frame = requestAnimationFrame(() => { root.current?.focus({ preventScroll: true }); });
    const keydown = (event: KeyboardEvent) => { if (event.key === "Tab") event.preventDefault(); };
    document.addEventListener("keydown", keydown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", keydown);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, []);
  return <OverlayLayer><div ref={root} tabIndex={-1} className={styles.veil} data-testid="auth-continuing" role="status" aria-live="polite">
    <div className={styles.shade} aria-hidden="true" />
    <div className={styles.anchor}>
      <p className={["tower-glass tower-glass--liquid", styles.capsule].join(" ")} data-testid="auth-continuing-message">{continuingWithGoogle}</p>
    </div>
  </div></OverlayLayer>;
}
