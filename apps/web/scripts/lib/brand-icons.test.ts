import { readFileSync } from "node:fs";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { icoFromPngs, saturnOnBackground } from "./brand-icons.ts";

const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url));

describe("brand icons", () => {
  it("public icons are the Saturn PNG on #0c0c0d (run pnpm brand:icons after changing a source)", async () => {
    const master = read("public/icons/saturn-1024.png");
    const favicons = [
      { size: 16, png: await saturnOnBackground(master, 16) },
      { size: 32, png: await saturnOnBackground(read("public/icons/saturn-32.png"), 32) },
      { size: 48, png: await saturnOnBackground(master, 48) },
    ];
    expect(read("public/icons/icon-192.png")).toEqual(await saturnOnBackground(master, 192));
    expect(read("public/icons/icon-512.png")).toEqual(await saturnOnBackground(read("public/icons/saturn-512.png"), 512));
    expect(read("public/icons/apple-touch-icon.png")).toEqual(await saturnOnBackground(read("public/icons/saturn-180.png"), 180));
    expect(read("public/icons/favicon.ico")).toEqual(icoFromPngs(favicons));
    expect(() => read("public/icons/icon.svg")).toThrow();
  });

  it("flattens the transparent Saturn onto #0c0c0d at the source sizes", async () => {
    const sources: readonly (readonly [string, number, number])[] = [
      ["public/brand/logo.png", 704, 377],
      ["public/icons/saturn-32.png", 32, 32],
      ["public/icons/saturn-180.png", 180, 180],
      ["public/icons/saturn-512.png", 512, 512],
      ["public/icons/saturn-1024.png", 1024, 1024],
    ];
    for (const [file, width, height] of sources) {
      const meta = await sharp(read(file)).metadata();
      expect([meta.width, meta.height, meta.hasAlpha], file).toEqual([width, height, true]);
    }
    const out = await saturnOnBackground(read("public/icons/saturn-32.png"), 32);
    const { data, info } = await sharp(out).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    expect([info.width, info.height, info.channels]).toEqual([32, 32, 4]);
    expect([data[0], data[1], data[2], data[3]]).toEqual([0x0c, 0x0c, 0x0d, 255]);
    expect(data.some((value, index) => index % 4 === 0 && value > 200 && data[index + 3] === 255)).toBe(true);
    await expect(saturnOnBackground(read("public/icons/saturn-32.png"), 0)).rejects.toThrow(/out of range/);
  });

  it("packs PNG entries into an ICO directory", () => {
    const ico = icoFromPngs([{ size: 16, png: Buffer.from([1, 2]) }, { size: 32, png: Buffer.from([3]) }]);
    expect([ico.readUInt16LE(2), ico.readUInt16LE(4), ico.readUInt8(6), ico.readUInt8(22)]).toEqual([1, 2, 16, 32]);
    expect([ico.readUInt32LE(6 + 12), ico.readUInt32LE(22 + 12)]).toEqual([38, 40]);
    expect([...ico.subarray(38)]).toEqual([1, 2, 3]);
  });
});
