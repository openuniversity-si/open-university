import { readFile, writeFile } from "node:fs/promises";
import { generateTokenCss, generateTokenNames, generateTokenValues, generateTypographyCss, type TokenSnapshot } from "./lib/tokens.ts";

const snapshot = JSON.parse(await readFile(new URL("../design/figma-tokens.snapshot.json", import.meta.url), "utf8")) as TokenSnapshot;
const check = process.argv.includes("--check");
for (const [name, generated] of [
  ["../src/ui/tokens/tokens.css", generateTokenCss(snapshot)],
  ["../src/ui/tokens/values.ts", generateTokenValues(snapshot)],
  ["../src/ui/tokens/names.ts", generateTokenNames(snapshot)],
  ["../src/ui/typography.css", generateTypographyCss(snapshot)],
] as const) {
  const target = new URL(name, import.meta.url);
  if (check) {
    if (await readFile(target, "utf8") !== generated) throw new Error(`${name} differs from the Figma snapshot; run pnpm tokens:generate.`);
  } else {
    await writeFile(target, generated);
  }
}
console.log(`tokens:${check ? "check" : "generate"}: ${String(Object.keys(snapshot.variables).length)} tokens, ${String(snapshot.typography.length)} text roles; version ${snapshot.figmaVersionId ?? "unversioned (freeze blocked)"}.`);
