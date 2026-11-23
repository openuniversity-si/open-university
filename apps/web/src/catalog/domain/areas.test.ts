import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { taxonomyDrift } from "./areas.ts";

// Verifies: D-030, REQ-contract-inv-h4
// ADR-25: the areas and their order are data in `subject_areas`, changed through the admin API. No list of them in code.
const app = join(import.meta.dirname, "..", "..", "..");
const doc = readFileSync(join(app, "docs", "catalog", "areas.md"), "utf8");
const seedIds = [...readFileSync(join(app, "drizzle", "0012_subject_areas.sql"), "utf8").matchAll(/\('([a-z0-9-]+)', '[^']+', \d+\)/g)].map((match) => match[1] ?? "");

function sources(directory: string): string[] {
  return readdirSync(join(app, directory), { recursive: true, encoding: "utf8" }).filter((file) => /\.(ts|tsx|mjs)$/.test(file)).map((file) => join(app, directory, file));
}

const area = (id: string, position: number, title = id) => ({ id, title, position });
const tables = (areas: ReturnType<typeof area>[], subareas: { id: string; area_id: string; title: string; position: number }[] = []) => ({ subject_areas: areas, subject_subareas: subareas });

describe("subject areas (data, not code)", () => {
  it("keeps no list of areas in the code: nothing declares or imports one", () => {
    expect(seedIds.length).toBeGreaterThan(0);
    // A fixture names a few areas; ten or more `{ id: <area>, title: … }` entries in one file mirror the list.
    const entry = new RegExp(`\\{ id: "(?:${seedIds.join("|")})", title: `, "g");
    const offenders = [...sources("src"), ...sources("scripts"), ...sources("test")]
      .filter((file) => file !== import.meta.filename)
      .filter((file) => { const text = readFileSync(file, "utf8"); return /\bSUBJECT_AREAS\b|\bSUBJECT_SUBAREAS\b|\bPUBLISHED_COURSE_AREAS\b|\bsubareaSeedRows\b|\bareaSeedRows\b/.test(text) || (text.match(entry) ?? []).length >= 10; })
      .map((file) => relative(app, file));
    expect(offenders).toEqual([]);
  });

  it("documents the admin API workflow in docs/catalog/areas.md, not a table of areas", () => {
    expect(doc).not.toContain("<!-- areas:start -->");
    expect(doc).not.toMatch(/^\| \d+ \| `[a-z0-9-]+` \|/m);
    for (const command of ["area list", "area create", "area move", "area update"]) expect(doc, command).toContain(`scripts/tower-catalog ${command}`);
  });

  it("finds no drift when the release carries the tables' order, and every shifted area after a move", () => {
    const before = tables([area("a", 1), area("b", 2), area("c", 3)]);
    const release = { areas: [{ id: "a", title: "a" }, { id: "b", title: "b" }, { id: "c", title: "c" }] };
    expect(taxonomyDrift(release, before)).toEqual([]);
    // Positions may have gaps; only the order counts.
    expect(taxonomyDrift(release, tables([area("a", 2), area("b", 5), area("c", 9)]))).toEqual([]);
    expect(taxonomyDrift(release, tables([area("c", 1), area("a", 2), area("b", 3)]))).toEqual(["area:a", "area:b", "area:c"]);
    expect(taxonomyDrift(release, tables([area("a", 1), area("c", 2), area("b", 3)]))).toEqual(["area:b", "area:c"]);
  });

  it("names renamed, created and subarea changes, and ignores what the release does not publish", () => {
    const current = tables([area("a", 1, "A2"), area("b", 2), area("d", 3)], [{ id: "s", area_id: "b", title: "S", position: 1 }]);
    expect(taxonomyDrift({ areas: [{ id: "a", title: "A" }, { id: "b", title: "b" }] }, current)).toEqual(["area:a", "area:d"]);
    expect(taxonomyDrift({ areas: [{ id: "a", title: "A2" }, { id: "b", title: "b" }, { id: "d", title: "d" }], subareas: [{ id: "s", areaId: "a", title: "S" }] }, current)).toEqual(["subarea:s"]);
    expect(taxonomyDrift({}, current)).toEqual([]);
  });
});

function listed(pattern: RegExp): string[] {
  return [...sources("src"), ...sources("scripts"), ...sources("test")]
    .filter((file) => file !== import.meta.filename && pattern.test(readFileSync(file, "utf8")))
    .map((file) => relative(app, file));
}

describe("D-030 taxonomy is data", () => {
  it("declares no subarea seed module and no SUBJECT_SUBAREAS constant", () => {
    expect(existsSync(join(app, "src", "catalog", "domain", "subareas.ts"))).toBe(false);
    expect(listed(/\bSUBJECT_SUBAREAS\b|\bsubareaSeedRows\b/)).toEqual([]);
  });

  it("parses no area list from the migration for a test reset", () => {
    expect(existsSync(join(app, "test", "fixtures", "catalog-seed.ts"))).toBe(false);
    expect(listed(/\bareaSeedRows\b/)).toEqual([]);
  });

  it("reads a renamed subarea from the tables passed in", () => {
    const current = tables([area("a", 1), area("b", 2)], [{ id: "s", area_id: "a", title: "After", position: 1 }]);
    expect(taxonomyDrift({ areas: [{ id: "a", title: "a" }, { id: "b", title: "b" }], subareas: [{ id: "s", areaId: "a", title: "Before" }] }, current)).toEqual(["subarea:s"]);
  });

  it("keeps source free of a fixed subject-subarea id list", () => {
    expect(listed(/\bSUBJECT_SUBAREAS\b|\bSUBJECT_AREAS\b|\bPUBLISHED_COURSE_AREAS\b/)).toEqual([]);
  });

  it("describes subareas without listing the rows", () => {
    const text = readFileSync(join(app, "docs", "catalog", "subareas.md"), "utf8");
    expect(text).not.toContain("<!-- subareas:start -->");
    expect(text).not.toContain("SUBJECT_SUBAREAS");
    expect(text).not.toMatch(/^\| `[a-z0-9-]+` \| \d+ \| `[a-z0-9-]+` \|/m);
    expect(text).toContain("subject_subareas");
    expect(text).toContain("D-030");
    expect(text).toContain("scripts/tower-catalog subarea list");
    expect(text).toContain("scripts/tower-catalog subarea create");
  });

  it("points ADR-25 and ADR-26 at the database", () => {
    const adr25 = readFileSync(join(app, "docs", "adr", "ADR-25-subject-areas.md"), "utf8");
    const adr26 = readFileSync(join(app, "docs", "adr", "ADR-26-subareas.md"), "utf8");
    for (const text of [adr25, adr26]) {
      expect(text).not.toContain("SUBJECT_AREAS");
      expect(text).not.toContain("SUBJECT_SUBAREAS");
      expect(text).toContain("D-030");
      expect(text).toContain("never requires a code change");
    }
    expect(adr25).toContain("subject_areas");
    expect(adr25).toContain("area create");
    expect(adr26).toContain("subject_subareas");
    expect(adr26).toContain("subarea create");
  });
});
