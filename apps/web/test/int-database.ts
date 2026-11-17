import { randomBytes } from "node:crypto";
import pg from "pg";
import { inject } from "vitest";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";

const { connectionString, prefix, template } = inject("integrationDatabase");
const url = validateDatabaseUrl(connectionString, "container");
const database = `${prefix}f${randomBytes(8).toString("hex")}`;
const admin = new pg.Client({ connectionString });
await admin.connect();
try { await admin.query(`CREATE DATABASE "${database}" TEMPLATE "${template}"`); }
finally { await admin.end(); }
url.pathname = `/${database}`;
const fileUrl = url.toString();
process.env.TEST_DATABASE_URL = fileUrl;
// CLI subprocesses must use this same file's database, rather than the launcher's shared container target.
process.env.APP_DATABASE_URL_CONTAINER_UNPOOLED = fileUrl;
// The migrated rows are the taxonomy. Copy them here so a reset can restore them without a code list (D-030).
const snapshot = new pg.Client({ connectionString: fileUrl });
await snapshot.connect();
try {
  await snapshot.query("CREATE SCHEMA tower_test");
  await snapshot.query("CREATE TABLE tower_test.subject_areas AS TABLE public.subject_areas");
  await snapshot.query("CREATE TABLE tower_test.subject_subareas AS TABLE public.subject_subareas");
} finally { await snapshot.end(); }
