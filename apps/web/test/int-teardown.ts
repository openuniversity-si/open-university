import { randomBytes } from "node:crypto";
import pg from "pg";
import type { TestProject } from "vitest/node";
import { runMigrations } from "../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";

export interface IntegrationDatabase {
  readonly connectionString: string;
  readonly prefix: string;
  readonly template: string;
}

declare module "vitest" {
  export interface ProvidedContext { integrationDatabase: IntegrationDatabase }
}

/** No test shares a database, even when a file drops public and its migration ledger. */
export default async function setup(project: TestProject): Promise<() => Promise<void>> {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString) throw new Error("TEST_DATABASE_URL is required; no database mocks.");
  const url = validateDatabaseUrl(connectionString, "container");
  const prefix = `tower_test_g${randomBytes(8).toString("hex")}`;
  const template = `${prefix}t`;
  const admin = new pg.Client({ connectionString });
  await admin.connect();
  const cleanup = async () => {
    try {
      const { rows } = await admin.query<{ datname: string }>("SELECT datname FROM pg_database WHERE starts_with(datname, $1)", [prefix]);
      for (const { datname } of rows) {
        // Identifiers originate here, never from a target environment or user input.
        if (!/^tower_test_g[a-f0-9]{16}[tf][a-f0-9]*$/.test(datname)) throw new Error("Invalid integration database name");
        await admin.query(`DROP DATABASE "${datname}" WITH (FORCE)`);
      }
    } finally { await admin.end(); }
  };
  try {
    await admin.query(`CREATE DATABASE "${template}"`);
    url.pathname = `/${template}`;
    await runMigrations(url.toString(), false);
    project.provide("integrationDatabase", { connectionString, prefix, template });
  } catch (error) {
    await cleanup();
    throw error;
  }
  return cleanup;
}
