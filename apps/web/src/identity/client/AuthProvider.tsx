"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { handoffPendingCompletion, sessionCompletionStore } from "@/playback/client/completion";
import { completionPersistence } from "@/playback/client/persistence";
import { consumeSignInFeedback } from "@/identity/client/return-to";
import { CACHE } from "@/kernel/cache.ts";
import { createSignInRequest, isSignInRedirect } from "@/identity/ports/sign-in";
import { saveReturnUI, takeReturnUI } from "@/identity/client/return-ui";

export type SignInFeedbackKind = "error" | "cancelled";
export interface AuthProviderSlots {
  /** Shown while `busy && !viewer`. */
  readonly busyOverlay: ComponentType;
  /** Shown when Google sign-in returns feedback. */
  readonly signInFeedback: ComponentType<{ readonly kind: SignInFeedbackKind; readonly onRetry: () => void }>;
}

interface Viewer { id: string; name: string }
export interface AuthPlaybackContext { currentSecond(): number; pause(): void; returnRoute?: string }
interface AuthContextValue {
  viewer: Viewer | null;
  busy: boolean;
  startSignIn: (playback?: AuthPlaybackContext) => Promise<void>;
  signOut: () => Promise<boolean>;
  registerPlayback: (playback: AuthPlaybackContext) => () => void;
  setSelection: (key: string, value: string | undefined) => void;
  restoredSelection: Record<string, string | undefined>;
}
const AuthContext = createContext<AuthContextValue | null>(null);
const currentRoute = () => `${location.pathname}${location.search}${location.hash}`;

export function AuthProvider({ children, slots }: { readonly children: ReactNode; readonly slots: AuthProviderSlots }) {
  const pathname = usePathname();
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<SignInFeedbackKind | null>(null);
  const [restored, setRestored] = useState<{ pathname: string; selection: Record<string, string | undefined> } | null>(null);
  const restoredSelection = restored?.pathname === pathname ? restored.selection : {};
  const selection = useRef<Record<string, string | undefined>>({});
  const playback = useRef<AuthPlaybackContext | null>(null);
  const inFlight = useRef(false);
  const sessionEpoch = useRef(0);

  useEffect(() => {
    const result = consumeSignInFeedback(currentRoute());
    if (result.returnTo !== currentRoute()) history.replaceState(history.state, "", result.returnTo);
    if (result.feedback) {
      // This effect handles a provider redirect; no router navigation or page refresh.
      const frame = requestAnimationFrame(() => { setFeedback(result.feedback); });
      return () => { cancelAnimationFrame(frame); };
    }
  }, [pathname]);

  useEffect(() => {
    const restored = takeReturnUI(consumeSignInFeedback(currentRoute()).returnTo);
    if (!restored) return;
    const frame = requestAnimationFrame(() => {
      setRestored({ pathname, selection: restored.selection });
      window.scrollTo(restored.scrollX, restored.scrollY);
      for (const rail of restored.rails) {
        const element = document.querySelector(`[data-testid="${CSS.escape(rail.id)}"]`);
        if (element) element.scrollLeft = rail.left;
      }
    });
    return () => { cancelAnimationFrame(frame); };
  }, [pathname]);

  useEffect(() => {
    const controller = new AbortController();
    const epoch = sessionEpoch.current;
    void fetch("/api/auth/get-session", { cache: CACHE.fetchNoStore, signal: controller.signal })
      .then(async (response) => response.ok ? await response.json() as { user?: Viewer } | null : null)
      .then((session) => { if (!controller.signal.aborted && epoch === sessionEpoch.current) setViewer(session?.user ?? null); })
      .catch(() => {});
    return () => { controller.abort(); };
  }, [pathname]);

  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => { setFeedback(null); }, 4000);
    return () => { clearTimeout(timer); };
  }, [feedback]);

  useEffect(() => {
    if (!viewer) return;
    void handoffPendingCompletion(sessionCompletionStore(sessionStorage), completionPersistence).catch(() => {});
  }, [viewer]);

  const startSignIn = useCallback(async (provided?: AuthPlaybackContext) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const player = provided ?? playback.current;
    player?.pause();
    const request = createSignInRequest(player?.returnRoute ?? currentRoute(), player?.currentSecond());
    saveReturnUI({ route: request.callbackURL, scrollX: scrollX, scrollY: scrollY, selection: selection.current,
      rails: Array.from(document.querySelectorAll<HTMLElement>('[data-testid]')).filter((element) => element.scrollLeft > 0)
        .map((element) => ({ id: element.dataset.testid ?? "", left: element.scrollLeft })) });
    setFeedback(null);
    setBusy(true);
    try {
      const response = await fetch("/api/auth/sign-in/social", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...request, disableRedirect: true }),
      });
      if (!response.ok) throw new Error("Sign-in unavailable");
      const data = await response.json() as { url?: string };
      const redirect = new URL(data.url ?? "");
      if (!isSignInRedirect(redirect)) throw new Error("Invalid provider redirect");
      location.assign(redirect.href);
    } catch {
      takeReturnUI(request.callbackURL);
      inFlight.current = false;
      setBusy(false);
      setFeedback("error");
    }
  }, []);

  const signOut = useCallback(async () => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setBusy(true);
    try {
      const response = await fetch("/api/auth/sign-out", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!response.ok) return false;
      sessionEpoch.current++;
      playback.current?.pause();
      setViewer(null);
      return true;
    } catch { return false; }
    finally { inFlight.current = false; setBusy(false); }
  }, []);
  const registerPlayback = useCallback((value: AuthPlaybackContext) => {
    playback.current = value;
    return () => { if (playback.current === value) playback.current = null; };
  }, []);
  const setSelection = useCallback((key: string, value: string | undefined) => { selection.current[key] = value; }, []);

  return <AuthContext.Provider value={{ viewer, busy, startSignIn, signOut, registerPlayback, setSelection, restoredSelection }}>
    {children}
    {busy && !viewer ? <slots.busyOverlay /> : null}
    {feedback ? <slots.signInFeedback kind={feedback} onRetry={() => { void startSignIn(); }} /> : null}
  </AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth requires AuthProvider");
  return context;
}

/** Selection survives an OAuth round trip but ordinary page visits keep select-first behavior. */
export function useAuthSelection(key: string) {
  const { setSelection, restoredSelection } = useAuth();
  const [selected, setSelected] = useState<string>();
  const value = selected ?? restoredSelection[key];
  useEffect(() => { setSelection(key, value); }, [key, value, setSelection]);
  return [value, setSelected] as const;
}

/** D2: authentication returns paused; clicking Mark complete never queues completion while signed out. */
export function useMarkComplete(playback: AuthPlaybackContext, lesson: { courseSlug: string; lessonSlug: string }) {
  const { viewer, startSignIn } = useAuth();
  return () => viewer
    ? completionPersistence.markComplete({ ...lesson, endedAt: Date.now() })
    : startSignIn(playback);
}
