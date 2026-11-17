import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { applyToolingMigrations, readToolingMigrations, toolingMigrationStatus } from "../../scripts/lib/migrations.ts";
import { materializeActiveSet } from "./active.ts";
import { fakeFigma, fakePage } from "./fixtures.test-helpers.ts";
import { loadActiveReferenceSet, NoActiveReferenceSetError, type SqlClient } from "./repository.ts";
import { createFileSystemStorage } from "./storage.ts";
import { syncFidelityReferences } from "./sync.ts";

/** tower_tooling schema, sync and harness reads against a real Postgres, in a throwaway schema. */
const connectionString = process.env.TEST_DATABASE_URL;
const schema = `tooling_test_${String(process.pid)}_${String(Date.now())}`;

describe("tower_tooling fidelity references", () => {
  let client: pg.Client | undefined;
  let directory = "";
  const db: SqlClient = {
    query: async (text, values) => {
      if (!client) throw new Error("not connected");
      return client.query(text, values ? [...values] : []);
    },
  };
  const log = () => undefined;
  const database = <T>(work: (session: SqlClient) => Promise<T>) => work(db);

  beforeAll(async () => {
    if (!connectionString) throw new Error("TEST_DATABASE_URL is not set; pnpm test:int needs a real Postgres.");
    client = new pg.Client({ connectionString });
    await client.connect();
    await client.query(`CREATE SCHEMA ${schema}`);
    await client.query(`SET search_path TO ${schema}`);
    directory = await mkdtemp(path.join(tmpdir(), "tower-tooling-"));
  });

  afterAll(async () => {
    await client?.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);
    await client?.end();
  });

  it("applies the tooling migrations once and keeps an immutable ledger", async () => {
    const migrations = await readToolingMigrations();
    expect(await toolingMigrationStatus(db, migrations)).toEqual({ applied: 0, pending: migrations.length });
    expect(await applyToolingMigrations(db, migrations)).toEqual({ applied: migrations.length, pending: 0 });
    expect(await applyToolingMigrations(db, migrations)).toEqual({ applied: migrations.length, pending: 0 });
    const edited = migrations.map((migration) => ({ ...migration, sha256: "0".repeat(64) }));
    await expect(toolingMigrationStatus(db, edited)).rejects.toThrow(/immutable/);
  });

  it("fails clearly while no set is active", async () => {
    await expect(loadActiveReferenceSet(db)).rejects.toBeInstanceOf(NoActiveReferenceSetError);
  });

  it("dry-run exports and validates without uploading or writing", async () => {
    const result = await syncFidelityReferences({ figma: fakeFigma("100", fakePage()), database, storage: null, fileKey: "file", stagingDirectory: path.join(directory, "staging"), log });
    expect(result).toMatchObject({ status: "dry-run", images: 8, uploaded: 8, reused: 0, roots: { screen: 1, scroll: 1, state: 2 } });
    expect((await db.query("SELECT count(*)::int AS count FROM fidelity_reference_set")).rows[0]?.count).toBe(0);
  });

  it("syncs a version into storage and activates it atomically; re-running is a no-op", async () => {
    const storage = createFileSystemStorage(path.join(directory, "store"));
    const figma = fakeFigma("100", fakePage());
    const first = await syncFidelityReferences({ figma, database, storage, fileKey: "file", stagingDirectory: path.join(directory, "staging"), log });
    expect(first).toMatchObject({ status: "created", images: 8, uploaded: 8, reused: 0 });
    expect(figma.renders.count).toBe(0);
    const active = await loadActiveReferenceSet(db);
    expect(active.set).toMatchObject({ id: first.setId, figmaVersionId: "100", isActive: true });
    expect(active.images.map((image) => image.blobUrl).every((url) => url.includes("/fidelity/100/"))).toBe(true);
    expect(active.images.find((image) => image.screenKey === "home-mobile-390--29-399@2x")).toMatchObject({ viewport: "39@2x", width: 78, height: 168 });
    expect(active.nodes.find((node) => node.rootNodeId === "29:400" && node.nodeId === "29:401")).toMatchObject({ x: 0, y: 0, width: 39, height: 62 });
    expect(await syncFidelityReferences({ figma, database, storage, fileKey: "file", stagingDirectory: path.join(directory, "staging"), log })).toMatchObject({ status: "already-active", setId: first.setId });
  });

  it("activates newer versions, reuses unchanged renders, re-activates idempotently and prunes superseded sets", async () => {
    const store = path.join(directory, "store");
    const storage = createFileSystemStorage(store);
    const staging = path.join(directory, "staging");
    const sync = (version: string, shift: number, red?: number) => syncFidelityReferences({ figma: fakeFigma(version, fakePage(shift), red), database, storage, fileKey: "file", stagingDirectory: staging, log });
    const versions = async () => (await db.query("SELECT figma_version_id, is_active FROM fidelity_reference_set ORDER BY id")).rows;

    const moved = await sync("200", 4);
    expect(moved).toMatchObject({ status: "created", images: 8, reused: 8, uploaded: 0, pruned: { sets: 0, blobs: 0 } });
    const active = await loadActiveReferenceSet(db);
    expect(active.set.figmaVersionId).toBe("200");
    expect(active.nodes.find((node) => node.rootNodeId === "29:400" && node.nodeId === "29:401")?.y).toBe(4);
    expect(active.images.every((image) => image.blobUrl.includes("/fidelity/100/"))).toBe(true);

    // 100's blobs are still referenced by 200, so pruning 100 deletes rows only.
    expect(await sync("300", 0, 99)).toMatchObject({ status: "created", uploaded: 8, reused: 0, pruned: { sets: 1, blobs: 0 } });
    expect(await versions()).toEqual([{ figma_version_id: "200", is_active: false }, { figma_version_id: "300", is_active: true }]);
    expect(await sync("200", 4)).toMatchObject({ status: "activated-existing", pruned: { sets: 0, blobs: 0 } });
    expect(await versions()).toEqual([{ figma_version_id: "200", is_active: true }, { figma_version_id: "300", is_active: false }]);

    // 400 supersedes 200; 300 is the newest inactive and is kept; 200's blobs go with it.
    expect(await sync("400", 0, 50)).toMatchObject({ status: "created", uploaded: 8, pruned: { sets: 1, blobs: 8 } });
    expect(await versions()).toEqual([{ figma_version_id: "300", is_active: false }, { figma_version_id: "400", is_active: true }]);
    expect(await storage.head("fidelity/100/home-mobile-390--29-399@1x.png")).toBeNull();
    expect(await storage.head("fidelity/300/home-mobile-390--29-399@1x.png")).not.toBeNull();
  });

  it("enforces exactly one active set in the schema", async () => {
    await expect(db.query("UPDATE fidelity_reference_set SET is_active = true")).rejects.toThrow(/fidelity_reference_set_one_active/);
  });

  it("materializes the active set into the sha256 cache for the harness", async () => {
    const storage = createFileSystemStorage(path.join(directory, "store"));
    const cache = path.join(directory, "cache");
    const local = await materializeActiveSet(db, storage, cache, log);
    expect(Object.keys(local.files)).toHaveLength(8);
    expect(Object.values(local.files).every((file) => file.startsWith(cache))).toBe(true);
    const lines: string[] = [];
    await materializeActiveSet(db, storage, cache, (line) => lines.push(line));
    expect(lines[0]).toContain("(0 downloaded, 8 from cache)");
  });
});
