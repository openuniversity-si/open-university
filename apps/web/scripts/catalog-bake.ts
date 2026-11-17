import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { bakedReleaseSchema, type BakedRelease } from "../src/catalog/domain/baked.ts";
import { parseStoredRelease } from "../src/catalog/domain/release.ts";
import { releaseSha } from "../src/kernel/sha.ts";
import { appRoot, readJson, writeJson } from "./lib/catalog-files.ts";
import { syntheticCatalog } from "../src/catalog/testing/synthetic.ts";
import { createDatabaseClient, queryDatabase } from "./lib/database-client.ts";
import { DatabaseToolError, parseTargetArgs, resolveDatabaseTarget, safeDatabaseError } from "./lib/database-target.ts";

// pnpm catalog:bake [--from fixture | --target <target>] [--if-missing]
// Writes src/catalog/domain/generated/release.json (ADR-17). Default source: the database in APP_DATABASE_URL(_UNPOOLED) (hosted builds)
// and, without one (CI, test builds), the versioned fixture. A database that is configured but unreadable fails the build.
const output = resolve(appRoot, "src/catalog/domain/generated/release.json");

async function readActive(connectionString: string): Promise<BakedRelease> {
  // A single SELECT; no read-only startup `options`, which a connection pooler may refuse.
  const client = createDatabaseClient(connectionString);
  await client.connect();
  try {
    const { rows: [row] } = await queryDatabase<{ payload: unknown; payload_sha256: string }>(client, "SELECT payload, payload_sha256 FROM catalog_releases WHERE is_active");
    if (!row) throw new DatabaseToolError("The database has no active catalog release.");
    const release = parseStoredRelease(row.payload);
    if (releaseSha(release) !== row.payload_sha256) throw new DatabaseToolError(`Release #${String(release.number)} differs from its payload_sha256.`);
    return { source: "database", sha: row.payload_sha256, release };
  } finally {
    await client.end();
  }
}

try {
  const args = process.argv.slice(2);
  const ifMissing = args.includes("--if-missing");
  const fromFixture = args.includes("--from") && args[args.indexOf("--from") + 1] === "fixture";
  const rest = args.filter((arg, index) => arg !== "--if-missing" && !(fromFixture && (arg === "--from" || args[index - 1] === "--from")));
  if (!(ifMissing && existsSync(output) && bakedReleaseSchema.safeParse(readJson(output)).success)) {
    const target = rest.length > 0 ? parseTargetArgs(rest, false).target : undefined;
    const testBuild = process.env.TOWER_BUILD_TARGET === "test";
    const connectionString = fromFixture || testBuild ? undefined : target ? resolveDatabaseTarget(target) : process.env.APP_DATABASE_URL_UNPOOLED ?? process.env.APP_DATABASE_URL;
    let baked: BakedRelease;
    if (connectionString) baked = await readActive(connectionString);
    else {
      const release = syntheticCatalog;
      baked = { source: "fixture", sha: releaseSha(release), release };
    }
    mkdirSync(dirname(output), { recursive: true });
    writeJson(output, bakedReleaseSchema.parse(baked));
    const { release } = baked;
    console.log(`catalog:bake: release #${String(release.number)} (sha256 ${baked.sha.slice(0, 12)}) from ${baked.source}${target ? ` ${target}` : ""}: ${String(release.courses.length)} courses, ${String(release.lessons.length)} lessons.`);
  }
} catch (error) {
  console.error(error instanceof DatabaseToolError ? error.message : error instanceof Error && !("code" in error) ? error.message : safeDatabaseError(error));
  process.exitCode = 1;
}
