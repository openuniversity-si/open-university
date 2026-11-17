"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/identity/client/AuthProvider";
import { completedLabel, markComplete } from "@/site/domain/reader-copy.ts";
import type { LessonIdentity } from "@/playback/domain/engine";
import { sendProgress } from "@/progress/client/client";
import styles from "./CompletionToggle.module.css";

/**
 * PlayerCompletionToggle 162:90. Signed in: optimistic, persisted through POST /api/progress, reverted when the
 * write fails. Signed out (D2): starts sign-in, paused, and queues nothing.
 */
export function CompletionToggle({ lesson, completed = false, signedIn = false }: {
  readonly lesson: LessonIdentity;
  /** Saved state at render (always false signed out, D1). */
  readonly completed?: boolean;
  /** The page was rendered for a session; `useAuth().viewer` takes over once it loads. */
  readonly signedIn?: boolean;
}) {
  const { viewer, startSignIn } = useAuth();
  const router = useRouter();
  const [saved, setSaved] = useState(completed);
  const [shown, setShown] = useState(completed);
  const [busy, setBusy] = useState(false);
  if (saved !== completed) { setSaved(completed); setShown(completed); }
  const checked = (viewer !== null || signedIn) && shown;
  return <button className={styles.toggle} type="button" aria-pressed={viewer !== null || signedIn ? checked : undefined} aria-busy={busy || undefined}
    data-testid="player-completion" data-completed={checked}
    onClick={() => {
      if (viewer === null && !signedIn) { void startSignIn(); return; }
      if (busy) return;
      const next = !shown;
      setShown(next); setBusy(true);
      void sendProgress({ ...lesson, completed: next }).then((ok) => {
        setBusy(false);
        if (!ok) { setShown(!next); return; }
        router.refresh();
      });
    }}>
    {checked
      ? <><svg viewBox="0 0 22 22" aria-hidden="true"><path d="M4.583 11.229 8.867 15.5l8.55-8.567" fill="none" stroke="currentColor" strokeWidth="var(--tower-el-mark-complete-stroke)" strokeLinecap="round" strokeLinejoin="round" /></svg><span>{completedLabel}</span></>
      : <><svg viewBox="0 0 22 22" aria-hidden="true"><path d="M11 4.583333v12.833334M4.583333 11h12.833334" fill="none" stroke="currentColor" strokeWidth="var(--tower-el-mark-open-stroke)" strokeLinecap="round" /></svg><span>{markComplete}</span></>}
  </button>;
}
