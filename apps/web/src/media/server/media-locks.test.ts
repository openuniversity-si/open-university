import { describe, expect, it } from "vitest";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import { lockMediaOwners } from "./media-locks.ts";

function recorder() {
  const locks: { scope: string; mode?: string }[] = [];
  const queries: { sql: string; values?: unknown[] }[] = [];
  const tx = {
    query(sql: string, values?: unknown[]) {
      queries.push({ sql, values });
      return Promise.resolve({ rows: [] });
    },
    acquireLock(lock: { scope: string; mode?: "shared" | "exclusive" }) {
      locks.push(lock);
      return Promise.resolve();
    },
    onAfterCommit() {},
  };
  return { tx: tx as UnitOfWork, locks, queries };
}

describe("media owner locks", () => {
  it("takes maintenance on key 742020 before owner keys, remapping hash 0 to 1 and ordering the keys", async () => {
    const db = recorder();
    await lockMediaOwners(db.tx, [
      { owner: "lesson", ownerId: "lesson-2" },
      { owner: "course", ownerId: "course-1" },
    ]);
    expect(db.locks).toEqual([{ scope: "media-maintenance", mode: "shared" }]);
    expect(db.queries).toHaveLength(1);
    const statement = db.queries[0]?.sql ?? "";
    expect(statement).toContain("pg_advisory_xact_lock(742020, key)");
    expect(statement).toContain("CASE WHEN hashtext(label) = 0 THEN 1 ELSE hashtext(label) END");
    expect(statement.indexOf("hashtext(label) = 0 THEN 1")).toBeLessThan(statement.indexOf("ORDER BY 1"));
    expect(statement).toContain("ORDER BY 1");
    expect(db.queries[0]?.values).toEqual([["lesson:lesson-2", "course:course-1"]]);
  });

  it("skips the owner query when nothing is locked and passes exclusive mode through", async () => {
    const empty = recorder();
    await lockMediaOwners(empty.tx, []);
    expect(empty.locks).toEqual([{ scope: "media-maintenance", mode: "shared" }]);
    expect(empty.queries).toEqual([]);
    const prune = recorder();
    await lockMediaOwners(prune.tx, [{ owner: "area", ownerId: "physics" }], "exclusive");
    expect(prune.locks).toEqual([{ scope: "media-maintenance", mode: "exclusive" }]);
    expect(prune.queries[0]?.values).toEqual([["area:physics"]]);
  });
});
