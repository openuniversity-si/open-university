import { parseTargetArgs, resolveDatabaseTarget, safeDatabaseError } from "./lib/database-target.ts";
import { migrationLedger, runMigrations } from "./lib/migrations.ts";

try {
  const args = process.argv.slice(2);
  const ledger = args.includes("--ledger");
  const { target, dryRun } = parseTargetArgs(args.filter((arg) => arg !== "--ledger"));
  if (ledger) {
    console.log(JSON.stringify(await migrationLedger(resolveDatabaseTarget(target))));
  } else {
    const status = await runMigrations(resolveDatabaseTarget(target), dryRun);
    console.log(JSON.stringify({ target, dryRun, ...status }));
    if (dryRun && status.pending > 0) process.exitCode = 1;
  }
} catch (error) {
  console.error(safeDatabaseError(error));
  process.exitCode = 1;
}
