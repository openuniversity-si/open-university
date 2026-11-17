import { PENDING_COMPLETION_KEY } from "../../kernel/brand-ids.ts";
import type { Completion } from "../domain/engine.ts";
import type { PlaybackEngine } from "../ports/engine.ts";

export interface PendingCompletionStore {
  read(): Completion | null;
  write(completion: Completion): void;
  clear(): void;
}
/** F10 hands this record to F11 after authentication. Clear only after persistence succeeds. */
export interface CompletionHandoff {
  markComplete(completion: Completion): Promise<void>;
}
export interface ServerPendingCompletionStore {
  read(sessionId: string): Promise<Completion | null>;
  write(sessionId: string, completion: Completion): Promise<void>;
  clear(sessionId: string): Promise<void>;
}
const key = PENDING_COMPLETION_KEY;
export function sessionCompletionStore(storage: Pick<Storage, "getItem" | "setItem" | "removeItem">): PendingCompletionStore {
  return {
    read() {
      try {
        const value: unknown = JSON.parse(storage.getItem(key) ?? "null");
        if (typeof value !== "object" || value === null || !("courseSlug" in value) || !("lessonSlug" in value) || !("endedAt" in value)) return null;
        if (typeof value.courseSlug !== "string" || !value.courseSlug || typeof value.lessonSlug !== "string" || !value.lessonSlug || typeof value.endedAt !== "number" || !Number.isFinite(value.endedAt) || value.endedAt <= 0) return null;
        return { courseSlug: value.courseSlug, lessonSlug: value.lessonSlug, endedAt: value.endedAt };
      } catch { return null; }
    },
    write(completion) { storage.setItem(key, JSON.stringify(completion)); },
    clear() { storage.removeItem(key); },
  };
}
export function captureSignedOutCompletion(engine: PlaybackEngine, store: PendingCompletionStore, isSignedIn: () => boolean): () => void {
  return engine.subscribe((event) => {
    if (event.type === "ended" && !isSignedIn()) store.write(event.completion);
  });
}
export async function handoffPendingCompletion(store: PendingCompletionStore, handoff: CompletionHandoff): Promise<void> {
  const pending = store.read();
  if (!pending) return;
  await handoff.markComplete(pending);
  // A later lesson may have finished while the handoff was pending.
  if (JSON.stringify(store.read()) === JSON.stringify(pending)) store.clear();
}
