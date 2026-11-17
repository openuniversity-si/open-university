import { describe, expect, it, vi } from "vitest";
import { ledgerStatus, runLedger, type MigrationLedger } from "./migrations.ts";
import type { Queryable } from "../../src/platform/db/uow.ts";
function fixture(name: "app" | "tooling") {
  const events: string[] = [];
  const db: Queryable = { query: (sql) => { events.push(sql); return Promise.resolve({ rows: [] }); } };
  const files = [{ id: "1", checksum: "a" }, { id: "2", checksum: "b" }];
  let applied = files.slice(0, 1);
  const apply = vi.fn((_db: Queryable, pending: readonly { id: string }[]) => {
    events.push(`apply:${pending.map((file) => file.id).join(",")}`); applied = files;
    return Promise.resolve();
  });
  const ledger: MigrationLedger = { name, lock: name === "app" ? [742019, 1] : [742019, 2], files: () => Promise.resolve(files), applied: () => Promise.resolve(applied), apply };
  return { db, ledger, events, apply, setApplied: (rows: typeof files) => { applied = rows; } };
}
describe.each(["app", "tooling"] as const)("shared %s migration policy", (name) => {
  it("locks the same session, applies pending only, then verifies history; rerun is idempotent", async () => {
    const { db, ledger, events } = fixture(name);
    expect(await runLedger(ledger, db, { dryRun: false })).toEqual({ applied: 2, pending: 0 });
    expect(await runLedger(ledger, db, { dryRun: false })).toEqual({ applied: 2, pending: 0 });
    const lock = `SELECT pg_advisory_lock(${String(ledger.lock[0])}, ${String(ledger.lock[1])})`;
    expect(events).toEqual([lock, "apply:2", lock, "apply:"]);
  });
  it("dry-runs in a read-only snapshot without lock or writes", async () => {
    const { db, ledger, events, apply } = fixture(name);
    expect(await runLedger(ledger, db, { dryRun: true })).toEqual({ applied: 1, pending: 1 });
    expect(events).toEqual(["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY", "ROLLBACK"]);
    expect(apply).not.toHaveBeenCalled();
  });
  it.each([
    [{ id: "1", checksum: "changed" }], [{ id: "2", checksum: "b" }],
    [{ id: "1", checksum: "a" }, { id: "2", checksum: "b" }, { id: "3", checksum: "c" }],
  ])("rejects changed, reordered or extra applied history", async (...rows) => {
    const { db, ledger, setApplied, apply } = fixture(name);
    setApplied(rows);
    await expect(ledgerStatus(ledger, db)).rejects.toThrow("history differs");
    await expect(runLedger(ledger, db, { dryRun: false })).rejects.toThrow("history differs");
    expect(apply).not.toHaveBeenCalled();
  });
});
