import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { readMigrationFiles } from "drizzle-orm/migrator";
import { drizzle } from "drizzle-orm/node-postgres";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import { DatabaseToolError } from "./database-target.ts";
import { createDatabaseClient, queryDatabase, type DatabaseClient } from "./database-client.ts";
import { sha256 } from "../../fidelity/references/storage.ts";
import type { SqlClient } from "../../fidelity/references/repository.ts";
import type { Queryable } from "../../src/platform/db/uow.ts";

export const migrationsFolder = fileURLToPath(new URL("../../drizzle", import.meta.url));
export const toolingMigrationsFolder = fileURLToPath(new URL("../../tooling/migrations", import.meta.url));
interface Migration { readonly id: string; readonly checksum: string }
export interface MigrationLedger {
  readonly name: "app" | "tooling";
  readonly lock: readonly [742019, 1] | readonly [742019, 2];
  files(): Promise<readonly Migration[]>;
  applied(db: Queryable): Promise<readonly Migration[]>;
  apply(db: Queryable, pending: readonly { readonly id: string }[]): Promise<void>;
}

function historyDiffers(ledger: MigrationLedger): Error {
  // Keep the sentences the existing operators and integration tests already match.
  if (ledger.name === "app") return new DatabaseToolError("Migration history differs from versioned SQL. Stop and investigate; applied migrations are immutable.");
  return new Error("tower_tooling migration history differs from tooling/migrations. Applied migrations are immutable; investigate.");
}
async function history(ledger: MigrationLedger, db: Queryable) {
  const files = await ledger.files();
  const applied = await ledger.applied(db);
  if (applied.length > files.length || applied.some((row, i) => row.id !== files[i]?.id || row.checksum !== files[i].checksum)) throw historyDiffers(ledger);
  return { files, count: applied.length };
}
export async function ledgerStatus(ledger: MigrationLedger, db: Queryable): Promise<{ applied: number; pending: number }> {
  const { files, count } = await history(ledger, db);
  return { applied: count, pending: files.length - count };
}

/** The caller owns one connected session, including the session lock, until it closes it. */
export async function runLedger(ledger: MigrationLedger, db: Queryable, options: { readonly dryRun: boolean }): Promise<{ applied: number; pending: number }> {
  if (options.dryRun) {
    await db.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    try { return await ledgerStatus(ledger, db); }
    finally { await db.query("ROLLBACK"); }
  }
  // Keep both deployed lock identities exactly; each ledger lives in its own database.
  await db.query(ledger.lock[1] === 1 ? "SELECT pg_advisory_lock(742019, 1)" : "SELECT pg_advisory_lock(742019, 2)");
  const { files, count } = await history(ledger, db);
  await ledger.apply(db, files.slice(count));
  return ledgerStatus(ledger, db);
}

export const drizzleLedger: MigrationLedger = {
  name: "app", lock: [742019, 1],
  files() { return Promise.resolve(readMigrationFiles({ migrationsFolder }).map((file) => ({ id: String(file.folderMillis), checksum: file.hash }))); },
  async applied(db) {
    const exists = await db.query("SELECT to_regclass('drizzle.__drizzle_migrations')::text AS relation");
    const rows = exists.rows[0]?.relation ? (await db.query("SELECT hash, created_at FROM drizzle.__drizzle_migrations ORDER BY created_at, id")).rows : [];
    // folderMillis is a number; node-pg returns the bigint ledger column as text. Compare the same way the previous runner did.
    return rows.map((row) => ({ id: String(Number(row.created_at)), checksum: String(row.hash) }));
  },
  async apply(db) {
    // The adapter below retains its actual pg session for the driver's migrator.
    await migrate(drizzle((db as MigrationSession).client), { migrationsFolder });
  },
};
interface MigrationSession extends Queryable { readonly client: DatabaseClient }
function appSession(client: DatabaseClient): MigrationSession {
  return { client, query: (sql, values) => queryDatabase(client, sql, values) };
}
export const migrationStatus = (client: DatabaseClient) => ledgerStatus(drizzleLedger, appSession(client));
export async function runMigrations(connectionString: string, dryRun: boolean): Promise<{ applied: number; pending: number }> {
  const client = createDatabaseClient(connectionString);
  try {
    await client.connect();
    return await runLedger(drizzleLedger, appSession(client), { dryRun });
  } finally { await client.end(); }
}

/** Applied rows and the checkout's files. Read-only. Does not apply and does not print the URI. */
export async function migrationLedger(connectionString: string): Promise<{ applied: { id: string; checksum: string }[]; files: { id: string; checksum: string }[] }> {
  const client = createDatabaseClient(connectionString);
  try {
    await client.connect();
    const session = appSession(client);
    await session.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    try {
      const files = await drizzleLedger.files();
      const applied = await drizzleLedger.applied(session);
      return { applied: applied.map((row) => ({ id: row.id, checksum: row.checksum })), files: files.map((row) => ({ id: row.id, checksum: row.checksum })) };
    } finally {
      await session.query("ROLLBACK");
    }
  } finally { await client.end(); }
}

export interface ToolingMigration { readonly name: string; readonly sql: string; readonly sha256: string }
export async function readToolingMigrations(folder = toolingMigrationsFolder): Promise<ToolingMigration[]> {
  const names = (await readdir(folder)).filter((name) => name.endsWith(".sql")).sort();
  return Promise.all(names.map(async (name) => {
    const sql = await readFile(`${folder}/${name}`, "utf8");
    return { name, sql, sha256: sha256(Buffer.from(sql)) };
  }));
}
export function toolingLedger(migrations?: readonly ToolingMigration[]): MigrationLedger {
  const load = () => migrations ? Promise.resolve(migrations) : readToolingMigrations();
  return {
    name: "tooling", lock: [742019, 2],
    async files() { return (await load()).map((file) => ({ id: file.name, checksum: file.sha256 })); },
    async applied(db) {
      const exists = await db.query("SELECT to_regclass('tooling_migration')::text AS relation");
      const rows = exists.rows[0]?.relation ? (await db.query("SELECT name, sha256 FROM tooling_migration ORDER BY name")).rows : [];
      return rows.map((row) => ({ id: String(row.name), checksum: String(row.sha256) }));
    },
    async apply(db, pending) {
      await db.query(`CREATE TABLE IF NOT EXISTS tooling_migration (
        name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
      )`);
      const files = await load();
      for (const { id } of pending) {
        const file = files.find((file) => file.name === id);
        if (!file) throw new DatabaseToolError("Missing tooling migration.");
        await db.query("BEGIN");
        try {
          await db.query(file.sql);
          await db.query("INSERT INTO tooling_migration (name, sha256) VALUES ($1, $2)", [file.name, file.sha256]);
          await db.query("COMMIT");
        } catch (error) {
          await db.query("ROLLBACK");
          throw error;
        }
      }
    },
  };
}
function isRow(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function rowsOf(value: unknown): readonly Record<string, unknown>[] {
  if (typeof value !== "object" || value === null || !("rows" in value) || !Array.isArray(value.rows)) return [];
  return value.rows.filter(isRow);
}
function queryRows(result: unknown): readonly Record<string, unknown>[] {
  // node-pg returns one result, or an array of results when the SQL has several statements.
  return Array.isArray(result) ? result.flatMap(rowsOf) : rowsOf(result);
}
function toolingSession(db: SqlClient): Queryable {
  return { query: async (sql, values) => ({ rows: [...queryRows(await db.query(sql, values))] }) };
}
export const toolingMigrationStatus = (db: SqlClient, migrations: readonly ToolingMigration[]) => ledgerStatus(toolingLedger(migrations), toolingSession(db));
export const applyToolingMigrations = (db: SqlClient, migrations: readonly ToolingMigration[]) => runLedger(toolingLedger(migrations), toolingSession(db), { dryRun: false });
