import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resetPreviewEnvironment } from "./lifecycle.ts";
import { buildCrossEnvironmentInventory, markOrExecuteMediaGc, RETENTION_MS } from "../media/domain/figure-exit.ts";
import type { LifecycleDeps, LifecycleEnvironment, LifecycleJobs, LifecycleObject, LifecycleStorage } from "../media/domain/figure-ports.ts";

const NOW = new Date("2026-10-20T00:00:00.000Z");
const sha = (n: number) => n.toString(16).padStart(64, "0");

interface Row extends LifecycleObject { removed: boolean; backup: boolean }

function harness(seed: readonly Row[], options: { storageComplete?: boolean; prodBarrier?: boolean; previewBarrier?: boolean; job?: boolean; copy?: boolean; remove?: boolean } = {}) {
  const rows = new Map(seed.map((row) => [row.sha256, { ...row }]));
  const calls: string[] = [];
  const receipts: string[] = [];
  const env = (name: "prod" | "preview"): LifecycleEnvironment => ({
    name,
    listInventory: () => Promise.resolve({
      environment: name,
      complete: true,
      references: [...rows.values()].map((row) => ({ ...row, referenced: name === "prod" ? row.referenced && row.sha256.endsWith("1") : row.referenced && !row.sha256.endsWith("1") })),
    }),
    markOrphan: (id) => {
      const row = rows.get(id);
      if (!row || row.referenced) return Promise.resolve("referenced");
      if (row.orphanedAt) return Promise.resolve("already");
      row.orphanedAt = NOW.toISOString();
      calls.push(`mark:${id}`);
      return Promise.resolve("marked");
    },
    clearOrphan: (id) => { const row = rows.get(id); if (row) row.orphanedAt = null; return Promise.resolve(); },
    barrier: () => Promise.resolve(name === "prod" ? options.prodBarrier !== false : options.previewBarrier !== false),
    revalidate: () => Promise.resolve(true),
    snapshot: () => Promise.resolve({ id: "snap-1", checksum: "abc", rows: rows.size }),
    restore: () => { calls.push("restore"); return Promise.resolve(true); },
    reset: () => { calls.push("reset"); return Promise.resolve(true); },
    rehearse: () => Promise.resolve(true),
    deleteRow: (id) => { calls.push(`row:${id}`); return Promise.resolve(rows.delete(id)); },
  });
  const storage: LifecycleStorage = {
    list: () => Promise.resolve({ keys: [...rows.values()].filter((row) => row.bytesPresent).map((row) => `m/${row.sha256}.jpg`), cursor: null, complete: options.storageComplete !== false }),
    copyAside: (id) => { const row = rows.get(id); if (!row || options.copy === false) return Promise.resolve(false); row.backup = true; calls.push(`copy:${id}`); return Promise.resolve(true); },
    remove: (id) => { const row = rows.get(id); if (!row || options.remove === false) return Promise.resolve(false); row.removed = true; row.bytesPresent = false; calls.push(`remove:${id}`); return Promise.resolve(true); },
    exists: (id) => Promise.resolve(rows.get(id)?.bytesPresent === true),
  };
  const jobs: LifecycleJobs = {
    claim: () => Promise.resolve(options.job === false ? { acquired: false, token: "" } : { acquired: true, token: "lease" }),
    receipt: (_token, id) => { receipts.push(id); calls.push(`receipt:${id}`); return Promise.resolve(); },
    complete: () => Promise.resolve(),
  };
  const deps: LifecycleDeps = { environments: ["prod", "preview"], now: () => NOW, ports: { prod: env("prod"), preview: env("preview") }, storage, jobs };
  return { deps, rows, calls, receipts };
}

function object(id: string, patch: Partial<Row> = {}): Row {
  return { sha256: id, bytesPresent: true, referenced: false, retainedRelease: false, orphanedAt: null, removed: false, backup: false, ...patch };
}

describe("media retention", () => {
  it("blocks mark and apply when pagination, a reference, a retained release or the age is short", async () => {
    const young = new Date(NOW.getTime() - (RETENTION_MS - 60_000)).toISOString();
    const exact = new Date(NOW.getTime() - RETENTION_MS).toISOString();
    const open = harness([
      object(sha(1), { referenced: true, orphanedAt: exact }),
      object(sha(2), { retainedRelease: true, orphanedAt: exact }),
      object(sha(3), { orphanedAt: null }),
      object(sha(4), { orphanedAt: young }),
      object(sha(5), { orphanedAt: exact }),
    ]);
    const inventory = await buildCrossEnvironmentInventory(open.deps);
    expect(inventory.complete).toBe(true);
    expect(inventory.references.find((row) => row.sha256 === sha(1))?.prod).toBe(true);
    const marked = await markOrExecuteMediaGc(open.deps, { mode: "mark" });
    expect(marked.deleted).toBe(0);
    expect(open.calls.filter((call) => call.startsWith("remove"))).toEqual([]);
    expect(open.rows.get(sha(3))?.orphanedAt).toBe(NOW.toISOString());
    const again = await markOrExecuteMediaGc(open.deps, { mode: "mark" });
    expect(again.marked).toBe(0);
    expect(open.rows.get(sha(3))?.orphanedAt).toBe(NOW.toISOString());
    const applied = await markOrExecuteMediaGc(open.deps, { mode: "apply" });
    expect(applied.deleted).toBe(1);
    expect(open.calls).not.toContain("reset");
    expect(open.rows.has(sha(5))).toBe(false);
    expect(open.rows.get(sha(4))?.removed).toBe(false);
    expect(open.calls.indexOf(`copy:${sha(5)}`)).toBeLessThan(open.calls.indexOf(`receipt:${sha(5)}`));
    expect(open.calls.indexOf(`receipt:${sha(5)}`)).toBeLessThan(open.calls.indexOf(`remove:${sha(5)}`));
    const interrupted = harness([object(sha(5), { orphanedAt: exact })], { storageComplete: false });
    expect((await buildCrossEnvironmentInventory(interrupted.deps)).complete).toBe(false);
    expect(await markOrExecuteMediaGc(interrupted.deps, { mode: "apply" })).toMatchObject({ deleted: 0, marked: 0 });
    expect(interrupted.calls).toEqual([]);
  });

  it("fails closed when a barrier, copy or generation is missing, and resumes from the receipt", async () => {
    const exact = new Date(NOW.getTime() - RETENTION_MS).toISOString();
    const blocked = harness([object(sha(5), { orphanedAt: exact })], { prodBarrier: false });
    expect((await markOrExecuteMediaGc(blocked.deps, { mode: "apply" })).deleted).toBe(0);
    expect(blocked.calls.some((call) => call.startsWith("remove"))).toBe(false);
    const stale = harness([object(sha(5), { orphanedAt: exact })]);
    const current = await buildCrossEnvironmentInventory(stale.deps);
    expect((await markOrExecuteMediaGc(stale.deps, { mode: "apply", generation: "0".repeat(64) })).deleted).toBe(0);
    expect((await markOrExecuteMediaGc(stale.deps, { mode: "apply", generation: current.generation })).deleted).toBe(1);
    const crashed = harness([object(sha(6), { orphanedAt: exact })], { remove: false });
    expect((await markOrExecuteMediaGc(crashed.deps, { mode: "apply" })).deleted).toBe(0);
    expect(crashed.rows.get(sha(6))?.backup).toBe(true);
    expect(crashed.receipts).toEqual([sha(6)]);
  });

  it("rejects a production reset and restores when the reset fails", async () => {
    const base = harness([]);
    expect(await resetPreviewEnvironment(base.deps, { dryRun: true })).toEqual({ dryRun: true, snapshotId: null, verified: false });
    expect(await resetPreviewEnvironment(base.deps, { dryRun: false, environment: "prod" })).toEqual({ dryRun: true, snapshotId: null, verified: false });
    expect(base.calls).toEqual([]);
    const failed = harness([]);
    failed.deps.ports.preview.reset = () => Promise.resolve(false);
    const report = await resetPreviewEnvironment(failed.deps, { dryRun: false, environment: "preview" });
    expect(report.verified).toBe(false);
    expect(failed.calls).toContain("restore");
    const preview = harness([]);
    let rows = 2;
    preview.deps.ports.preview.snapshot = () => Promise.resolve({ id: "snap-1", checksum: "abc", rows });
    preview.deps.ports.preview.reset = () => { rows = 0; preview.calls.push("reset"); return Promise.resolve(true); };
    preview.deps.ports.preview.restore = () => { rows = 2; preview.calls.push("restore"); return Promise.resolve(true); };
    const done = await resetPreviewEnvironment(preview.deps, { dryRun: false });
    expect(done).toEqual({ dryRun: false, snapshotId: "snap-1", verified: true });
    expect(rows).toBe(0);
    const broken = harness([]);
    broken.deps.ports.preview.rehearse = () => Promise.resolve(false);
    expect((await resetPreviewEnvironment(broken.deps, { dryRun: false })).verified).toBe(false);
    expect(broken.calls).toEqual([]);
    expect(broken.calls.some((call) => call.startsWith("remove") || call.startsWith("mark:"))).toBe(false);
  });
});

describe("figure exit and preview reset", () => {
  it("keeps the thirty-day rule off the preview reset, and the reset off the exit", () => {
    const reset = readFileSync(new URL("./lifecycle.ts", import.meta.url), "utf8");
    const exit = readFileSync(new URL("../media/domain/figure-exit.ts", import.meta.url), "utf8");
    expect(reset).not.toContain("RETENTION_MS");
    expect(reset).not.toContain("markOrExecuteMediaGc");
    expect(exit).not.toContain("resetPreviewEnvironment");
  });
});
