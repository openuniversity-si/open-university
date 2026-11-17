import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { connectTooling, requiredEnv, safeErrorMessage } from "../fidelity/references/connect.ts";
import { R2_FIDELITY_BUCKET_DEFAULT, sha256 } from "../fidelity/references/storage.ts";
import { createS3Bucket, r2Config } from "./lib/r2.ts";

// `pnpm fidelity:migrate-r2 (--dry-run | --apply) [--source <dir[:dir...]>]`
// Copies the private fidelity store from LOCAL caches into R2 `the-tower-fidelity` (no Blob reads):
//  - reference PNGs: every fidelity_reference_image row (tooling DB, read-only role) whose sha256 is cached
//    locally as <sha256>.png, under the key of its recorded Blob pathname (so no tooling DB rewrite is needed);
//  - companion mask art: <digest>.png files under media-masks dirs → media-mask-art/<digest>.png.
// Refuses unless every image of the ACTIVE set is local. Superseded sets may be partial (regenerable from Figma).
const args = process.argv.slice(2);
const mode = args[0];
const sourceIndex = args.indexOf("--source");
if (!["--dry-run", "--apply"].includes(mode ?? "") || (args.length !== 1 && !(args.length === 3 && sourceIndex === 1))) throw new Error("Usage: pnpm fidelity:migrate-r2 (--dry-run | --apply) [--source <dir[:dir...]>]");
const sources = (sourceIndex === 1 ? args[2] ?? "" : process.env.TOWER_FIDELITY_SOURCE_DIRS ?? ".fidelity-cache").split(":").filter(Boolean);
try {
  const references = new Map<string, string>();
  const masks = new Map<string, string>();
  async function walk(directory: string): Promise<void> {
    let entries;
    try { entries = await readdir(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(file);
      else if (/^[a-f0-9]{64}\.png$/.test(entry.name)) (path.basename(directory) === "media-masks" ? masks : references).set(entry.name.slice(0, 64), file);
    }
  }
  for (const source of sources) await walk(path.resolve(source));
  const db = await connectTooling(requiredEnv("TOWER_TOOLING_DATABASE_URL", "to read fidelity reference rows (read-only role)"), { readOnly: true });
  let rows;
  try {
    rows = (await db.query("SELECT DISTINCT i.blob_url, i.sha256, s.is_active FROM fidelity_reference_image i JOIN fidelity_reference_set s ON s.id = i.set_id")).rows.map((row) => ({ url: String(row.blob_url), sha: String(row.sha256), active: row.is_active === true }));
  } finally { await db.end(); }
  const missingActive = rows.filter((row) => row.active && !references.has(row.sha)).length;
  const objects = new Map<string, string>();
  for (const row of rows) { const file = references.get(row.sha); if (file) objects.set(new URL(row.url).pathname.slice(1).split("/").map(decodeURIComponent).join("/"), file); }
  for (const [digest, file] of masks) objects.set(`media-mask-art/${digest}.png`, file);
  const summary = { mode, referenceRows: rows.length, activeRows: rows.filter((row) => row.active).length, missingActive, missingInactive: rows.filter((row) => !row.active && !references.has(row.sha)).length, maskArt: masks.size, objects: objects.size };
  if (missingActive) throw new Error(`Refusing: ${String(missingActive)} active reference image(s) are not cached locally. ${JSON.stringify(summary)}`);
  if (mode === "--dry-run") console.log(JSON.stringify(summary));
  else {
    const bucket = createS3Bucket(r2Config(process.env, process.env.R2_FIDELITY_BUCKET ?? R2_FIDELITY_BUCKET_DEFAULT, "rw"));
    let uploaded = 0, present = 0;
    for (const [key, file] of objects) {
      const bytes = await readFile(file);
      if (path.basename(path.dirname(file)) !== "media-masks" && sha256(bytes) !== path.basename(file, ".png")) throw new Error(`Local reference ${path.basename(file)} is corrupt.`);
      const existing = await bucket.head(key);
      if (existing?.size === bytes.length) { present++; continue; }
      await bucket.put(key, bytes, { contentType: "image/png", overwrite: true }); uploaded++;
    }
    console.log(JSON.stringify({ ...summary, uploaded, present }));
  }
} catch (error) {
  console.error(`fidelity:migrate-r2: FAIL — ${safeErrorMessage(error)}`);
  process.exitCode = 1;
}
