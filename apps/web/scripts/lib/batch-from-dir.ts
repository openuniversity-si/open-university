import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { batchFromBundlesV1, type Converted, type V1Entry } from "../../src/catalog/domain/batch-convert.ts";
import { validateCourseBundle } from "../../src/catalog/domain/bundle.ts";
import { prepareMedia } from "../../src/media/server/prepare.ts";

/**
 * Read a v1 bundles directory (`*.json`, covers relative to each bundle) into a CatalogBatchV2. Cover content addresses
 * are those of the prepared bytes, exactly what `tower-media` uploads. `rowInstitutions` comes from the catalog (GET /home).
 */
export async function batchFromDirectory(directory: string, rowInstitutions: ReadonlyMap<string, string>): Promise<Converted> {
  const failures: string[] = [];
  const entries: V1Entry[] = [];
  for (const name of readdirSync(directory).filter((file) => file.endsWith(".json")).sort()) {
    const file = join(directory, name);
    const parsed = validateCourseBundle(JSON.parse(readFileSync(file, "utf8")) as unknown);
    if (!parsed.ok) { failures.push(`${name}: ${parsed.error.message}`); continue; }
    const coverShas: Record<string, string> = {};
    for (const cover of parsed.value.covers) {
      try { coverShas[cover.kind] = (await prepareMedia(join(dirname(file), cover.path))).sha256; }
      catch (error) { failures.push(`${name}: cover ${cover.path}: ${error instanceof Error ? error.message : "unreadable"}`); }
    }
    entries.push({ file: name, bundle: parsed.value, coverShas });
  }
  const converted = batchFromBundlesV1(entries, rowInstitutions);
  return failures.length === 0 ? converted : { ok: false, failures: [...failures, ...(converted.ok ? [] : converted.failures)] };
}
