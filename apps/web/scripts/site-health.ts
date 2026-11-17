// effects: read-only
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { stitchRelease } from "../src/catalog/domain/incremental-compile.ts";
import { readProjections, readReleaseIndex } from "../src/catalog/server/projections-repo.ts";
import { fixtureMeasurements } from "../src/catalog/testing/route-payload.ts";
import { CACHE_CHUNK_ITEMS, jsonBytes } from "../src/kernel/cache-budget.ts";
import { parseTargetArgs, resolveDatabaseTarget, safeDatabaseError } from "./lib/database-target.ts";
import { htmlBytes, reportRefusal, siteHealthCeiling, siteHealthFailures, siteHealthReport, type SiteHealthMeasurement } from "../src/site/domain/site-health.ts";

// Reports stay on this machine (gitignored), next to the app.
const reportDir = resolve(dirname(fileURLToPath(import.meta.url)), "../.gate/site-health");

function option(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  const value = index === -1 ? undefined : process.argv[index + 1];
  return typeof value === "string" && !value.startsWith("--") ? value : undefined;
}

function printMeasurements(measurements: readonly SiteHealthMeasurement[]): void {
  for (const measurement of measurements) {
    const budget = siteHealthCeiling(measurement.route, measurement.audience);
    console.log(`${measurement.route}\t${measurement.audience}\trsc ${String(measurement.rscBytes)}\thtml ${String(htmlBytes(measurement.rscBytes))}\tqueries ${String(measurement.queries)}\tserver ${String(measurement.serverMs)}\tbudget rsc ${String(budget.rscBytes)} queries ${String(budget.queries)} ms ${String(budget.serverMs)}`);
  }
}

function fail(failures: readonly string[]): void {
  for (const failure of failures) console.error(failure);
  process.exit(1);
}

function safe(error: unknown): string {
  const message = error instanceof Error ? error.message : "site-health failed";
  return message.replace(/postgres(?:ql)?:\/\/\S+/gi, "[database]");
}

/** Largest slice the chunked cache would store. One item over the cap is reported at its own size. */
function storedChunkBytes(items: readonly unknown[], budget: number): number {
  let max = 0;
  let index = 0;
  let width = Math.max(1, CACHE_CHUNK_ITEMS);
  while (index < items.length) {
    const slice = items.slice(index, index + width);
    const size = jsonBytes(slice);
    if (size > budget && slice.length > 1) {
      width = Math.max(1, Math.floor(width / 2));
      continue;
    }
    if (size > max) max = size;
    index += slice.length;
    width = CACHE_CHUNK_ITEMS;
  }
  return max;
}

function fixture(): void {
  const measurements = fixtureMeasurements();
  printMeasurements(measurements);
  const failures = siteHealthFailures(measurements);
  if (failures.length > 0) fail(failures);
}

function reportPath(batchSha: string): string {
  return resolve(reportDir, `${batchSha}.json`);
}

function requireReport(batchSha: string): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(reportPath(batchSha), "utf8")) as unknown;
  } catch {
    console.error("site-health report is missing for this batch");
    process.exit(1);
  }
  const reason = reportRefusal(batchSha, parsed);
  if (reason) {
    console.error(reason);
    process.exit(1);
  }
}

async function clone(batchSha: string): Promise<void> {
  const target = option("--target");
  let url: string | undefined;
  try {
    url = target ? resolveDatabaseTarget(parseTargetArgs(["--target", target], false).target) : process.env.APP_DATABASE_URL ?? process.env.TEST_DATABASE_URL;
  } catch (error) {
    console.error(safeDatabaseError(error));
    process.exit(2);
  }
  if (!url) {
    console.error("site-health: pass --target <database>, or set APP_DATABASE_URL or TEST_DATABASE_URL");
    process.exit(2);
  }
  const client = new pg.Client({ connectionString: url });
  let queries = 0;
  const db = {
    query: (sql: string, params?: readonly unknown[]) => {
      queries += 1;
      return client.query(sql, params as unknown[]);
    },
  };
  const started = performance.now();
  try {
    await client.connect();
    const active: unknown = await db.query("SELECT number FROM catalog_releases WHERE is_active");
    const rows = active !== null && typeof active === "object" && "rows" in active && Array.isArray(active.rows) ? active.rows : [];
    const row: unknown = rows[0];
    const raw = row !== null && typeof row === "object" && "number" in row ? row.number : undefined;
    const number = typeof raw === "number" || typeof raw === "string" ? Number(raw) : Number.NaN;
    if (!Number.isInteger(number) || number < 1) {
      console.error("site-health: no active release on the clone");
      process.exit(1);
    }
    const index = await readReleaseIndex(db, number);
    if (!index) {
      console.error("site-health: the active release has no projection index");
      process.exit(1);
    }
    const loaded = await readProjections(db, index.courses);
    const projections = index.courses.map((ref) => {
      const found = loaded.get(ref.courseId);
      if (!found || found.sha256 !== ref.sha256) throw new Error(`Projection ${ref.courseId} is missing.`);
      return found;
    });
    const catalog = stitchRelease({ number, publishedAt: index.publishedAt, projections, frame: index.frame });
    if (catalog.courses.length === 0) {
      console.error("site-health: the clone release has no courses");
      process.exit(1);
    }
    const serverMs = Math.max(0, Math.round(performance.now() - started));
    const cacheEntryBytes = storedChunkBytes(projections, siteHealthCeiling("/", "anonymous").cacheEntryBytes);
    const measurements = fixtureMeasurements(catalog, serverMs).map((measurement) => ({ ...measurement, queries, cacheEntryBytes }));
    const report = siteHealthReport(batchSha, measurements);
    mkdirSync(reportDir, { recursive: true });
    writeFileSync(reportPath(batchSha), `${JSON.stringify(report)}\n`);
    printMeasurements(measurements);
    if (!report.passed) fail(report.failures);
  } catch (error) {
    console.error(safe(error));
    process.exit(1);
  } finally {
    await client.end().catch(() => undefined);
  }
}

const batchSha = option("--batch-sha") ?? (process.argv.includes("--require") ? option("--require") : undefined);
if (process.argv.includes("--fixture")) fixture();
else if (process.argv.includes("--require")) {
  if (!batchSha) {
    console.error("site-health: --require needs the batch sha");
    process.exit(2);
  }
  requireReport(batchSha);
} else if (process.argv.includes("--clone")) {
  if (!batchSha) {
    console.error("site-health: --clone needs --batch-sha");
    process.exit(2);
  }
  await clone(batchSha);
} else {
  console.error("site-health: pass --fixture, --clone --batch-sha <sha>, or --require <sha>");
  process.exit(2);
}
