import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { woff2Codepoints } from "../../../scripts/lib/font-coverage.ts";
import { INTER_SUBSET, inInterSubset, outsideInterSubset, undrawablePageText } from "../../site/domain/page-characters.ts";

const root = fileURLToPath(new URL("../../..", import.meta.url));

/** scripts/fonts/inter-unicodes.txt as [first, last] pairs. */
function recordedRanges(): [number, number][] {
  return readFileSync(`${root}/scripts/fonts/inter-unicodes.txt`, "utf8").split("\n").map((line) => line.replace(/#.*/, "").trim()).filter(Boolean).map((line) => {
    const [first, last] = line.replace(/^U\+/, "").split("-").map((hex) => Number.parseInt(hex, 16));
    return [first ?? 0, last ?? first ?? 0];
  });
}

describe("Inter subset for catalog text", () => {
  it("mirrors scripts/fonts/inter-unicodes.txt exactly", () => {
    expect(INTER_SUBSET.map(([first, last]) => [first, last])).toEqual(recordedRanges());
  });

  it("only allows code points the shipped woff2 really has", () => {
    const covered = woff2Codepoints(readFileSync(`${root}/public/fonts/Inter.woff2`));
    const missing = INTER_SUBSET.flatMap(([first, last]) => Array.from({ length: last - first + 1 }, (_, index) => first + index)).filter((point) => !covered.has(point));
    expect(missing).toEqual([]);
  });

  it("names the code points outside the subset, never the text", () => {
    expect(inInterSubset(0x41)).toBe(true);
    expect(inInterSubset(0x2014)).toBe(true);
    expect(outsideInterSubset("Plain — “quoted” text…")).toEqual([]);
    expect(outsideInterSubset("emoji 🙂 and 🙂 again, Ω")).toEqual(["U+1F642", "U+03A9"]);
    expect(undrawablePageText("course", "level", "emoji 🙂")).toBe("course.level uses characters outside the Inter subset: U+1F642.");
    expect(undrawablePageText("course", "level", "x".repeat(80))).toBeNull();
  });

  it("keeps the subset on the site, away from the offer's slot sizes", () => {
    const offer = readFileSync(new URL("./fields.ts", import.meta.url), "utf8");
    expect(offer).not.toContain("INTER_SUBSET");
    expect(offer).not.toContain("0x0020");
    expect(readFileSync(new URL("../../site/domain/page-characters.ts", import.meta.url), "utf8")).toContain("export const INTER_SUBSET");
  });
});
