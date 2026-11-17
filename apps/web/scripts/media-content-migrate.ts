import { parseArgs } from "node:util";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { StorageError } from "../src/media/server/r2.ts";
import { mediaConnection, mediaFailure, poolOfOne } from "./lib/media-cli.ts";
import type { MediaPool } from "../src/media/server/repository.ts";
import { targetVariables, type DatabaseTarget } from "./lib/database-target.ts";
import { installMigrationDnsCache, migrationDnsHosts } from "./lib/migrate-dns.ts";
import { createBulkR2Store } from "./lib/r2-bulk.ts";
import { applyContentBatches, assertSampleScope, auditContentSources, backfillContent, contentBatches, contentReferences, contentSummary, planFromReferences, publicContentStore, readInventory, referenceSnapshot, rollbackContent, selectContentSample, verifyInventory, type ContentPlan, type ContentReference } from "./lib/media-content-migrate.ts";

function stringList(value: unknown): string[] {
  if (value == null) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new StorageError("Invalid migration progress file.");
  return value.filter((item): item is string => typeof item === "string");
}

/**
 * Modes: --dry-run | --apply (default) | --verify | --rollback.
 * `--sample N` (alias `--limit`) keeps a stable sha256 sample for the DB gate.
 * `--batch-size` (default 200) copies and verifies one batch, then commits that batch's pointers.
 * Without --map, dry-run/apply write a fresh mapping under ~/.local/state/open-university/media-content/<target>/.
 */
try {
  installMigrationDnsCache(migrationDnsHosts(process.env));
  const started = performance.now();
  const { values } = parseArgs({ options: {
    "audit-sources": { type: "boolean" }, target: { type: "string" }, "dry-run": { type: "boolean" }, apply: { type: "boolean" }, verify: { type: "boolean" }, rollback: { type: "boolean" },
    map: { type: "string" }, modes: { type: "string" }, "yes-prod": { type: "boolean" }, resume: { type: "boolean" },
    sample: { type: "string" }, limit: { type: "string" }, "batch-size": { type: "string" },
  } });
  const positive = (raw: string | undefined, label: string) => {
    if (raw == null) return undefined;
    if (!/^[1-9]\d*$/.test(raw) || !Number.isSafeInteger(Number(raw))) throw new StorageError(`${label} must be a positive integer.`);
    return Number(raw);
  };
  const sampleCount = positive(values.sample, "--sample");
  const limitCount = positive(values.limit, "--limit");
  if (sampleCount != null && limitCount != null && sampleCount !== limitCount) throw new StorageError("--sample and --limit disagree.");
  const sampleSize = sampleCount ?? limitCount;
  const batchSize = positive(values["batch-size"], "--batch-size") ?? 200;
  const target = values.target;
  if (!target || !Object.hasOwn(targetVariables, target)) throw new StorageError("Explicit --target container|staging|prod required.");
  const selectedCount = [values["audit-sources"], values["dry-run"], values.apply, values.verify, values.rollback].filter(Boolean).length;
  if (values.modes && selectedCount > 0) throw new StorageError("--modes replaces --dry-run, --apply, --verify and --rollback.");
  if (!values.modes && selectedCount > 1) throw new StorageError("Choose at most one --dry-run, --apply, --verify, --rollback.");
  if (values.modes && values.map) throw new StorageError("--map applies to one mode; omit it with --modes.");
  const allowedModes = new Set(["audit-sources", "dry-run", "apply", "verify", "rollback"]);
  const modeList = values.modes
    ? values.modes.split(",").map((item) => item.trim()).filter((item) => item.length > 0)
    : [values["audit-sources"] ? "audit-sources" : values.verify ? "verify" : values.rollback ? "rollback" : values["dry-run"] ? "dry-run" : "apply"];
  if (modeList.length === 0 || modeList.some((mode) => !allowedModes.has(mode))) throw new StorageError("--modes expects dry-run, apply, verify, rollback.");
  if (values.modes && modeList.includes("audit-sources")) throw new StorageError("--modes does not include audit-sources.");
  if (target === "prod" && modeList.some((mode) => mode === "apply" || mode === "rollback") && !values["yes-prod"]) throw new StorageError("Production apply/rollback requires --yes-prod.");
  // A database session is held only around database work: a server may drop idle sessions during minutes of R2/HTTP I/O,
  // and closing such a dropped session never settles, so the close is bounded.
  const withDatabase = async <T>(readOnly: boolean, work: (pool: MediaPool) => Promise<T>): Promise<T> => {
    const db = await mediaConnection(target as DatabaseTarget, readOnly);
    try { return await work(poolOfOne(db)); } finally {
      let timer: NodeJS.Timeout | undefined;
      await Promise.race([db.end().catch(() => undefined), new Promise((resolve) => { timer = setTimeout(resolve, 5000); })]);
      clearTimeout(timer);
    }
  };
  const storage = (apply: boolean) => process.env.MEDIA_CONTENT_STORAGE === "public-read-only" ? publicContentStore() : createBulkR2Store(process.env, apply ? "rw" : "ro");
  const scope = (references: ContentReference[]): ContentReference[] => sampleSize == null ? references : selectContentSample(references, sampleSize);
  let mapSerial = 0;
  const runMode = async (mode: string) => {
  const apply = mode === "apply";
  if (mode === "audit-sources") {
    const inventory = await withDatabase(true, readInventory);
    console.log(JSON.stringify({ target, mode, sample: sampleSize ?? null, totalReferences: inventory.refs.length, ...await auditContentSources({ ...inventory, refs: scope(inventory.refs) }, storage(false)) }));
  } else if (mode === "verify") {
    const inventory = await withDatabase(true, readInventory);
    const selected = scope(inventory.refs);
    if (sampleSize != null) assertSampleScope(inventory.refs, selected);
    const objects = inventory.objects.filter((object) => selected.some((ref) => ref.sha256 === object.sha256));
    console.log(JSON.stringify({ target, mode, sample: sampleSize ?? null, ...await verifyInventory({ refs: selected, objects }), seconds: (performance.now() - started) / 1000 }));
  } else if (mode === "rollback") {
    const hashes = sampleSize == null ? undefined : [...new Set(scope(await withDatabase(true, contentReferences)).map((ref) => ref.sha256))];
    console.log(JSON.stringify({ target, sample: sampleSize ?? null, rollback: true, cleared: await withDatabase(false, (pool) => rollbackContent(pool, hashes)), seconds: (performance.now() - started) / 1000 }));
  } else {
    if (values.resume && !values.map) throw new StorageError("--resume needs the --map file of the earlier run.");
    const map = values.map ?? join(homedir(), ".local/state/open-university/media-content", target, `${new Date().toISOString().replaceAll(":", "")}-${String(process.pid)}-${mode}-${String(mapSerial++)}-mapping.json`);
    const progressPath = `${map}.progress.json`;
    let plan: ContentPlan;
    const store = storage(apply);
    let completed: string[] = [];
    if (values.resume) {
      const saved = JSON.parse(await readFile(map, "utf8")) as { target: string; plan: Omit<ContentPlan, "version"> & { version: number } };
      if (saved.target !== target || saved.plan.version !== 1 || referenceSnapshot(saved.plan.references) !== saved.plan.sourceSha256) throw new StorageError("Invalid migration resume mapping.");
      plan = { ...saved.plan, version: 1 };
      try {
        const progress = JSON.parse(await readFile(progressPath, "utf8")) as { completed?: unknown };
        completed = stringList(progress.completed);
      } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    } else {
      const inventory = await withDatabase(true, readInventory);
      plan = await planFromReferences(scope(inventory.refs), store, inventory.objects);
      await mkdir(dirname(map), { recursive: true, mode: 0o700 });
      // Never overwrite a mapping from an earlier apply. A new plan needs a new path.
      await writeFile(map, JSON.stringify({ target, plan, sample: sampleSize ?? null, batchSize }, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    }
    let result = {};
    if (apply) {
      const applied = await applyContentBatches(plan, store, {
        batchSize, completed,
        backfill: (hashes) => withDatabase(false, (pool) => backfillContent(pool, plan, hashes)),
        onBatch: (report) => { console.error(JSON.stringify({ target, batch: `${String(report.index)}/${String(report.total)}`, copied: report.copied, skipped: report.skipped, failed: report.failed })); },
        persist: async (done) => {
          const tmp = `${progressPath}.tmp`;
          await writeFile(tmp, JSON.stringify({ version: 1, batchSize, completed: done }, null, 2) + "\n", { mode: 0o600 });
          await rename(tmp, progressPath);
        },
      });
      result = { verified: applied.verified, copied: applied.copied, skipped: applied.skipped, updated: applied.updated };
    }
    const report = { target, dryRun: !apply, sample: sampleSize ?? null, batchSize, batches: contentBatches(plan.objects, batchSize).length, ...contentSummary(plan), ...result, map, seconds: (performance.now() - started) / 1000 };
    await writeFile(`${map}.result.tmp`, JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
    await rename(`${map}.result.tmp`, `${map}.result.json`);
    console.log(JSON.stringify(report));
  }
  };
  for (const mode of modeList) await runMode(mode);
} catch (error) { mediaFailure(error); }
