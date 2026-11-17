import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const source = (path: string) => readFileSync(join(here, path), "utf8");

describe("empty catalog", () => {
  it("paints the copy each caller already uses", () => {
    const panel = source("./EmptyCatalog.tsx");
    expect(panel).not.toContain("emptyCatalogTitle");
    expect(panel).not.toContain("emptyCatalogBody");
    expect(panel).not.toContain("reader-copy");
    expect(panel).toContain('data-testid="tower-empty-catalog"');
    for (const path of ["../../app/page.tsx", "../../app/signed-in-home/page.tsx", "../../app/authors/view.tsx", "../../app/universities/view.tsx", "../../app/(test)/fixtures/states/page.test.tsx"]) {
      const caller = source(path);
      expect(caller).toContain("emptyCatalogTitle");
      expect(caller).toContain("emptyCatalogBody");
    }
    const error = source("../../app/error.tsx");
    expect(error).toContain("errorTitle");
    expect(error).toContain("body={null}");
    expect(error).toContain("homeTitle");
  });

  it("keeps the primary action free of catalog and player facts", () => {
    const cta = source("../PrimaryCTA/PrimaryCTA.tsx");
    expect(cta).not.toMatch(/@\/catalog\//);
    expect(cta).not.toMatch(/playback/);
  });
});
