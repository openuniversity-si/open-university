import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { testDatabaseUrl } from "../../../test/fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../../../test/fixtures/catalog-reset.ts";
import { runMigrations } from "../../../scripts/lib/migrations.ts";
import { jobsContract } from "../testing/jobs-contract.ts";
import { createSqlJobStore } from "./jobs-repo.ts";
import type { JobIdentity } from "../ports/jobs.ts";

const cases = ["admin.job.occupied", "admin.job.expired", "admin.job.heartbeat", "admin.job.fencing", "admin.job.hash", "admin.job.cas"];

describe("sql job store", () => {
  let pool: pg.Pool;
  beforeAll(async () => {
    const connectionString = testDatabaseUrl();
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    pool = new pg.Pool({ connectionString });
  }, 120_000);
  afterAll(async () => { await pool.end(); });

  it.each(cases)("%s", async (id) => {
    await pool.query("DELETE FROM catalog_jobs");
    const clock = { now: Date.parse("2026-01-01T00:00:00.000Z") };
    let sequence = 0;
    const store = createSqlJobStore(pool, { now: () => new Date(clock.now), ids: () => { sequence += 1; return `job-${id.replaceAll(".", "-")}-${String(sequence)}`; } });
    const entry = jobsContract(store, clock).find((item) => item.id === id);
    if (!entry) throw new Error(id);
    await entry.run();
  });

  it("lets one overlapping claim win and leaves the other occupied", async () => {
    await pool.query("DELETE FROM catalog_jobs");
    let sequence = 0;
    const store = createSqlJobStore(pool, { ids: () => { sequence += 1; return `job-race-${String(sequence)}`; } });
    const identity: JobIdentity = { actorId: "actor-a", environment: "preview", idempotencyKey: "race", bundleSha256: "c".repeat(64) };
    const [first, second] = await Promise.all([store.claim(identity, 60_000), store.claim(identity, 60_000)]);
    const statuses = [first.status, second.status].sort();
    expect(statuses).toEqual(["acquired", "occupied"]);
  });
});
