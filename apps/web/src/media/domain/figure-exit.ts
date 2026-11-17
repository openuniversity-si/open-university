import { createHash } from "node:crypto";
import { PAGINATION } from "../../kernel/pagination.ts";
import type { EnvironmentInventory, GcReport, LifecycleDeps, LifecycleEnvironment, LifecycleInventoryReport } from "./figure-ports.ts";

/** Thirty days. Age is compared with the injected clock; the SQL marker itself uses the database clock. */
export const RETENTION_MS = 30 * 24 * 60 * 60 * 1000;

interface Merged {
  readonly sha256: string;
  prod: boolean;
  preview: boolean;
  retainedRelease: boolean;
  bytesPresent: boolean;
  referenced: boolean;
  orphanedAt: string | null;
}

function generationOf(complete: boolean, rows: readonly Merged[]): string {
  const body = JSON.stringify({
    complete,
    rows: rows.map((row) => ({
      sha256: row.sha256, prod: row.prod, preview: row.preview, retainedRelease: row.retainedRelease,
      bytesPresent: row.bytesPresent, referenced: row.referenced, orphanedAt: row.orphanedAt,
    })),
  });
  return createHash("sha256").update(body).digest("hex");
}

function shaFromKey(key: string): string | null {
  return /^m\/([a-f0-9]{64})\.[a-z0-9]+$/.exec(key)?.[1] ?? null;
}

async function loadEnvironment(port: LifecycleEnvironment): Promise<EnvironmentInventory> {
  try {
    const inventory = await port.listInventory();
    if (inventory.environment !== port.name) return { environment: port.name, complete: false, references: inventory.references };
    return inventory;
  } catch {
    return { environment: port.name, complete: false, references: [] };
  }
}

async function merge(deps: LifecycleDeps): Promise<{ complete: boolean; rows: Merged[] }> {
  const map = new Map<string, Merged>();
  let complete = true;
  const ensure = (sha256: string): Merged => {
    const existing = map.get(sha256);
    if (existing) return existing;
    const created: Merged = { sha256, prod: false, preview: false, retainedRelease: false, bytesPresent: false, referenced: false, orphanedAt: null };
    map.set(sha256, created);
    return created;
  };
  for (const name of deps.environments) {
    const inventory = await loadEnvironment(deps.ports[name]);
    if (!inventory.complete) complete = false;
    for (const ref of inventory.references) {
      const row = ensure(ref.sha256);
      if (name === "prod" && ref.referenced) row.prod = true;
      if (name === "preview" && ref.referenced) row.preview = true;
      if (ref.retainedRelease) row.retainedRelease = true;
      if (ref.referenced) row.referenced = true;
      if (ref.bytesPresent) row.bytesPresent = true;
      if (ref.orphanedAt && (row.orphanedAt === null || ref.orphanedAt < row.orphanedAt)) row.orphanedAt = ref.orphanedAt;
    }
  }
  try {
    let cursor: string | null = null;
    let pages = 0;
    for (;;) {
      const page = await deps.storage.list(cursor);
      pages += 1;
      if (!page.complete) complete = false;
      for (const key of page.keys) {
        const sha256 = shaFromKey(key);
        if (sha256) ensure(sha256).bytesPresent = true;
      }
      if (!page.complete || page.cursor === null) break;
      if (page.cursor === cursor || pages > PAGINATION.maxStoragePages) { complete = false; break; }
      cursor = page.cursor;
    }
  } catch {
    complete = false;
  }
  return { complete, rows: [...map.values()].sort((a, b) => (a.sha256 < b.sha256 ? -1 : 1)) };
}

function reportOf(complete: boolean, rows: readonly Merged[]): LifecycleInventoryReport {
  return {
    generation: generationOf(complete, rows),
    complete,
    references: rows.map((row) => ({ sha256: row.sha256, prod: row.prod, preview: row.preview, retainedRelease: row.retainedRelease })),
  };
}

/** A referenced object without bytes is an inconsistency, never an orphan. */
function orphanCandidate(row: Merged): boolean {
  return row.bytesPresent && !row.referenced && !row.prod && !row.preview && !row.retainedRelease;
}

export async function buildCrossEnvironmentInventory(deps: LifecycleDeps): Promise<LifecycleInventoryReport> {
  const merged = await merge(deps);
  return reportOf(merged.complete, merged.rows);
}

export async function markOrExecuteMediaGc(deps: LifecycleDeps, opts: { mode: "dry-run" | "mark" | "apply"; generation?: string }): Promise<GcReport> {
  const merged = await merge(deps);
  const report = reportOf(merged.complete, merged.rows);
  const skippedAll = { generation: report.generation, marked: 0, deleted: 0, skipped: merged.rows.length };
  if (!merged.complete) return skippedAll;
  if (opts.generation && opts.generation !== report.generation) return skippedAll;
  const claimed = await deps.jobs.claim(report.generation);
  if (!claimed.acquired) return skippedAll;
  if (opts.mode === "dry-run") {
    await deps.jobs.complete(claimed.token);
    return skippedAll;
  }
  if (opts.mode === "mark") {
    let marked = 0;
    let skipped = 0;
    for (const row of merged.rows) {
      if (!orphanCandidate(row) || row.orphanedAt !== null) { skipped += 1; continue; }
      const result = await deps.ports.preview.markOrphan(row.sha256).then((preview) => deps.ports.prod.markOrphan(row.sha256).then((prod) => (preview === "marked" || prod === "marked" ? "marked" : preview)));
      if (result === "marked") marked += 1;
      else skipped += 1;
    }
    await deps.jobs.complete(claimed.token);
    return { generation: report.generation, marked, deleted: 0, skipped };
  }
  const blocked = await deps.ports.prod.barrier().then((prod) => deps.ports.preview.barrier().then((preview) => prod && preview));
  const revalidated = blocked && await deps.ports.prod.revalidate().then((prod) => deps.ports.preview.revalidate().then((preview) => prod && preview));
  if (!blocked || !revalidated) {
    await deps.jobs.complete(claimed.token, "barrier");
    return skippedAll;
  }
  const fresh = await merge(deps);
  const freshReport = reportOf(fresh.complete, fresh.rows);
  if (!fresh.complete || freshReport.generation !== report.generation) {
    await deps.jobs.complete(claimed.token, "inventory-changed");
    return { generation: freshReport.generation, marked: 0, deleted: 0, skipped: fresh.rows.length };
  }
  const now = deps.now().getTime();
  let deleted = 0;
  let skipped = 0;
  for (const row of fresh.rows) {
    const age = row.orphanedAt === null ? null : now - Date.parse(row.orphanedAt);
    if (!orphanCandidate(row) || age === null || age < RETENTION_MS) { skipped += 1; continue; }
    const copied = await deps.storage.copyAside(row.sha256);
    if (!copied) { skipped += 1; continue; }
    await deps.jobs.receipt(claimed.token, row.sha256);
    const removed = await deps.storage.remove(row.sha256);
    const gone = removed && !(await deps.storage.exists(row.sha256));
    if (!gone) { skipped += 1; continue; }
    const dropped = await deps.ports.prod.deleteRow(row.sha256).then((prod) => deps.ports.preview.deleteRow(row.sha256).then((preview) => prod || preview));
    if (dropped) deleted += 1;
    else skipped += 1;
  }
  await deps.jobs.complete(claimed.token);
  return { generation: report.generation, marked: 0, deleted, skipped };
}
