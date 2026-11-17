import { describe, expect, it } from "vitest";
import type { CatalogOwnersPort } from "../ports/owner.ts";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import { pruneInherited } from "./inheritance.ts";

function harness() {
  const order: string[] = [];
  const sql: string[] = [];
  const db = {
    query(statement: string) {
      sql.push(statement);
      order.push("query");
      return Promise.resolve({ rows: [] });
    },
    acquireLock(lock: { scope: string; mode?: string }) {
      order.push(`${lock.scope}:${lock.mode ?? ""}`);
      return Promise.resolve();
    },
    onAfterCommit() {},
  } as UnitOfWork;
  const owners: CatalogOwnersPort = {
    courseOf() { return Promise.resolve(undefined); },
    graph() {
      order.push("graph");
      return Promise.resolve({ courses: [], lessons: [] });
    },
    lockGraph() { order.push("lockGraph"); return Promise.resolve(); },
    inventory() { return Promise.resolve([]); },
  };
  return { db, owners, order, sql };
}

describe("inherited cover prune", () => {
  it("takes exclusive maintenance before it rereads candidates", async () => {
    const { db, owners, order, sql } = harness();
    const report = await pruneInherited(db, true, () => owners);
    expect(sql.join("\n")).not.toMatch(/LOCK\s+TABLE/i);
    expect(order.slice(0, 2)).toEqual(["lockGraph", "media-maintenance:exclusive"]);
    expect(order.indexOf("graph")).toBeGreaterThan(1);
    expect(report).toMatchObject({ apply: true, count: 0, bytesDeleted: 0 });
  });

  it("leaves the graph unlocked on a dry run", async () => {
    const { db, owners, order } = harness();
    const report = await pruneInherited(db, false, () => owners);
    expect(order[0]).toBe("graph");
    expect(order.some((step) => step.startsWith("media-maintenance"))).toBe(false);
    expect(report.apply).toBe(false);
  });
});
