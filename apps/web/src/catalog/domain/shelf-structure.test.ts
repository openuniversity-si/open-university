import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("shelf structure", () => {
  it("does not import reader copy into the institution shelf", () => {
    for (const name of ["universities.ts", "countries.ts", "credits.ts"]) {
      expect(readFileSync(new URL(name, import.meta.url), "utf8"), name).not.toMatch(/reader-copy/);
    }
  });
});
