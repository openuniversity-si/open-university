import { readFileSync, writeFileSync } from "node:fs";
import { createDatabaseClient, type DatabaseClient } from "./lib/database-client.ts";
import { DatabaseToolError, safeDatabaseError } from "./lib/database-target.ts";
import { compareLegacySnapshots, parseLegacySnapshot, snapshotLegacyDatabase } from "./lib/legacy-snapshot.ts";

let client: DatabaseClient | undefined;
try {
  const args = process.argv.slice(2);
  const output = args[1];
  const compare = args.length === 4 && args[2] === "--compare" ? args[3] : undefined;
  if (args[0] !== "--output" || !output || !(args.length === 2 || (args.length === 4 && compare))) {
    throw new DatabaseToolError("Use --output <file> [--compare <before-file>].");
  }
  const connectionString = process.env.APP_LEGACY_DATABASE_URL_UNPOOLED;
  if (!connectionString) throw new DatabaseToolError("Missing APP_LEGACY_DATABASE_URL_UNPOOLED; obtain read-only access from Daniel.");
  client = createDatabaseClient(connectionString, true);
  await client.connect();
  const snapshot = await snapshotLegacyDatabase(client);
  writeFileSync(output, JSON.stringify(snapshot, null, 2) + "\n", { mode: 0o600 });
  if (compare) {
    const before = parseLegacySnapshot(JSON.parse(readFileSync(compare, "utf8")) as unknown);
    if (!compareLegacySnapshots(before, snapshot)) throw new DatabaseToolError("Legacy table list or row counts changed. Investigate before completing F02.");
  }
  console.log(JSON.stringify({ tables: snapshot.tables.length, comparison: compare ? "unchanged" : "baseline captured" }));
} catch (error) {
  console.error(safeDatabaseError(error));
  process.exitCode = 1;
} finally {
  await client?.end();
}
