import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const src = join(import.meta.dirname, "../..");
const files = (directory: string): string[] => readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
  const path = join(directory, entry.name);
  return entry.isDirectory() ? files(path) : /\.tsx?$/.test(entry.name) ? [path] : [];
});

/** ADR-17 guardian: runtime modules read the active release, never the v1 JSON or the versioned snapshot. */
describe("runtime catalog sources", () => {
  it("no runtime module imports the legacy catalog or the snapshot", () => {
    const allowed = new Set<string>();
    const offenders = files(src).map((path) => relative(src, path)).filter((path) => !allowed.has(path) && !/\.test\.tsx?$/.test(path))
      .filter((path) => /from\s+["'][^"']*(?:catalog\/load(?:\.ts)?|content\/catalog\/)[^"']*["']/.test(readFileSync(join(src, path), "utf8")));
    expect(offenders).toEqual([]);
  });
});
