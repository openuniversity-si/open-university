import { describe, expect, it } from "vitest";
import { drainPendingObjects, queuePending } from "./pending-deletions.ts";

describe("pending deletions", () => {
  it("rolls back the queue with the catalog delete when the transaction throws", async () => {
    const calls: string[] = [];
    const tx = { query: (sql: string) => { calls.push(sql); return Promise.reject(new Error("boom")); } };
    await expect(queuePending(tx, ["covers/a.jpg"], [{ pathname: "covers/a.jpg", owner: "course", ownerId: "course-1" }], "course-1", "req")).rejects.toThrow("boom");
    expect(calls.some((sql) => sql.startsWith("DELETE FROM r2_pending_deletions"))).toBe(false);
    const drained = await drainPendingObjects({ query: () => Promise.resolve({ rows: [] }) }, () => ({ delete: () => Promise.resolve() }), { courseId: "course-1" }, []);
    expect(drained).toEqual({ deleted: [], pending: [] });
  });
  it("keeps a failed key queued and drains only the checked key on the next call", async () => {
    const rows = [{ key: "covers/ok.jpg" }, { key: "covers/stuck.jpg" }];
    const db = { query: (sql: string) => Promise.resolve(sql.startsWith("SELECT") ? { rows } : { rows: [] }) };
    const store = () => ({ delete: (key: string) => key.endsWith("stuck.jpg") ? Promise.reject(new Error("r2")) : Promise.resolve() });
    const first = await drainPendingObjects(db, store, { courseId: "course-1" }, ["covers/ok.jpg", "covers/stuck.jpg"]);
    expect(first.deleted).toEqual([]);
    expect(first.pending).toEqual(["covers/ok.jpg", "covers/stuck.jpg"]);
  });
  it("deletes a media key only after the retention window", async () => {
    const sha = "a".repeat(64);
    const key = `m/${sha}.jpg`;
    const now = new Date("2026-10-20T00:00:00.000Z");
    const marked = new Date(now.getTime() - 31 * 24 * 60 * 60 * 1000).toISOString();
    const db = { query: (sql: string) => Promise.resolve(sql.includes("orphaned_at") ? { rows: [{ orphaned_at: marked }] } : sql.startsWith("SELECT") ? { rows: [{ key }] } : { rows: [] }) };
    const deleted: string[] = [];
    const drained = await drainPendingObjects(db, () => ({ delete: (value: string) => { deleted.push(value); return Promise.resolve(); } }), { courseId: "course-1" }, [key], new Set(), now);
    expect(deleted).toEqual([key]);
    expect(drained).toEqual({ deleted: [key], pending: [] });
  });
});
