import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { BetterAuthOptions } from "better-auth";
import type pg from "pg";
import { describe, expect, it } from "vitest";
import type { SessionDatabase } from "./session-database.ts";

const webRoot = fileURLToPath(new URL("../../../", import.meta.url));

function productionSources(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "testing") continue;
      found.push(...productionSources(path));
      continue;
    }
    if (!entry.name.endsWith(".ts") && !entry.name.endsWith(".tsx")) continue;
    if (entry.name.includes(".test.")) continue;
    found.push(path);
  }
  return found;
}

describe("session database port", () => {
  it("is fulfilled by the production pool type", () => {
    const fulfilled: pg.Pool extends SessionDatabase ? true : false = true;
    const accepted: SessionDatabase extends NonNullable<BetterAuthOptions["database"]> ? true : false = true;
    expect(fulfilled).toBe(true);
    expect(accepted).toBe(true);
  });

  it("does not hand the driver pool type to the session", () => {
    const config = readFileSync(join(webRoot, "src/identity/server/config.ts"), "utf8");
    expect(config.includes("pg.Pool")).toBe(false);
    expect(config.includes('from "pg"') || config.includes("from 'pg'")).toBe(false);
  });

  it("constructs the production pool only in the pool module", () => {
    const hits = productionSources(join(webRoot, "src")).filter((file) => /\bnew\s+(?:pg\.)?Pool\s*\(/.test(readFileSync(file, "utf8")));
    expect(hits.map((file) => file.slice(webRoot.length))).toEqual(["src/platform/db/pool.ts"]);
  });
});
