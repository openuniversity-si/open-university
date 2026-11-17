import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

it("D-023: retires v1 data, import and parity entry points", () => {
  const app = resolve(import.meta.dirname, "../../..");
  for (const path of ["content/catalog", "scripts/catalog-migrate.ts", "scripts/catalog-parity.ts", "scripts/lib/catalog-import.ts", "scripts/lib/catalog-parity.ts", "test/int/catalog-migrate.int.test.ts"]) {
    expect(existsSync(resolve(app, path)), path).toBe(false);
  }
  const pkg = JSON.parse(readFileSync(resolve(app, "package.json"), "utf8")) as { scripts: Record<string, string> };
  expect(pkg.scripts).not.toHaveProperty("catalog:migrate");
  expect(pkg.scripts).not.toHaveProperty("catalog:parity");
});
