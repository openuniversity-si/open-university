import { describe, expect, it, vi } from "vitest";
import { withUnitOfWork, type DbPool } from "./uow.ts";

describe("withUnitOfWork", () => {
  function fixture(fail?: string) {
    const events: string[] = [];
    const release = vi.fn();
    const query = (sql: string) => {
      events.push(sql);
      return sql === fail ? Promise.reject(new Error(sql)) : Promise.resolve({ rows: [] });
    };
    const pool: DbPool = { query, connect: () => Promise.resolve({ query, release }) };
    return { events, pool, release };
  }
  it("runs effects in registration order after COMMIT", async () => {
    const { pool, events } = fixture();
    await withUnitOfWork(pool, (tx) => {
      tx.onAfterCommit(() => { events.push("effect1"); });
      tx.onAfterCommit(() => { events.push("effect2"); });
      return Promise.resolve();
    });
    expect(events).toEqual(["BEGIN", "COMMIT", "effect1", "effect2"]);
  });
  it("emits the advisory SQL already deployed, including the catalog release literal", async () => {
    const { pool, events } = fixture();
    await withUnitOfWork(pool, async (tx) => {
      await tx.acquireLock({ scope: "xact", key: "media:course:course-1:poster_9x16:default" });
      await tx.acquireLock({ scope: "xact-hashtext", key: "catalog:release" });
    });
    expect(events).toEqual([
      "BEGIN",
      "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
      "SELECT pg_advisory_xact_lock(hashtext('catalog:release'))",
      "COMMIT",
    ]);
  });
  it.each(["work", "COMMIT"])("never runs effects when %s fails", async (failure) => {
    const { pool, events } = fixture(failure);
    await expect(withUnitOfWork(pool, (tx) => {
      tx.onAfterCommit(() => { events.push("effect"); });
      return failure === "work" ? Promise.reject(new Error("work")) : Promise.resolve();
    })).rejects.toThrow(failure);
    expect(events).toEqual(failure === "work" ? ["BEGIN", "ROLLBACK"] : ["BEGIN", "COMMIT", "ROLLBACK"]);
  });
});
