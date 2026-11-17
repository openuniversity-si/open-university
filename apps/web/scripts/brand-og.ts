import { readFile, writeFile } from "node:fs/promises";
import { chromium } from "@playwright/test";
import sharp from "sharp";

/**
 * `pnpm brand:og [--out file]`: regenerates `public/brand/og.jpg` (1200×630) from the Figma frame "OG image — 1200x630" (the design spec file,
 * page 18:3, node 591:10621). Every number below is that frame's: dark #0c0c0c, two silver radial glows, a glass card
 * inset 24 px, the Saturn TowerMark (154×82.5 at 52,121.8 — node 591:10625, centered on the previous mark), "Open University"
 * in Inter Semi Bold 112 with a white→silver fill, the tagline, the pillars and the address.
 * Change the Figma frame first, then this file.
 */
const outIndex = process.argv.indexOf("--out");
const out = new URL(outIndex > 0 ? `file://${process.argv[outIndex + 1] ?? ""}` : "../public/brand/og.jpg", import.meta.url);
const logo = (await readFile(new URL("../public/brand/logo.png", import.meta.url))).toString("base64");
const font = (await readFile(new URL("../public/fonts/Inter.woff2", import.meta.url))).toString("base64");

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: "Inter OG"; src: url(data:font/woff2;base64,${font}) format("woff2"); font-weight: 100 900; }
* { box-sizing: border-box; margin: 0; }
html, body { width: 1200px; height: 630px; background: #0c0c0c; overflow: hidden; font-family: "Inter OG", sans-serif; }
.frame { position: relative; width: 1200px; height: 630px; overflow: hidden; }
.glow { position: absolute; inset: 0; }
.glow.a { background: radial-gradient(circle 640px at 1000px 60px, rgb(199 201 207 / 20%) 0%, rgb(199 201 207 / 7%) 55%, rgb(199 201 207 / 0%) 100%); }
.glow.b { background: radial-gradient(circle 520px at 80px 640px, rgb(199 201 207 / 7%) 0%, rgb(199 201 207 / 2.45%) 55%, rgb(199 201 207 / 0%) 100%); }
.card { position: absolute; left: 24px; top: 24px; width: 1152px; height: 582px; border-radius: 28px; background: rgb(255 255 255 / 3.5%); border: 1px solid rgb(255 255 255 / 14%); }
.mark { position: absolute; left: 52px; top: 121.8px; width: 154px; height: 82.5px; }
.t { position: absolute; white-space: nowrap; }
.title { left: 92px; top: 238px; font-size: 112px; font-weight: 600; line-height: 134.4px; letter-spacing: -0.02em; background: linear-gradient(180deg, #fff 0%, #c9cbcf 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.tag { left: 96px; top: 398px; font-size: 40px; font-weight: 400; line-height: 52px; color: #a1a1a8; }
.pillars { left: 96px; top: 526px; font-size: 20px; font-weight: 500; line-height: 24px; letter-spacing: 0.18em; color: #8b8b92; white-space: pre; }
.addr { right: 96px; top: 526px; font-size: 22px; font-weight: 500; line-height: 28px; color: #8b8b92; }
</style></head><body><div class="frame">
<div class="glow a"></div><div class="glow b"></div><div class="card"></div>
<img class="mark" src="data:image/png;base64,${logo}" alt="" width="154" height="82.5" />
<div class="t title">Open University</div>
<div class="t tag">Great lecture courses, in order.<br>Free, and beautifully made.</div>
<div class="t pillars">UNIVERSAL  ·  FREE  ·  LUXURIOUS</div>
<div class="t addr">openuniversity.si</div>
</div></body></html>`;

const runningAsRoot = typeof process.getuid === "function" && process.getuid() === 0;
const browser = await chromium.launch({ args: runningAsRoot ? ["--no-sandbox", "--disable-setuid-sandbox"] : [] });
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  await page.setContent(html);
  await page.evaluate(() => document.fonts.ready);
  const png = await page.screenshot({ clip: { x: 0, y: 0, width: 1200, height: 630 } });
  await writeFile(out, await sharp(png).jpeg({ quality: 90, chromaSubsampling: "4:4:4" }).toBuffer());
} finally {
  await browser.close();
}
console.log(`brand:og: wrote ${out.pathname} (1200×630)`);
