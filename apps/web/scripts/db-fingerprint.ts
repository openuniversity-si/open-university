import { createHash } from "node:crypto";
import { createDatabaseClient, queryDatabase } from "./lib/database-client.ts";
import { migrationStatus } from "./lib/migrations.ts";
import { parseTargetArgs, resolveDatabaseTarget, safeDatabaseError } from "./lib/database-target.ts";

// Read-only schema + migration-ledger fingerprint. gate-db compares it around a second migration run (idempotency).
const FINGERPRINT_SQL = `
SELECT format('column %s.%s.%s %s %s %s', table_schema, table_name, column_name, data_type, is_nullable, column_default) AS line
  FROM information_schema.columns WHERE table_schema IN ('public', 'drizzle')
UNION ALL SELECT format('index %s.%s %s', schemaname, indexname, indexdef) FROM pg_indexes WHERE schemaname IN ('public', 'drizzle')
UNION ALL SELECT format('constraint %s %s %s', conrelid::regclass, conname, pg_get_constraintdef(oid))
  FROM pg_constraint WHERE connamespace::regnamespace::text IN ('public', 'drizzle')
UNION ALL SELECT format('enum %s %s %s', t.typname, e.enumsortorder, e.enumlabel)
  FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typnamespace::regnamespace::text = 'public'
UNION ALL SELECT format('view %s %s', viewname, definition) FROM pg_views WHERE schemaname = 'public'
UNION ALL SELECT format('trigger %s %s', tgrelid::regclass, pg_get_triggerdef(oid)) FROM pg_trigger t
  WHERE NOT tgisinternal AND tgrelid::regclass::text NOT LIKE 'pg_%'
UNION ALL SELECT format('function %s', pg_get_functiondef(p.oid)) FROM pg_proc p
  WHERE p.pronamespace::regnamespace::text = 'public' AND p.prokind IN ('f', 'p')`;

try {
  const { target } = parseTargetArgs(process.argv.slice(2), false);
  const client = createDatabaseClient(resolveDatabaseTarget(target));
  await client.connect();
  try {
    await queryDatabase(client, "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    const status = await migrationStatus(client);
    const ledger = status.applied ? (await queryDatabase<{ line: string }>(client,
      "SELECT format('migration %s %s', hash, created_at) AS line FROM drizzle.__drizzle_migrations")).rows : [];
    const lines = [...(await queryDatabase<{ line: string }>(client, FINGERPRINT_SQL)).rows, ...ledger].map((row) => row.line).sort();
    await queryDatabase(client, "ROLLBACK");
    const sha256 = createHash("sha256").update(lines.join("\n")).digest("hex");
    console.log(JSON.stringify({ target, ...status, objects: lines.length, sha256 }));
  } finally {
    await client.end();
  }
} catch (error) {
  console.error(safeDatabaseError(error));
  process.exitCode = 1;
}
