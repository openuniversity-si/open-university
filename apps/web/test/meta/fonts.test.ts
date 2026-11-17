import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import manifest from "../../public/fonts/manifest.json";

describe("pinned OFL fonts", () => {
  it.each(manifest)("pins $family bytes and real weight range", async (font) => {
    const bytes = await readFile(new URL(`../../public/fonts/${font.file}`, import.meta.url));
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(font.sha256);
    expect(font.version).not.toBe("");
    const weight = font.axes.find((axis) => axis.tag === "wght");
    if (!weight) throw new Error(`Missing weight axis: ${font.family}`);
    expect(weight.min).toBeLessThanOrEqual(400);
    expect(weight.max).toBeGreaterThanOrEqual(700);
    expect(await readFile(new URL(`../../public/fonts/${font.family}-OFL.txt`, import.meta.url), "utf8")).toContain("SIL OPEN FONT LICENSE Version 1.1");
  });
});
