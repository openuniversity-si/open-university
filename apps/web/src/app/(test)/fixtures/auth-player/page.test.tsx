"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth, useMarkComplete } from "@/identity/client/AuthProvider";

/** Shared F10 contracts exercised until the Player screen lands. No media element. */
export default function AuthPlayerFixture() {
  const [paused, setPaused] = useState(false);
  const { registerPlayback } = useAuth();
  const playback = useMemo(() => ({ currentSecond: () => 3134.9, pause: () => { setPaused(true); }, returnRoute: "/c/genesis/lecture-4?view=lecture#notes" }), []);
  useEffect(() => registerPlayback(playback), [registerPlayback, playback]);
  const markComplete = useMarkComplete(playback, { courseSlug: "genesis", lessonSlug: "lecture-4" });
  return <div style={{ paddingTop: 100 }}><button type="button" onClick={() => { void markComplete(); }}>Mark complete</button>
    <output data-testid="auth-player-state">{paused ? "Paused" : "Playing"}</output></div>;
}
