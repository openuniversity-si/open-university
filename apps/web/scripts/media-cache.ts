import { parseArgs } from "node:util";
import { readFile, writeFile, rename } from "node:fs/promises";
import { snapshotCatalog } from "../src/catalog/testing/fake.ts";
import { mediaGaps } from "./lib/media-check.ts";
import { listActiveMedia } from "../src/media/server/repository.ts";
import { assetSchema } from "../src/media/domain/types.ts";
import { mediaConnection, mediaFailure, MediaToolError } from "./lib/media-cli.ts";
import { targetVariables, type DatabaseTarget } from "./lib/database-target.ts";
import { optionalReadStore } from "./lib/media-storage.ts";
import { cacheMedia } from "./lib/media-cache.ts";

// Snapshot descriptors are public, versioned test data; bytes always come from the real media origin.
try {
  const { values } = parseArgs({ options: { from: { type: "string" }, target: { type: "string" }, offline: { type: "boolean" }, "export-fixtures": { type: "boolean" } } });
  if (values.from && values.from !== "snapshot") throw new MediaToolError("Use --from snapshot or --target <database>.");
  if (values.from && values.target) throw new MediaToolError("Choose one media inventory source.");
  if (!values.from && (!values.target || !Object.hasOwn(targetVariables, values.target))) throw new MediaToolError("Use --from snapshot or an explicit --target <database>.");
  if (values["export-fixtures"] && (!values.target || values.offline)) throw new MediaToolError("Fixture export requires an explicit read-only database --target.");
  const db = values.target ? await mediaConnection(values.target as DatabaseTarget, true) : undefined;
  try {
    const assets = db ? await listActiveMedia(db) : assetSchema.array().parse(JSON.parse(await readFile(new URL("../content/media-fixtures.json", import.meta.url), "utf8")) as unknown);
    if (values["export-fixtures"]) {
      const owners = new Set([...snapshotCatalog.courses, ...snapshotCatalog.lessons].map((owner) => owner.id));
      const fixtures = assets.filter((asset) => owners.has(asset.ownerId));
      if (mediaGaps(fixtures).length) throw new MediaToolError("Fixture export requires a complete active set.");
      const file = new URL("../content/media-fixtures.json", import.meta.url);
      const temporary = new URL("../content/media-fixtures.json.partial", import.meta.url);
      await writeFile(temporary, `${JSON.stringify(fixtures, null, 2)}\n`);
      await rename(temporary, file);
      console.log(JSON.stringify({ source: values.target, exported: fixtures.length }));
    } else {
      const counts = await cacheMedia(assets, { offline: values.offline, store: values.from || values.offline ? undefined : optionalReadStore() });
      console.log(JSON.stringify({ source: values.from ?? values.target, ...counts }));
    }
  } finally { await db?.end(); }
} catch (error) { mediaFailure(error); }
