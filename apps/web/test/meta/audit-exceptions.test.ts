import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const packageJson = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")) as {
  pnpm?: { auditConfig?: { ignoreGhsas?: string[] } };
};
const doc = readFileSync(new URL("../../docs/security/audit-exceptions.md", import.meta.url), "utf8");

/** Rows of the exceptions table: | GHSA | package | path | reason | owner | deadline | */
const rows = doc
  .split("\n")
  .filter((line) => line.startsWith("| GHSA-"))
  .map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()));

describe("pnpm audit exceptions (§10.2)", () => {
  const ignored = packageJson.pnpm?.auditConfig?.ignoreGhsas ?? [];

  it("documents exactly the advisories ignored in package.json", () => {
    expect(rows.map((row) => row[0]).sort()).toEqual([...ignored].sort());
  });

  it("gives every exception a reason, an owner and a deadline", () => {
    for (const row of rows) {
      expect(row).toHaveLength(6);
      for (const cell of row) expect(cell).not.toBe("");
    }
  });
});
