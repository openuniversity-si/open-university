import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
  CACHE_CATALOG, COLOR_THEME, EDITORIAL_CATALOG, EXTENT_CATALOG, LIMITS_CATALOG, OG_MATTE_KEY_FILE,
  PAGINATION_CATALOG, SPACING_CATALOG, TYPOGRAPHY_CATALOG, UI_TEXT_CATALOG, stripComments,
} from "./domain-literals.ts";

/** A value the absolute reading counts. A template is not a string. A number inside a string still counts. */
export type LiteralKind = "string" | "number" | "boolean";

export interface ValueLiteral {
  readonly kind: LiteralKind;
  readonly text: string;
  readonly index: number;
}

const NUMBER = /(?<![\w$.])(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)(?![\d.])/g;
const BOOLEAN = /(?<![\w$])(?:true|false)(?![\w$])/g;

/**
 * The same reading as the M10 audit.
 * Comments are gone. A `//` inside a string stays. A template is not a string.
 * A number counts inside a string and before a CSS unit. `true` and `false` count when they are not part of a longer word.
 */
export function valueLiterals(source: string): ValueLiteral[] {
  const text = stripComments(source);
  const literals: ValueLiteral[] = [];
  let index = 0;
  const modes = ["code"];
  let stringStart = -1;
  while (index < text.length) {
    const mode = modes[modes.length - 1];
    const char = text[index];
    if (mode === "sq" || mode === "dq") {
      if (char === "\\") {
        index += 2;
        continue;
      }
      if ((mode === "sq" && char === "'") || (mode === "dq" && char === "\"")) {
        literals.push({ kind: "string", text: text.slice(stringStart + 1, index), index: stringStart });
        modes.pop();
      }
      index += 1;
      continue;
    }
    if (mode === "tmpl") {
      if (char === "\\") {
        index += 2;
        continue;
      }
      if (char === "`") {
        modes.pop();
        index += 1;
        continue;
      }
      if (char === "$" && text[index + 1] === "{") {
        modes.push("code");
        index += 2;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'") {
      modes.push("sq");
      stringStart = index;
      index += 1;
      continue;
    }
    if (char === "\"") {
      modes.push("dq");
      stringStart = index;
      index += 1;
      continue;
    }
    if (char === "`") {
      modes.push("tmpl");
      index += 1;
      continue;
    }
    if (char === "}" && modes.length > 1 && modes[modes.length - 2] === "tmpl") {
      modes.pop();
      index += 1;
      continue;
    }
    index += 1;
  }
  for (const match of text.matchAll(NUMBER)) {
    literals.push({ kind: "number", text: match[0], index: match.index });
  }
  for (const match of text.matchAll(BOOLEAN)) {
    literals.push({ kind: "boolean", text: match[0], index: match.index });
  }
  return literals;
}

/** Production sources, including `(test)` routes, the way the M10 census reads them. */
export function absoluteSources(repo: string): { path: string; text: string }[] {
  const files: { path: string; text: string }[] = [];
  const root = join(repo, "apps/web/src");
  const collect = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (name === "testing") continue;
      const absolute = join(dir, name);
      if (statSync(absolute).isDirectory()) {
        collect(absolute);
        continue;
      }
      if (!/\.(?:css|ts|tsx)$/.test(name) || /\.(?:int\.)?test\.tsx?$/.test(name)) continue;
      files.push({ path: relative(repo, absolute).split("\\").join("/"), text: readFileSync(absolute, "utf8") });
    }
  };
  collect(root);
  return files;
}

/** Files whose literals are the keys. A literal in one of these is not outside the catalog. */
export const ABSOLUTE_CATALOGS = [
  ...TYPOGRAPHY_CATALOG, ...SPACING_CATALOG, ...COLOR_THEME, ...CACHE_CATALOG, ...LIMITS_CATALOG,
  ...PAGINATION_CATALOG, ...EXTENT_CATALOG, ...EDITORIAL_CATALOG, OG_MATTE_KEY_FILE, UI_TEXT_CATALOG,
] as const;

/**
 * The absolute door stays off while a fresh census is not zero outside the catalogs and the named exceptions.
 * Turning it on is `true` only when `absoluteOffenders` of the production tree is empty.
 */
export const ABSOLUTE_GATE = false;

const SQL_OWNERS = [
  "apps/web/src/platform/db/",
  "apps/web/src/catalog/server/",
  "apps/web/src/media/server/",
  "apps/web/src/playback/server/",
  "apps/web/src/identity/server/",
  "apps/web/src/progress/server/",
  "apps/web/src/site/server/",
];

/** DOM key names. `key === "Home"` is the key, not a second spelling of the word Home. */
export const DOM_KEYS = [" ", "Home", "End", "Escape", "Tab", "Enter", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"] as const;

export interface AbsoluteOptions {
  readonly catalogValues: ReadonlySet<string>;
  readonly phrases: ReadonlySet<string>;
}

function lineAt(text: string, index: number): string {
  const start = text.lastIndexOf("\n", index - 1) + 1;
  const end = text.indexOf("\n", index);
  return text.slice(start, end < 0 ? text.length : end);
}

function looksLikeSql(value: string): boolean {
  return /\b(?:SELECT|INSERT|UPDATE|DELETE|WITH|FROM|JOIN)\b/i.test(value);
}

function sqlSpans(source: string): [number, number][] {
  const text = stripComments(source);
  const spans: [number, number][] = [];
  let index = 0;
  const modes = ["code"];
  const starts: number[] = [];
  while (index < text.length) {
    const mode = modes[modes.length - 1];
    const char = text[index];
    if (mode === "sq" || mode === "dq" || mode === "tmpl") {
      if (char === "\\") {
        index += 2;
        continue;
      }
      const closes = (mode === "sq" && char === "'") || (mode === "dq" && char === "\"") || (mode === "tmpl" && char === "`");
      if (closes) {
        const start = starts.pop() ?? index;
        const body = text.slice(start + 1, index);
        if (looksLikeSql(body)) spans.push([start, index + 1]);
        modes.pop();
        index += 1;
        continue;
      }
      if (mode === "tmpl" && char === "$" && text[index + 1] === "{") {
        modes.push("code");
        index += 2;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'" || char === "\"" || char === "`") {
      modes.push(char === "'" ? "sq" : char === "\"" ? "dq" : "tmpl");
      starts.push(index);
      index += 1;
      continue;
    }
    if (char === "}" && modes.length > 1 && modes[modes.length - 2] === "tmpl") {
      modes.pop();
      index += 1;
      continue;
    }
    index += 1;
  }
  return spans;
}

function excepted(path: string, literal: ValueLiteral, text: string, options: AbsoluteOptions, spans: readonly [number, number][]): boolean {
  if (literal.kind === "string") {
    const line = lineAt(text, literal.index);
    if ((literal.text === "use client" || literal.text === "use server") && new RegExp(`^\\s*["']${literal.text}["'];?\\s*$`).test(line)) return true;
    if (/^var\(--[\w-]+\)$/.test(literal.text)) return true;
    if (/\b(?:import|export)\b/.test(line) && (line.includes(`"${literal.text}"`) || line.includes(`'${literal.text}'`))) return true;
    if (options.phrases.has(literal.text) && /\[[^\]]+\]/.test(line) && line.includes(literal.text)) return true;
    if ((DOM_KEYS as readonly string[]).includes(literal.text) && /(?:event\.)?key\s*===\s*$/.test(text.slice(Math.max(0, literal.index - 40), literal.index))) return true;
    if (SQL_OWNERS.some((owner) => path.startsWith(owner)) && looksLikeSql(literal.text)) return true;
    return false;
  }
  if (literal.kind === "number") {
    if (literal.text === "1" && /LIMIT\s+$/i.test(text.slice(Math.max(0, literal.index - 8), literal.index))) return true;
    const line = lineAt(text, literal.index);
    if (/@media|@supports/.test(line)) {
      const unit = /^[\d.]+(?:px|rem|em|vw|vh|dvh|svh|%)/.exec(text.slice(literal.index));
      if (unit && options.catalogValues.has(unit[0])) return true;
    }
    if (SQL_OWNERS.some((owner) => path.startsWith(owner)) && spans.some(([from, to]) => literal.index >= from && literal.index < to)) return true;
  }
  return false;
}

/** Literals outside the catalogs and the named exceptions. The production tree is not empty, so the door stays off. */
export function absoluteOffenders(files: readonly { path: string; text: string }[], options: AbsoluteOptions): string[] {
  const catalogs = new Set<string>(ABSOLUTE_CATALOGS);
  const offenders: string[] = [];
  for (const file of files) {
    if (catalogs.has(file.path)) continue;
    const text = stripComments(file.text);
    const spans = sqlSpans(file.text);
    for (const literal of valueLiterals(file.text)) {
      if (excepted(file.path, literal, text, options, spans)) continue;
      offenders.push(`${file.path}: ${literal.kind} ${literal.text}`);
    }
  }
  return offenders;
}
