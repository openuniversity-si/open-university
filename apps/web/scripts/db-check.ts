import { cpSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { migrationsFolder } from "./lib/migrations.ts";

// drizzle-kit check validates history. Generate against a temporary copy also
// proves the TypeScript schema matches the committed migration snapshot.
const temporary = mkdtempSync(join(tmpdir(), "tower-db-check-"));
try {
  const out = join(temporary, "drizzle");
  cpSync(migrationsFolder, out, { recursive: true });
  const before = readdirSync(out).filter((name) => name.endsWith(".sql")).sort();
  const config = join(temporary, "drizzle.config.ts");
  writeFileSync(config, `export default ${JSON.stringify({ dialect: "postgresql", schema: fileURLToPath(new URL("../src/platform/db/schema.ts", import.meta.url)), out: relative(process.cwd(), out) })};\n`);
  const result = spawnSync("pnpm", ["exec", "drizzle-kit", "generate", "--config", config], { encoding: "utf8" });
  if (result.status !== 0 || !result.stdout.includes("No schema changes, nothing to migrate")) throw new Error("Drizzle schema verification failed or detected a schema change.");
  const after = readdirSync(out).filter((name) => name.endsWith(".sql")).sort();
  if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error("Schema drift: generate and commit a migration before proceeding.");
  console.log(`Schema matches migration snapshot; ${String(before.length)} migration(s), 0 drift.`);
} catch (error) {
  console.error(error instanceof Error ? error.message : "Database check failed.");
  process.exitCode = 1;
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
