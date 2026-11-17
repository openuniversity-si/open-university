"use client";

import { signInCancelled, signInError, tryAgainLabel } from "@/site/domain/reader-copy.ts";
import { OverlayLayer } from "@/ui/OverlayLayer/OverlayLayer";
import styles from "./SignInFeedback.module.css";

interface SignInFeedbackProps {
  readonly kind: "error" | "cancelled";
  readonly onRetry?: () => void;
}

/** Presentational feedback only; F10 decides when to show it and handles retries. */
export function SignInFeedback({ kind, onRetry }: SignInFeedbackProps) {
  return (
    <OverlayLayer>
      <div className={["tower-glass tower-glass--regular tower-signin-feedback", styles.panel].join(" ")} data-testid="tower-signin-feedback" data-kind={kind} role="status">
        <p className={styles.message}>{kind === "error" ? signInError : signInCancelled}</p>
        <button className={["tower-signin-feedback__retry", styles.retry].join(" ")} type="button" onClick={onRetry}>{tryAgainLabel}</button>
      </div>
    </OverlayLayer>
  );
}
