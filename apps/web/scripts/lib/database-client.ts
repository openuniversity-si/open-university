import pg from "pg";
import { drizzle as drizzlePostgres } from "drizzle-orm/node-postgres";

// Operations scripts reach PostgreSQL over its standard protocol, with the same driver as the application.
export type DatabaseClient = pg.Client;

export function createDatabaseClient(connectionString: string, readOnly = false): DatabaseClient {
  return new pg.Client({
    connectionString,
    connectionTimeoutMillis: 10_000,
    statement_timeout: 60_000,
    ...(readOnly ? { options: "-c default_transaction_read_only=on" } : {}),
  });
}

export function databaseForClient(client: DatabaseClient) {
  return drizzlePostgres(client);
}

// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters -- Callers specify SQL result-row types, matching the driver's generic query contract.
export async function queryDatabase<Row extends Record<string, unknown> = Record<string, unknown>>(client: DatabaseClient, sql: string, values: readonly unknown[] = []): Promise<{ rows: Row[]; rowCount: number }> {
  const result = await client.query<Row>(sql, [...values]);
  return { rows: result.rows, rowCount: result.rowCount ?? 0 };
}
