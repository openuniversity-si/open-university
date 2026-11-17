import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Type identity guard (Daniel, 08/10 and 17/10/2026): the UI is set in the system stack with self-hosted Inter
 * (`--tower-font-ui`); Libre Caslon belongs only to the logo/wordmark (src/ui/TowerMark, public/brand), never to
 * UI text. Any other family, @font-face, next/font loader or inline fontFamily outside the logo fails here.
 */
const root = fileURLToPath(new URL("../..", import.meta.url));
const src = join(root, "src");
const LOGO = [/^src\/ui\/TowerMark\//];
const UI_STACK = '-apple-system, blinkmacsystemfont, var(--tower-font-inter-face), "Inter", sans-serif';
const ALLOWED_FAMILY_VALUES = new Set(["var(--tower-font-ui)", "var(--tower-font-display)", "inherit"]);
/** A `font` shorthand (or a token holding one) must end in the UI stack, or point at such a token (checked itself). */
const allowedFontValue = (value: string): boolean => value.trim() === "inherit" || /var\(--tower-font-(?:ui|display)\)$/.test(value.trim()) || /^var\(--tower-[a-z0-9-]*-font(?:-[a-z0-9]+)*\)$/.test(value.trim());

function files(dir: string, test: (path: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path, test);
    return test(path) ? [path] : [];
  });
}
const rel = (path: string): string => relative(root, path).split("\\").join("/");
const outsideLogo = (path: string): boolean => !LOGO.some((pattern) => pattern.test(rel(path)));
const strip = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, "");

const css = files(src, (path) => path.endsWith(".css")).filter(outsideLogo);
const code = files(src, (path) => /\.(ts|tsx)$/.test(path) && !/\.test\.tsx?$/.test(path)).filter(outsideLogo);

describe("type identity: system stack + Inter outside the logo", () => {
  it("defines --tower-font-ui as the system/Inter stack and --tower-font-display as an alias of it", () => {
    const tokens = strip(readFileSync(join(src, "ui/tokens/tokens.css"), "utf8"));
    expect(tokens).toContain(`--tower-font-ui: ${UI_STACK};`);
    expect(tokens).toContain("--tower-font-display: var(--tower-font-ui);");
  });

  it("declares font-family only through the UI stack tokens", () => {
    const offenders = css.flatMap((path) => [...strip(readFileSync(path, "utf8")).matchAll(/(?:^|[;{\s])font-family\s*:\s*([^;}]+)/g)]
      .map((match) => (match[1] ?? "").trim()).filter((value) => !ALLOWED_FAMILY_VALUES.has(value)).map((value) => `${rel(path)}: ${value}`));
    expect(offenders).toEqual([]);
  });

  it("has no other font-family tokens, no @font-face, and every font shorthand ends in the UI stack", () => {
    const offenders = css.flatMap((path) => {
      const body = strip(readFileSync(path, "utf8"));
      const tokens = [...body.matchAll(/(--tower-[a-z0-9-]*font(?:-family|-face)?)\s*:\s*([^;]+);/g)]
        .filter((match) => !/-(size|weight)(-|$)/.test(match[1] ?? "") && !["--tower-font-ui", "--tower-font-display"].includes(match[1] ?? "") && !allowedFontValue(match[2] ?? ""))
        .map((match) => `${rel(path)}: ${match[1] ?? ""}`);
      const faces = /@font-face/.test(body) ? [`${rel(path)}: @font-face`] : [];
      const shorthand = [...body.matchAll(/(?:^|[;{\s])font\s*:\s*([^;}]+)/g)].filter((match) => !allowedFontValue(match[1] ?? "")).map((match) => `${rel(path)}: font: ${(match[1] ?? "").trim()}`);
      return [...tokens, ...faces, ...shorthand];
    });
    expect(offenders).toEqual([]);
  });

  it("loads exactly one web font, Inter, and sets no fontFamily inline", () => {
    const loaders = code.flatMap((path) => [...readFileSync(path, "utf8").matchAll(/localFont\(\{[\s\S]*?src:\s*"([^"]+)"/g)].map((match) => `${rel(path)}: ${match[1] ?? ""}`));
    expect(loaders).toEqual(["src/ui/fonts.ts: ../../public/fonts/Inter.woff2"]);
    expect(code.filter((path) => /next\/font\/google|fontFamily\s*:/.test(readFileSync(path, "utf8"))).map(rel)).toEqual([]);
  });

  it("serves no other web font file (Libre Caslon only as the pinned wordmark source TTF, never a woff2)", () => {
    expect(readdirSync(join(root, "public/fonts")).filter((name) => /\.(woff2?|otf)$/.test(name))).toEqual(["Inter.woff2"]);
  });
});
