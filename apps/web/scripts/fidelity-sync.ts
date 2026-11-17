import { requiredEnv, safeErrorMessage, toolingSessions } from "../fidelity/references/connect.ts";
import { createFigmaClient, specFileKey } from "../fidelity/references/figma.ts";
import { referenceStorageFromEnv } from "../fidelity/references/storage.ts";
import { syncFidelityReferences } from "../fidelity/references/sync.ts";

// Orchestrator routine, never CI: `pnpm fidelity:sync [--dry-run]`.
// Needs FIGMA_TOKEN (read-only PAT), TOWER_TOOLING_DATABASE_URL_OWNER and, unless --dry-run,
// a storage write credential (R2_ACCESS_KEY_ID_RW/R2_SECRET_ACCESS_KEY_RW with R2_ACCOUNT_ID). Values are never printed.
const args = process.argv.slice(2);
if (args.some((arg) => arg !== "--dry-run")) throw new Error("Usage: pnpm fidelity:sync [--dry-run]");
const dryRun = args.includes("--dry-run");
try {
  const figma = createFigmaClient(requiredEnv("FIGMA_TOKEN", "to export Figma references (read-only PAT)"));
  const storage = dryRun ? null : referenceStorageFromEnv(process.env, "rw");
  if (!dryRun && !storage) throw new Error("A fidelity storage write credential is required (R2_ACCESS_KEY_ID_RW/R2_SECRET_ACCESS_KEY_RW with R2_ACCOUNT_ID).");
  const database = toolingSessions(requiredEnv("TOWER_TOOLING_DATABASE_URL_OWNER", "to record the reference set (owner role)"), { readOnly: dryRun });
  const result = await syncFidelityReferences({ figma, database, storage, fileKey: specFileKey(), stagingDirectory: ".fidelity-cache/sync", log: console.log });
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(`fidelity:sync: FAIL — ${safeErrorMessage(error)}`);
  process.exitCode = 1;
}
