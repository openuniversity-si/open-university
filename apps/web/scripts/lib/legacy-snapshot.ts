import { queryDatabase, type DatabaseClient } from "./database-client.ts";

export interface LegacyTableSnapshot { schema: string; table: string; rows: string }
export interface LegacySnapshot { database: string; tables: LegacyTableSnapshot[] }

function quoteIdentifier(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export async function snapshotLegacyDatabase(client: DatabaseClient): Promise<LegacySnapshot> {
  // The driver also sets default_transaction_read_only; this transaction keeps
  // every exact count on a single consistent snapshot. No DDL or DML is issued.
  await queryDatabase(client, "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
  try {
    const database = (await queryDatabase<{ database: string }>(client, "SELECT current_database() AS database")).rows[0]?.database;
    if (!database) throw new Error("Database identity unavailable.");
    const tables = await queryDatabase<{ schema: string; table: string }>(client,
      "SELECT schemaname AS schema, tablename AS table FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') AND schemaname NOT LIKE 'pg_toast%' ORDER BY schemaname, tablename",
    );
    const snapshot: LegacyTableSnapshot[] = [];
    for (const table of tables.rows) {
      const result = await queryDatabase<{ count: string }>(client, `SELECT count(*)::text AS count FROM ${quoteIdentifier(table.schema)}.${quoteIdentifier(table.table)}`);
      const count = result.rows[0]?.count;
      if (count === undefined) throw new Error("Row count unavailable.");
      snapshot.push({ ...table, rows: count });
    }
    return { database, tables: snapshot };
  } finally {
    await queryDatabase(client, "ROLLBACK");
  }
}

export function compareLegacySnapshots(before: LegacySnapshot, after: LegacySnapshot): boolean {
  return JSON.stringify(before) === JSON.stringify(after);
}

export function parseLegacySnapshot(value: unknown): LegacySnapshot {
  if (typeof value !== "object" || value === null || !("database" in value) || typeof value.database !== "string" || !("tables" in value) || !Array.isArray(value.tables)) {
    throw new Error("Invalid legacy snapshot.");
  }
  const tables = value.tables.map((entry: unknown) => {
    if (typeof entry !== "object" || entry === null || !("schema" in entry) || typeof entry.schema !== "string" || !("table" in entry) || typeof entry.table !== "string" || !("rows" in entry) || typeof entry.rows !== "string" || !/^\d+$/.test(entry.rows)) {
      throw new Error("Invalid legacy table snapshot.");
    }
    return { schema: entry.schema, table: entry.table, rows: entry.rows };
  });
  return { database: value.database, tables };
}
