import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import "../src/media/server/public-hosts.ts";
import { mediaPublicHost } from "../src/media/domain/types.ts";
import { mediaArgs, mediaConnection, mediaFailure, poolOfOne, MediaToolError, revalidateMedia, revalidationConfig } from "./lib/media-cli.ts";
import { applyUrlMap, copyObjects, indexLocalFiles, listAllMediaRows, mergeUrlMaps, planHostRewrite, planMigration, type UrlMap } from "./lib/media-migrate.ts";
import { createR2MediaStore } from "./lib/media-storage.ts";
import { hasR2Credentials } from "./lib/r2.ts";

// `pnpm media:migrate-r2 --target <t> (--dry-run | --apply | --revert | --rewrite-host) [--source <dir[:dir...]>] [--map <file>] [--no-revalidate] [--yes-prod]`
// --dry-run: read-only DB; plans copy + host rewrite; HEADs R2 only if credentials exist.
// --apply:   refuses if any sha256 (active or old) is missing locally; copies every object to R2 under the same
//            immutable key, writes the URL map, rewrites only the host in catalog_media (one
//            transaction), then revalidates the deployment.
// --copy-only: same refusal + copy as --apply, but writes no URL map and no DB rows (stage bytes before the deploy).
// --rewrite-host: the objects are ALREADY in the bucket (copied and sha-verified beforehand): HEADs every pathname there (refuses if one is missing), then rewrites only the URL host
//            of every row not on the public host, in one transaction, and revalidates. No local bytes needed.
// --revert:  restores the old URLs from the map (one transaction) and revalidates.
try {
  const { values, target } = mediaArgs({ "dry-run": { type: "boolean" }, apply: { type: "boolean" }, revert: { type: "boolean" }, "rewrite-host": { type: "boolean" }, source: { type: "string" }, map: { type: "string" }, "copy-only": { type: "boolean" }, "no-revalidate": { type: "boolean" }, "yes-prod": { type: "boolean" } });
  const modes = (["dry-run", "copy-only", "apply", "revert", "rewrite-host"] as const).filter((mode) => values[mode] === true);
  if (modes.length !== 1) throw new MediaToolError("Use exactly one of --dry-run, --copy-only, --apply, --revert, --rewrite-host.");
  const mode = modes[0];
  if (target === "prod" && mode !== "dry-run" && mode !== "copy-only" && values["yes-prod"] !== true) throw new MediaToolError("Prod writes need --yes-prod (Daniel's explicit OK).");
  const host = mediaPublicHost(process.env);
  const mapFile = path.resolve(typeof values.map === "string" ? values.map : `.media-migration/${target}-urlmap.json`);
  const sources = (typeof values.source === "string" ? values.source : process.env.TOWER_MEDIA_SOURCE_DIRS ?? ".fidelity-cache/media").split(":").filter(Boolean);
  const revalidation = mode !== "dry-run" && mode !== "copy-only" && values["no-revalidate"] !== true ? revalidationConfig(target) : null;
  const db = await mediaConnection(target, mode === "dry-run" || mode === "copy-only");
  try {
    if (mode === "revert") {
      if (!existsSync(mapFile)) throw new MediaToolError("No URL map to revert.");
      const map = JSON.parse(await readFile(mapFile, "utf8")) as UrlMap;
      const reverted = await applyUrlMap(poolOfOne(db), map.entries, "revert");
      if (revalidation) await revalidateMedia(revalidation);
      console.log(JSON.stringify({ target, mode, reverted, revalidated: Boolean(revalidation) }));
    } else if (mode === "rewrite-host") {
      const rows = await listAllMediaRows(db);
      const plan = planHostRewrite(rows, host);
      const store = createR2MediaStore(process.env, "rw");
      const missing: string[] = [];
      // R2 occasionally drops a connection (seen 3 in ~800 HEADs, 2026-10-14): retry a failed HEAD before giving up; a 404 is never retried.
      const head = async (pathname: string) => { for (let attempt = 1; ; attempt++) { try { return await store.head(pathname); } catch (error) { if (attempt >= 3) throw error; } } };
      for (const pathname of plan.pathnames) if (!(await head(pathname))) missing.push(pathname);
      const summary = { target, mode, host, rows: rows.length, objects: plan.pathnames.length, rewrites: plan.rewrites.length, missingInBucket: missing.length };
      if (missing.length) { console.error(JSON.stringify({ ...summary, missing: missing.slice(0, 10) })); throw new MediaToolError("Refusing to rewrite: objects are missing from the bucket."); }
      const previous = existsSync(mapFile) ? JSON.parse(await readFile(mapFile, "utf8")) as UrlMap : null;
      const merged = mergeUrlMaps(previous, { host, entries: plan.rewrites });
      await mkdir(path.dirname(mapFile), { recursive: true });
      await writeFile(`${mapFile}.tmp`, JSON.stringify(merged, null, 1)); await rename(`${mapFile}.tmp`, mapFile);
      const rewritten = await applyUrlMap(poolOfOne(db), plan.rewrites, "forward");
      if (revalidation) await revalidateMedia(revalidation);
      console.log(JSON.stringify({ ...summary, rewritten, map: path.relative(process.cwd(), mapFile), revalidated: Boolean(revalidation) }));
    } else {
      const rows = await listAllMediaRows(db);
      const local = await indexLocalFiles(sources);
      const plan = planMigration(rows, local, host);
      const summary = { target, mode, host, rows: plan.rows, objects: plan.objects.length, rewrites: plan.rewrites.length, missingLocal: plan.missing.length };
      if (plan.missing.length) {
        console.error(JSON.stringify({ ...summary, missingSha256: plan.missing }));
        throw new MediaToolError(`Refusing to run: ${String(plan.missing.length)} sha256 value(s) are not available locally.`);
      }
      if (mode === "dry-run") {
        let alreadyInR2: number | "unknown (no R2 credentials)" = "unknown (no R2 credentials)";
        if (hasR2Credentials(process.env, "ro")) {
          const store = createR2MediaStore(process.env, "ro");
          alreadyInR2 = 0;
          for (const object of plan.objects) if (await store.head(object.pathname)) alreadyInR2++;
        }
        console.log(JSON.stringify({ ...summary, alreadyInR2 }));
      } else if (mode === "copy-only") {
        const copied = await copyObjects(plan, createR2MediaStore(process.env, "rw"), rows);
        console.log(JSON.stringify({ ...summary, ...copied, rewritten: 0 }));
      } else {
        const copied = await copyObjects(plan, createR2MediaStore(process.env, "rw"), rows);
        const previous = existsSync(mapFile) ? JSON.parse(await readFile(mapFile, "utf8")) as UrlMap : null;
        const merged = mergeUrlMaps(previous, { host, entries: plan.rewrites });
        await mkdir(path.dirname(mapFile), { recursive: true });
        await writeFile(`${mapFile}.tmp`, JSON.stringify(merged, null, 1)); await rename(`${mapFile}.tmp`, mapFile);
        const rewritten = await applyUrlMap(poolOfOne(db), plan.rewrites, "forward");
        if (revalidation) await revalidateMedia(revalidation);
        console.log(JSON.stringify({ ...summary, ...copied, rewritten, map: path.relative(process.cwd(), mapFile), revalidated: Boolean(revalidation) }));
      }
    }
  } finally { await db.end(); }
} catch (error) { mediaFailure(error); }
