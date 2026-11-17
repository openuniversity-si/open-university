import { connectTooling, requiredEnv, safeErrorMessage } from "../fidelity/references/connect.ts";
import { applyToolingMigrations, readToolingMigrations, toolingMigrationStatus } from "./lib/migrations.ts";

// Owner role only: `pnpm tooling:migrate [--dry-run]` with TOWER_TOOLING_DATABASE_URL_OWNER.
const args = process.argv.slice(2);
if (args.some((arg) => arg !== "--dry-run")) throw new Error("Usage: pnpm tooling:migrate [--dry-run]");
const dryRun = args.includes("--dry-run");
try {
  const db = await connectTooling(requiredEnv("TOWER_TOOLING_DATABASE_URL_OWNER", "to migrate tower_tooling"), { readOnly: dryRun });
  try {
    const migrations = await readToolingMigrations();
    const status = dryRun ? await toolingMigrationStatus(db, migrations) : await applyToolingMigrations(db, migrations);
    console.log(JSON.stringify({ database: "tower_tooling", dryRun, ...status }));
    if (dryRun && status.pending > 0) process.exitCode = 1;
  } finally {
    await db.end();
  }
} catch (error) {
  console.error(`tooling:migrate: ${safeErrorMessage(error)}`);
  process.exitCode = 1;
}
