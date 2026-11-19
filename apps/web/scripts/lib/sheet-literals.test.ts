import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// Verifies: D-052
/** Empty. The presentation files are free, so a literal anywhere fails. */
export const DEFERRED_SHEETS = [] as const;

const root = new URL("../../src/", import.meta.url);
const skipDir = new Set(["(test)", "testing", "tokens", "node_modules"]);

function deferred(path: string): boolean {
  return DEFERRED_SHEETS.some((prefix) => path === prefix || path.startsWith(prefix));
}

function strip(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const PATTERNS = [
  /object-fit:\s+(?!var\()cover\b/g,
  /aspect-ratio:\s+(?!var\()[^;{}\n]+/g,
  /opacity:\s+(?!var\()(?:\d*\.\d+|\d+)\b/g,
  /border-radius:\s+(?!var\()50%/g,
  /(?<![\w-])ease-out(?![\w-])/g,
  /stroke-dasharray:\s+(?!var\()[^;{}\n]+/g,
  /strokeWidth="(?!var\()[^"]+"/g,
  /animation:[^;{}]*\b1s\b/g,
  /animation:[^;{}]*\blinear\b/g,
  /(?<![\w-])9\s*\/\s*16\b/g,
  /(?<![\w-])16\s*\/\s*9\b/g,
  /color-scheme:\s+(?!var\()[^;{}\n]+/g,
  /-webkit-tap-highlight-color:\s+(?!var\()[^;{}\n]+/g,
  /:\s+transparent\b/g,
  /(?<![\w-])72%/g,
  /box-shadow:\s+inset 0 0 0\b/g,
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (skipDir.has(name)) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    if (!/\.(?:css|tsx)$/.test(name) || name.endsWith(".test.tsx")) return [];
    return [path];
  });
}

describe("sheet literals", () => {
  it("D-052: an identity literal outside the theme is on the deferred list", () => {
    const outside: string[] = [];
    for (const path of files(root.pathname)) {
      const rel = relative(root.pathname, path);
      if (deferred(rel) || rel.endsWith("typography.css")) continue;
      const text = strip(readFileSync(path, "utf8"));
      for (const pattern of PATTERNS) {
        pattern.lastIndex = 0;
        for (const match of text.matchAll(pattern)) outside.push(`${rel}: ${match[0]}`);
      }
    }
    expect(DEFERRED_SHEETS).toEqual([]);
    expect(outside).toEqual([]);
  });
});
