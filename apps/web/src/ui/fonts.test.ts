import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { staticTextCharacters, woff2Codepoints } from "../../scripts/lib/font-coverage.ts";

const root = fileURLToPath(new URL("../..", import.meta.url));
const fonts = `${root}/public/fonts`;

describe("Inter subset", () => {
  const inter = readFileSync(`${fonts}/Inter.woff2`);

  it("keeps every public woff2 at or below 60 KB", () => {
    for (const name of readdirSync(fonts).filter((file) => file.endsWith(".woff2"))) expect(statSync(`${fonts}/${name}`).size, name).toBeLessThanOrEqual(60 * 1024);
  });

  it("has a glyph for every character of the static text (no tofu)", () => {
    const covered = woff2Codepoints(inter);
    expect(covered.has(0x41) && covered.has(0x2014)).toBe(true);
    const missing = [...staticTextCharacters(root)].filter(([character]) => !covered.has(character.codePointAt(0) ?? 0));
    // Add the code point to scripts/fonts/inter-unicodes.txt and run `pnpm fonts:subset`.
    expect(missing.map(([character, file]) => `U+${(character.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0")} ${character} (${file})`)).toEqual([]);
  });

  it("is the file scripts/font-subset.py recorded in the manifest", () => {
    const manifest = JSON.parse(readFileSync(`${fonts}/manifest.json`, "utf8")) as { family: string; file: string; sha256: string }[];
    const entry = manifest.find((font) => font.family === "inter");
    expect(entry?.file).toBe("Inter.woff2");
    expect(entry?.sha256).toBe(createHash("sha256").update(inter).digest("hex"));
  });
});
