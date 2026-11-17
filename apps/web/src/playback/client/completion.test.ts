import { expect, it, vi } from "vitest";
import { captureSignedOutCompletion, handoffPendingCompletion, sessionCompletionStore } from "./completion.ts";
import { completionPersistence } from "./persistence.ts";
import { FakeEngine } from "../testing/fake-engine.ts";

const lesson = { courseSlug: "course", lessonSlug: "lesson" };
function storageFixture() {
  const data = new Map<string, string>();
  return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value); }, removeItem: (key: string) => { data.delete(key); } };
}
it("keeps signed-out completion across the redirect and clears after successful handoff", async () => {
  const storage = storageFixture(); const store = sessionCompletionStore(storage);
  const engine = new FakeEngine(lesson, () => 123);
  captureSignedOutCompletion(engine, store, () => false);
  engine.play({ type: "click", isTrusted: true }); engine.emit("playing"); engine.emit("ended");
  const afterRedirect = sessionCompletionStore(storage);
  expect(afterRedirect.read()).toEqual({ ...lesson, endedAt: 123 });
  await expect(handoffPendingCompletion(afterRedirect, { markComplete: () => Promise.reject(new Error("offline")) })).rejects.toThrow("offline");
  expect(afterRedirect.read()).not.toBeNull();
  const completed: unknown[] = [];
  await handoffPendingCompletion(afterRedirect, { markComplete(completion) { completed.push(completion); return Promise.resolve(); } });
  expect(completed).toEqual([{ ...lesson, endedAt: 123 }]); expect(store.read()).toBeNull();
});
it("ignores signed-in completions, corrupt storage and preserves newer pending records", async () => {
  const storage = storageFixture(); storage.setItem("open-university:pending-completion:v1", "invalid");
  const store = sessionCompletionStore(storage); expect(store.read()).toBeNull();
  const engine = new FakeEngine(lesson); captureSignedOutCompletion(engine, store, () => true);
  engine.play({ type: "click", isTrusted: true }); engine.emit("playing"); engine.emit("ended"); expect(store.read()).toBeNull();
  store.write({ ...lesson, endedAt: 123 });
  await handoffPendingCompletion(store, { markComplete() { store.write({ ...lesson, endedAt: 456 }); return Promise.resolve(); } });
  expect(store.read()?.endedAt).toBe(456);
});

it("Decision 4: persists the pending completion through POST /api/progress and keeps it when that fails", async () => {
  const store = sessionCompletionStore(storageFixture());
  const pending = { ...lesson, endedAt: 123 };
  store.write(pending);
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(new Response(null, { status: 500 })).mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  try {
    await expect(handoffPendingCompletion(store, completionPersistence)).rejects.toThrow();
    expect(store.read()).toEqual(pending);
    await handoffPendingCompletion(store, completionPersistence);
    expect(store.read()).toBeNull();
    expect(fetch).toHaveBeenLastCalledWith("/api/progress", expect.objectContaining({ method: "POST", body: JSON.stringify({ ...lesson, completed: true }) }));
  } finally { vi.unstubAllGlobals(); }
});
