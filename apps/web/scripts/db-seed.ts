import { createDatabaseClient, type DatabaseClient } from "./lib/database-client.ts";
import { DatabaseToolError, parseTargetArgs, resolveDatabaseTarget, safeDatabaseError } from "./lib/database-target.ts";
import { seedDatabase } from "./lib/database-seed.ts";

let client: DatabaseClient | undefined;
try {
  const { target } = parseTargetArgs(process.argv.slice(2), false);
  if (target === "prod") throw new DatabaseToolError("Synthetic seed is restricted to container and staging.");
  client = createDatabaseClient(resolveDatabaseTarget(target));
  await client.connect();
  await seedDatabase(client);
  console.log(JSON.stringify({ target, syntheticUsers: 1, syntheticProgressRows: 2, courseBundles: 0 }));
} catch (error) {
  console.error(safeDatabaseError(error));
  process.exitCode = 1;
} finally {
  await client?.end();
}
