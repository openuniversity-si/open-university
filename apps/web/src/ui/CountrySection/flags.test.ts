import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseSiteData } from "../../site/domain/site-data.ts";
import { validateFlagGeometry, type FlagGeometry } from "./flags.ts";

const data = parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8")));
const OFFICIAL: Record<string, number> = { us: 19 / 10, fr: 3 / 2, it: 3 / 2, de: 5 / 3, es: 3 / 2, ch: 1, gb: 2, in: 3 / 2, br: 10 / 7 };

describe("country flags (official proportions, never stretched)", () => {
  it.each(Object.keys(OFFICIAL))("%s keeps its official width:height ratio", (id) => {
    const flag = data.flags[id] as FlagGeometry;
    expect(flag.width / flag.height).toBeCloseTo(OFFICIAL[id] ?? 0, 3);
    expect(() => { validateFlagGeometry(flag); }).not.toThrow();
  });

  it.each(Object.keys(OFFICIAL))("%s draws inside its own box (no padding, no overflow)", (id) => {
    const flag = data.flags[id] as FlagGeometry;
    const field = flag.shapes.filter((shape) => shape.kind === "rect");
    expect(Math.max(...field.map((shape) => (shape.x ?? 0) + (shape.width ?? 0)))).toBeCloseTo(flag.width, 2);
    expect(Math.max(...field.map((shape) => (shape.y ?? 0) + (shape.height ?? 0)))).toBeCloseTo(flag.height, 2);
  });

  it("has a flag for every configured country", () => {
    for (const country of data.countries) expect(validateFlagGeometry(data.flags[country.id] as FlagGeometry).shapes.length).toBeGreaterThan(0);
  });

  it("draws Spain as three stripes and no crest, and has no Europe flag", () => {
    const spain = data.flags.es as FlagGeometry;
    expect(spain.shapes).toHaveLength(3);
    expect(spain.shapes.every((shape) => shape.kind === "rect")).toBe(true);
    expect(data.flags.eu).toBeUndefined();
    expect(data.countries.map((country) => country.id)).not.toContain("eu");
  });

  it("draws the U.S. 13 stripes and 50 stars, and India's 24-spoke chakra", () => {
    const us = data.flags.us as FlagGeometry;
    expect(us.shapes.filter((shape) => shape.kind === "rect")).toHaveLength(14);
    expect(us.shapes.find((shape) => shape.kind === "path")?.d?.match(/M/g)).toHaveLength(50);
    expect((data.flags.in as FlagGeometry).shapes.find((shape) => shape.stroke && shape.kind === "path")?.d?.match(/M/g)).toHaveLength(24);
  });

  it("accepts a new country's flag without a code change", () => {
    const flag: FlagGeometry = { width: 96, height: 64, shapes: [{ kind: "rect", x: 0, y: 0, width: 96, height: 64, fill: "#FFFFFF" }, { kind: "circle", cx: 48, cy: 32, r: 12, fill: "#BC002D" }] };
    expect(validateFlagGeometry(flag).shapes).toHaveLength(2);
  });
});
