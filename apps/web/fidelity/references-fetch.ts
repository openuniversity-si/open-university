import { connectTooling, requiredEnv, safeErrorMessage } from "./references/connect.ts";
import { DEFAULT_CACHE_DIRECTORY, materializeActiveSet, writeLocalSet } from "./references/active.ts";
import { loadActiveReferenceSet } from "./references/repository.ts";
import { referenceStorageFromEnv } from "./references/storage.ts";

// `pnpm fidelity:references [--resolve]`: read the active set with the read-only role, verify every
// image into the sha256 cache, and write the local manifest the harness reads.
// `--resolve` only prints `set-id=<id>` and `figma-version-id=<id>` (CI cache key); no download.
const resolveOnly = process.argv.slice(2).join(" ") === "--resolve";
if (process.argv.length > 2 && !resolveOnly) throw new Error("Usage: pnpm fidelity:references [--resolve]");
try {
  const db = await connectTooling(requiredEnv("TOWER_TOOLING_DATABASE_URL", "to read the active fidelity reference set (read-only role)"), { readOnly: true });
  try {
    if (resolveOnly) {
      const { set } = await loadActiveReferenceSet(db);
      console.log(`set-id=${set.id}\nfigma-version-id=${set.figmaVersionId}`);
    } else {
      const storage = referenceStorageFromEnv(process.env, "ro");
      if (!storage) throw new Error("A fidelity storage read credential is required (R2_ACCESS_KEY_ID_RO/R2_SECRET_ACCESS_KEY_RO, or the RW pair, with R2_ACCOUNT_ID).");
      const directory = process.env.TOWER_FIDELITY_CACHE_DIR ?? DEFAULT_CACHE_DIRECTORY;
      await writeLocalSet(await materializeActiveSet(db, storage, directory, console.log));
    }
  } finally {
    await db.end();
  }
} catch (error) {
  console.error(`fidelity:references: FAIL — ${safeErrorMessage(error)}`);
  process.exitCode = 1;
}
