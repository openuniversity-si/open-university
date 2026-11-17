import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parseSiteData } from "../../site/domain/site-data.ts";
import { fullSizeRelease } from "../testing/full-release.ts";
import { CONFIG_KEYS, OTHER_COUNTRIES_TITLE } from "./config/index.ts";
import values from "./config/values.json" with { type: "json" };
import { countryOf, groupByCountry, type Country } from "./countries.ts";
import type { HomeCourse } from "./home.ts";
import { universities, universityCourseCount, type University } from "./universities.ts";
import { universityIndexView } from "./view-model.ts";

const COUNTRIES = parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))).countries;
const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SKIP = new Set(["node_modules", ".git", ".toolchain", ".gate", "dist", "coverage", ".turbo"]);
const isBuildOutput = (name: string) => name.startsWith(".next");
const TEXT = new Set([".ts", ".tsx", ".mjs", ".js", ".cjs", ".py", ".sh", ".md", ".json", ".css", ".yml", ".yaml"]);
const ALLOWED = new Set(["src/catalog/domain/config/values.json", "docs/adr/ADR-27-country-sections.md"]);

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (SKIP.has(entry.name) || isBuildOutput(entry.name)) return [];
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return filesUnder(path);
    const dot = entry.name.lastIndexOf(".");
    return dot >= 0 && TEXT.has(entry.name.slice(dot)) ? [path] : [];
  });
}

function quoted(source: string): string[] {
  return [...source.matchAll(/["'](?:\\.|[^"'\\])*["']/g)].map((match) => match[0].slice(1, -1));
}

const university = (slug: string, place: string, courseIds: readonly string[]): University => {
  const courses = courseIds.map((id) => ({ id }) as HomeCourse);
  return { slug, name: slug, fullName: slug, place, cover: null, og: null, courses, areaCount: 0, areasNamed: false };
};

describe("countries", () => {
  it("ranks the configured countries 1..n without ties (the order is the only hierarchy)", () => {
    expect(COUNTRIES.map((country) => [country.id, country.rank])).toEqual([
      ["us", 1], ["fr", 2], ["it", 3], ["de", 4], ["es", 5], ["ch", 6], ["gb", 7], ["in", 8], ["br", 9],
    ]);
  });

  it("reads the country from the end of the release place", () => {
    expect(countryOf("Cambridge, MA", COUNTRIES)?.id).toBe("us");
    expect(countryOf("Paris, France", COUNTRIES)?.id).toBe("fr");
    expect(countryOf("Rome, Italy", COUNTRIES)?.id).toBe("it");
    expect(countryOf("Munich, Germany", COUNTRIES)?.id).toBe("de");
    expect(countryOf("Madrid, Spain", COUNTRIES)?.id).toBe("es");
    expect(countryOf("Zurich, Switzerland", COUNTRIES)?.id).toBe("ch");
    expect(countryOf("Oxford, United Kingdom", COUNTRIES)?.id).toBe("gb");
    expect(countryOf("Edinburgh, Scotland", COUNTRIES)?.id).toBe("gb");
    expect(countryOf("Chennai, India", COUNTRIES)?.id).toBe("in");
    expect(countryOf("São Paulo, Brazil", COUNTRIES)?.id).toBe("br");
    expect(countryOf("Lisbon, Portugal", COUNTRIES)).toBeNull();
    expect(countryOf("Dublin, Ireland", COUNTRIES)).toBeNull();
    expect(countryOf("Europe", COUNTRIES)).toBeNull();
    expect(countryOf("", COUNTRIES)).toBeNull();
    expect(countryOf("Tokyo, Japan", COUNTRIES)).toBeNull();
  });

  it("groups by rank whatever the Home row order, keeping row order inside each country", () => {
    const input = [university("iit-madras", "Chennai, India", ["c1"]), university("mit", "Cambridge, MA", ["c2", "c3"]), university("usp", "São Paulo, Brazil", ["c4"]), university("yale", "New Haven, CT", ["c5"]), university("oxford", "Oxford, United Kingdom", ["c6"])];
    const groups = groupByCountry(input, COUNTRIES);
    expect(groups.map((group) => group.country?.id)).toEqual(["us", "gb", "in", "br"]);
    expect(groups[0]?.universities.map((entry) => entry.slug)).toEqual(["mit", "yale"]);
    expect(groups[0]?.universityCount).toBe(2);
    expect(groups[0]?.courseCount).toBe(3);
  });

  it("follows the rank data, not the declaration order", () => {
    const swapped: Country[] = COUNTRIES.map((country) => ({ ...country, rank: country.id === "in" ? 0 : country.rank }));
    const groups = groupByCountry([university("mit", "Cambridge, MA", ["a"]), university("iisc", "Bengaluru, India", ["b"])], swapped);
    expect(groups.map((group) => group.country?.id)).toEqual(["in", "us"]);
  });

  it("hides countries with no published university (India before the NPTEL rows are published)", () => {
    const groups = groupByCountry([university("mit", "Cambridge, MA", ["a"]), university("yale", "New Haven, CT", ["b"])], COUNTRIES);
    expect(groups.map((group) => group.country?.id)).toEqual(["us"]);
    expect(groups[0]?.universityCount).toBe(2);
    expect(groups[0]?.courseCount).toBe(2);
  });

  it("never hides a university: unknown places go last, without a country", () => {
    const groups = groupByCountry([university("todai", "Tokyo, Japan", ["a"]), university("mit", "Cambridge, MA", ["b"]), university("nowhere", "", ["c"])], COUNTRIES);
    expect(groups.map((group) => group.country?.id ?? null)).toEqual(["us", null]);
    expect(groups[1]?.universities.map((entry) => entry.slug)).toEqual(["todai", "nowhere"]);
    expect(groups.flatMap((group) => group.universities).length).toBe(3);
  });

  it("groups a new country from data alone", () => {
    const countries = [...COUNTRIES, { id: "jp", name: "Japan", rank: 10, placeEndings: ["Japan"] }];
    const groups = groupByCountry([university("todai", "Tokyo, Japan", ["a"])], countries);
    expect(groups.map((group) => group.country?.id)).toEqual(["jp"]);
  });

  it("counts a course shared by two universities once in the country meta", () => {
    expect(groupByCountry([university("mit", "Cambridge, MA", ["x", "y"]), university("harvard", "Cambridge, MA", ["y"])], COUNTRIES)[0]?.courseCount).toBe(2);
  });

  it("resolves every place in the full-size fixture to a country, with none in the residual group", () => {
    const catalog = fullSizeRelease();
    const listed = universities(catalog);
    expect(listed.length).toBeGreaterThan(0);
    for (const entry of listed) expect(countryOf(entry.place, COUNTRIES)?.id, entry.place).toEqual(expect.any(String));
    const view = universityIndexView(catalog, COUNTRIES);
    expect(view.groups.every((group) => group.country !== null)).toBe(true);
    expect(view.groups.flatMap((group) => group.universities).every((entry) => entry.place.length > 0)).toBe(true);
    expect(view.courseCount).toBe(universityCourseCount(listed));
    for (const group of view.groups) {
      const members = listed.filter((entry) => entry.place !== "" && countryOf(entry.place, COUNTRIES)?.id === group.country?.id);
      expect(group.courseCount).toBe(universityCourseCount(members));
    }
  });

  it("reads the residual title from documented configuration and repeats it nowhere else", () => {
    const record = values as Record<string, string>;
    expect(Object.keys(values)).toEqual([...CONFIG_KEYS]);
    expect(OTHER_COUNTRIES_TITLE).toBe(record[CONFIG_KEYS[0]]);
    const doc = readFileSync(join(ROOT, "docs/adr/ADR-27-country-sections.md"), "utf8");
    const ui = readFileSync(join(ROOT, "src/ui/CountrySection/CountrySection.tsx"), "utf8");
    expect(ui).toContain('from "@/catalog/domain/config"');
    for (const key of CONFIG_KEYS) {
      const value = record[key] ?? "";
      expect(value.length, key).toBeGreaterThan(0);
      expect(doc, key).toContain("`" + key + "`");
      expect(doc, key).toContain("`" + value + "`");
    }
    const configured = CONFIG_KEYS.map((key) => record[key] ?? "");
    for (const path of filesUnder(ROOT)) {
      const rel = relative(ROOT, path);
      if (ALLOWED.has(rel)) continue;
      const source = readFileSync(path, "utf8");
      const bare = source.replace(/["'](?:\\.|[^"'\\])*["']/g, "");
      for (const value of configured) {
        expect(quoted(source), rel).not.toContain(value);
        if (value.length >= 4) expect(bare, rel).not.toContain(value);
      }
    }
  });
});
