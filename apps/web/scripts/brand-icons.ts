import { mkdir, readFile, writeFile } from "node:fs/promises";
import { icoFromPngs, saturnOnBackground } from "./lib/brand-icons.ts";

/**
 * `pnpm brand:icons [--out dir]`: writes the install icons from the provisional Saturn PNGs (D-028, ADR-13).
 * icon-192.png is scaled from saturn-1024.png; icon-512.png, apple-touch-icon.png (180) and the 32 px
 * favicon entry use their own sources. 16 and 48 in favicon.ico scale from saturn-1024.png. Every icon
 * is the white mark on #0c0c0d. `public/brand/og.jpg` is the brand card and is not generated here.
 */
const outIndex = process.argv.indexOf("--out");
const out = new URL(outIndex > 0 ? `file://${process.argv[outIndex + 1] ?? ""}/` : "../public/icons/", import.meta.url);
const icons = new URL("../public/icons/", import.meta.url);
const source = (name: string) => readFile(new URL(name, icons));

await mkdir(out, { recursive: true });
const master = await source("saturn-1024.png");
const favicons = [
  { size: 16, png: await saturnOnBackground(master, 16) },
  { size: 32, png: await saturnOnBackground(await source("saturn-32.png"), 32) },
  { size: 48, png: await saturnOnBackground(master, 48) },
];
await writeFile(new URL("icon-192.png", out), await saturnOnBackground(master, 192));
await writeFile(new URL("icon-512.png", out), await saturnOnBackground(await source("saturn-512.png"), 512));
await writeFile(new URL("apple-touch-icon.png", out), await saturnOnBackground(await source("saturn-180.png"), 180));
await writeFile(new URL("favicon.ico", out), icoFromPngs(favicons));
console.log(`brand:icons: wrote icon-192.png, icon-512.png, apple-touch-icon.png and favicon.ico to ${out.pathname}`);
