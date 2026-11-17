import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/** Generated type files. A font metric outside them is a second source (D-050). */
export const TYPOGRAPHY_CATALOG = [
  "apps/web/src/ui/tokens/tokens.css",
  "apps/web/src/ui/tokens/values.ts",
  "apps/web/src/ui/typography.css",
] as const;

const TYPOGRAPHY_VALUE = /^(?:var\(--tower-[\w-]+\)|inherit|normal)$/;

/**
 * D-050 typography. Size, weight, line height, tracking, family, transform, and decoration
 * read a `var(--tower-…)` token. `tower-label-transform` is the shared capitals key.
 */
export function typographyOffenders(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(TYPOGRAPHY_CATALOG);
  const offenders: string[] = [];
  for (const file of files) {
    if (!file.path.endsWith(".css") || catalog.has(file.path)) continue;
    const property = /(?:font-size|font-weight|line-height|letter-spacing|font-family|text-transform|text-decoration|font)\s*:\s*([^;}{]+)/g;
    for (const match of stripComments(file.text).matchAll(property)) {
      const value = (match[1] ?? "").trim();
      if (!TYPOGRAPHY_VALUE.test(value)) offenders.push(`${file.path}: ${match[0].trim()}`);
    }
  }
  return offenders;
}

/** Generated theme files. A unit length outside them is a second source (D-050). */
export const SPACING_CATALOG = ["apps/web/src/ui/tokens/tokens.css", "apps/web/src/ui/tokens/values.ts"] as const;

/** Generated theme files. A color outside them is a second source, except the link-preview matte. */
export const COLOR_THEME = ["apps/web/src/ui/tokens/tokens.css", "apps/web/src/ui/tokens/values.ts"] as const;

/** The domain key for the link-preview matte. This file may spell only that hex. */
export const OG_MATTE_KEY_FILE = "apps/web/src/media/domain/og.ts";

/** The server that paints the link-preview JPEG. It reads `ogMatte` and does not spell the hex. */
export const OG_MATTE_FILE = "apps/web/src/media/server/og.ts";

/** Near-black matte. The same hex can name a different job later. */
export const OG_MATTE = "#0a0a0b";

const ROOTS = ["apps/web/src"] as const;

export type SourceFile = { readonly path: string; readonly text: string };

/** Production `.ts`, `.tsx`, and `.css`. Tests and `testing/` are not values the gate counts. */
export function productionSources(repo: string): SourceFile[] {
  const files: SourceFile[] = [];
  for (const root of ROOTS) collect(join(repo, root), repo, files);
  return files;
}

function collect(dir: string, repo: string, files: SourceFile[]): void {
  for (const name of readdirSync(dir)) {
    if (name === "testing" || name === "(test)") continue;
    const absolute = join(dir, name);
    if (statSync(absolute).isDirectory()) {
      collect(absolute, repo, files);
      continue;
    }
    if (!/\.(?:css|ts|tsx)$/.test(name) || /\.(?:int\.)?test\.tsx?$/.test(name)) continue;
    files.push({ path: relative(repo, absolute).split("\\").join("/"), text: readFileSync(absolute, "utf8") });
  }
}

/** Drops comments. A `//` inside a string or a template's text stays. A `${...}` hole is code. */
export function stripComments(source: string): string {
  const out = source.split("");
  let index = 0;
  const modes = ["code"];
  while (index < source.length) {
    const mode = modes[modes.length - 1];
    const char = source[index];
    if (mode === "sq" || mode === "dq") {
      if (char === "\\") {
        index += 2;
        continue;
      }
      if ((mode === "sq" && char === "'") || (mode === "dq" && char === "\"")) modes.pop();
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
      if (char === "$" && source[index + 1] === "{") {
        modes.push("code");
        index += 2;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'") {
      modes.push("sq");
      index += 1;
      continue;
    }
    if (char === "\"") {
      modes.push("dq");
      index += 1;
      continue;
    }
    if (char === "`") {
      modes.push("tmpl");
      index += 1;
      continue;
    }
    if (char === "/" && source[index + 1] === "/") {
      const end = source.indexOf("\n", index);
      const stop = end < 0 ? source.length : end;
      for (let cursor = index; cursor < stop; cursor += 1) out[cursor] = " ";
      index = stop;
      continue;
    }
    if (char === "/" && source[index + 1] === "*") {
      const found = source.indexOf("*/", index + 2);
      const stop = found < 0 ? source.length : found + 2;
      for (let cursor = index; cursor < stop; cursor += 1) if (out[cursor] !== "\n") out[cursor] = " ";
      index = stop;
      continue;
    }
    if (char === "}" && modes.length > 1 && modes[modes.length - 2] === "tmpl") {
      modes.pop();
      index += 1;
      continue;
    }
    index += 1;
  }
  return out.join("");
}

/** The only production file that may spell a reader phrase (D-050, UI text). */
export const UI_TEXT_CATALOG = "apps/web/src/site/domain/reader-copy.ts";

function lineAt(text: string, index: number): string {
  const start = text.lastIndexOf("\n", index - 1) + 1;
  const end = text.indexOf("\n", index);
  return text.slice(start, end < 0 ? text.length : end);
}

function coveredByLonger(text: string, at: number, phrase: string, phrases: readonly string[]): boolean {
  for (const longer of phrases) {
    if (longer.length <= phrase.length || !longer.includes(phrase)) continue;
    const start = at - longer.indexOf(phrase);
    if (start >= 0 && text.startsWith(longer, start)) return true;
  }
  return false;
}

function phraseBounded(text: string, at: number, phrase: string): boolean {
  if (!/[A-Za-z]/.test(phrase)) return true;
  const before = text[at - 1] ?? "";
  const after = text[at + phrase.length] ?? "";
  return !/[A-Za-z0-9_]/.test(before) && !/[A-Za-z0-9_]/.test(after);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A whole quoted phrase, not a prefix of a longer sentence or a path. */
function quotedWhole(text: string, at: number, phrase: string): boolean {
  const before = text[at - 1] ?? "";
  const after = text[at + phrase.length] ?? "";
  return (before === "\"" && after === "\"") || (before === "'" && after === "'");
}

/**
 * D-050 UI text. A reader phrase lives in `reader-copy.ts`.
 * A quoted phrase must be the whole literal: "Featured" is not the error "Featured course…", and an import path is not a label.
 * A phrase that contains a middle dot, or a sentence of 16 characters or more, is also refused inside a template.
 * A count noun is not in this list: `plural(` may not be given a string, because that noun is a key.
 * A CSS attribute selector may repeat a catalog phrase, because a selector cannot call the reader.
 * `key === "Home"` is the DOM key name, not the label.
 */
export function uiTextOffenders(files: readonly SourceFile[], phrases: readonly string[]): string[] {
  const sorted = [...new Set(phrases.filter((phrase) => phrase.length > 0))].sort((a, b) => b.length - a.length);
  const offenders: string[] = [];
  for (const file of files) {
    if (file.path === UI_TEXT_CATALOG) continue;
    const text = stripComments(file.text);
    for (const match of text.matchAll(/plural\s*\(([^)]*)\)/g)) {
      const args = match[1] ?? "";
      if (/["'`]/.test(args)) offenders.push(`${file.path}: plural(${args.trim()})`);
    }
    for (const phrase of sorted) {
      const embedded = phrase.includes("·") || (phrase.includes(" ") && phrase.length >= 16);
      let from = 0;
      while (from < text.length) {
        const at = text.indexOf(phrase, from);
        if (at < 0) break;
        from = at + phrase.length;
        const whole = quotedWhole(text, at, phrase);
        if (!whole && !embedded) continue;
        if (embedded && !whole && (!phraseBounded(text, at, phrase) || coveredByLonger(text, at, phrase, sorted))) continue;
        const line = lineAt(text, at);
        if (/\bkey\s*===|\.key\b/.test(line)) continue;
        if (new RegExp(`\\[[^\\]]*data-[\\w-]+\\s*=\\s*["']${escapeRegExp(phrase)}["']\\]`).test(line)) continue;
        offenders.push(`${file.path}: ${JSON.stringify(phrase)}`);
      }
    }
  }
  return offenders;
}

function stripTokenUses(text: string): string {
  let current = text;
  for (;;) {
    const next = current.replace(/(?:rgb|hsl)a?\(\s*var\(\s*--[\w-]+\s*\)[^)]*\)/g, "").replace(/var\(\s*--[\w-]+\s*\)/g, "");
    if (next === current) return current;
    current = next;
  }
}

function lengths(text: string): string[] {
  return [...text.matchAll(/(?<![\w.-])\d+(?:\.\d+)?(?:px|rem|em|vw|vh|dvh|svh|lvh)\b/g)].map((match) => match[0]);
}

function colors(text: string): string[] {
  return [...text.matchAll(/#(?:[0-9a-fA-F]{3,8})\b|\b(?:rgb|hsl)a?\(/g)].map((match) => match[0]);
}

/**
 * D-050 colors. Theme colors live in the generated snapshot files.
 * The link-preview matte is the one color outside that theme, and only its key may spell that hex.
 */
export function colorOffenders(files: readonly SourceFile[]): string[] {
  const theme = new Set<string>(COLOR_THEME);
  const offenders: string[] = [];
  for (const file of files) {
    if (theme.has(file.path)) continue;
    const found = colors(stripTokenUses(stripComments(file.text)));
    if (file.path === OG_MATTE_KEY_FILE) {
      for (const visual of found) if (visual.toLowerCase() !== OG_MATTE) offenders.push(`${file.path}: ${visual}`);
      continue;
    }
    for (const visual of found) offenders.push(`${file.path}: ${visual}`);
  }
  return offenders;
}

/**
 * D-050 spacing. A unit length lives in the snapshot, written out as the spacing catalog.
 * A `@media` or `@supports` length cannot call `var()`, so it must be a catalog value exactly.
 * Unitless zero is not a length here.
 */
export function spacingOffenders(files: readonly SourceFile[], catalogValues: ReadonlySet<string>): string[] {
  const catalog = new Set<string>(SPACING_CATALOG);
  const offenders: string[] = [];
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const body = stripComments(file.text);
    if (!file.path.endsWith(".css")) {
      for (const visual of lengths(stripTokenUses(body))) offenders.push(`${file.path}: ${visual}`);
      continue;
    }
    for (const line of body.split("\n")) {
      if (/^\s*@(?:media|supports)\b/.test(line)) {
        for (const visual of lengths(line)) if (!catalogValues.has(visual)) offenders.push(`${file.path}: ${visual}`);
        continue;
      }
      for (const visual of lengths(stripTokenUses(line))) offenders.push(`${file.path}: ${visual}`);
    }
  }
  return offenders;
}

/** The only production file that may spell a limit or a timeout (D-050). */
export const LIMITS_CATALOG = ["apps/web/src/kernel/limits.ts"] as const;

/**
 * D-050 limits and timeouts.
 * A zod cap (`.max(`, `.min(` other than the non-empty floor, `label(`), a SQL upper bound,
 * a route or fetch timeout, and the media byte products `4 * 1024 * 1024`, `64 * 1024`, and `65536`
 * live in the catalog. `Math.max` is a clamp, not a cap.
 * Bare 0 and 1 are deferred to the extent keys. `.min(1)` is not a character cap.
 * `BETWEEN 1 AND` reads the upper bound here; the floor of one is `EXTENT.one`.
 */
export function limitOffenders(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(LIMITS_CATALOG);
  const offenders: string[] = [];
  const seen = new Set<string>();
  const push = (item: string) => {
    if (seen.has(item)) return;
    seen.add(item);
    offenders.push(item);
  };
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const text = stripComments(file.text);
    const rules = [
      /(?<!Math)\.max\(\s*\d[\d_]*\)?/g,
      /(?<!Math)\.min\(\s*(?!1\b)\d[\d_]*\)?/g,
      /\blabel\(\s*\d[\d_]*\)?/g,
      /char_length\([^\n]{0,220}?\)[^\n]{0,100}(?:<=\s*\d[\d_]*|BETWEEN\s+\d[\d_]*\s+AND\s+\d[\d_]*)/g,
      /BETWEEN\s+\d[\d_]*\s+AND\s+\d[\d_]*/g,
      /AbortSignal\.timeout\(\s*\d[\d_]*\)?/g,
      /\b(?:idleTimeoutMillis|connectionTimeoutMillis|statement_timeout|attemptTimeoutMs|totalTimeoutMs)\s*:\s*\d[\d_]*/g,
      /integer\(\s*"[^"]+"\s*,[^,\n]+,\s*\d[\d_]*/g,
      /\b64\s*\*\s*1024\b|\b65536\b|\b4\s*\*\s*1024\s*\*\s*1024\b/g,
    ];
    for (const rule of rules) {
      for (const match of text.matchAll(rule)) push(`${file.path}: ${match[0]}`);
    }
    for (const line of text.split("\n")) {
      if (!/\bspec\(/.test(line)) continue;
      const timeout = line.match(/,\s*(\d[\d_]*)\s*(?:,\s*["']safe["'])?\s*\)\s*,?\s*$/);
      const digits = timeout?.[1];
      if (digits) push(`${file.path}: spec timeout ${digits}`);
    }
  }
  return offenders;
}

/** The only production file that may spell a cache duration or a no-store policy (D-050). */
export const CACHE_CATALOG = ["apps/web/src/kernel/cache.ts"] as const;

/** `next.config.ts` sits outside `apps/web/src`, so the cache scan names it. */
export const CACHE_CONFIG = "apps/web/next.config.ts";

/**
 * D-050 cache.
 * A `revalidate` of a number or `false`, a Cache-Control max-age or stale-while-revalidate,
 * `cacheControlMaxAge`, `minimumCacheTTL`, the two Data Cache byte products, the session and
 * oEmbed duration products, and either spelling of `no-store` live in the catalog.
 * `expire: 0` is immediate expiry and reads `CACHE.immediateExpiry`. A bare 0 there is this domain.
 * `30 * 24 * 60 * 60 * 1000` is lifecycle retention, not a cache TTL.
 * `1024 * 1024` and `4 * 1024 * 1024` are body limits, not cache budgets.
 */
export function cacheOffenders(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(CACHE_CATALOG);
  const offenders: string[] = [];
  const seen = new Set<string>();
  const push = (item: string) => {
    if (seen.has(item)) return;
    seen.add(item);
    offenders.push(item);
  };
  const rules = [
    /(?<![\w-])revalidate\s*[:=]\s*(?:false|\d[\d_]*)/g,
    /max-age=\d[\d_]*/g,
    /stale-while-revalidate=\d[\d_]*/g,
    /\bcacheControlMaxAge\s*:\s*\d[\d_]*/g,
    /\bminimumCacheTTL\s*:\s*\d[\d_]*/g,
    /(?<![\d.])(?:1\.5|2)\s*\*\s*1024\s*\*\s*1024\b/g,
    /\b30\s*\*\s*24\s*\*\s*60\s*\*\s*60\b(?!\s*\*\s*(?:1000|1_000))/g,
    /\b24\s*\*\s*60\s*\*\s*60\b(?!\s*\*\s*(?:1000|1_000))/g,
    /\b24\s*\*\s*60\s*\*\s*60\s*\*\s*(?:1000|1_000)\b/g,
    /\b7\s*\*\s*24\s*\*\s*60\s*\*\s*60\s*\*\s*(?:1000|1_000)\b/g,
    /\b5\s*\*\s*60\b(?!\s*\*)/g,
    /\b86_?400_?000\b/g,
    /["']no-store["']/g,
    /\bexpire\s*:\s*0\b/g,
  ];
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const text = stripComments(file.text);
    for (const rule of rules) {
      for (const match of text.matchAll(rule)) {
        const at = match.index;
        // Lifecycle retention is `30 * 24 * 60 * 60 * 1000`. The 24-hour product is the suffix, not a second oEmbed window.
        if (match[0].startsWith("24") && /\*\s*$/.test(text.slice(0, at))) continue;
        // Next reads `export const revalidate` only as a literal. `satisfies typeof CACHE.<key>` locks that literal to the key.
        if (/^revalidate\s*=/.test(match[0]) && /^\s+satisfies\s+typeof\s+CACHE\.\w+/.test(text.slice(at + match[0].length))) continue;
        push(`${file.path}: ${match[0]}`);
      }
    }
  }
  return offenders;
}

/**
 * Status, lesson kind, and rights words. A call site of the editorial rules reads the key (D-050).
 * These modules are the spelling. The proof covers the named functions, not every quote in the tree.
 */
export const EDITORIAL_CATALOG = [
  "apps/web/src/catalog/domain/course-status.ts",
  "apps/web/src/catalog/domain/lesson-kind.ts",
  "apps/web/src/catalog/domain/schema/fields.ts",
] as const;

/** Functions this stage moved onto the enums. A loose word here fails the proof. */
export const EDITORIAL_CALLS = [
  "apps/web/src/catalog/domain/compile.ts",
  "apps/web/src/catalog/domain/incremental-compile.ts",
  "apps/web/src/catalog/domain/preview.ts",
  "apps/web/src/catalog/domain/rules/home.ts",
  "apps/web/src/catalog/domain/rules/lifecycle.ts",
  "apps/web/src/catalog/domain/cover-source.ts",
  "apps/web/src/catalog/domain/queries.ts",
  "apps/web/src/catalog/domain/schema/batch-v2.ts",
  "apps/web/src/catalog/domain/rules/status.ts",
  "apps/web/src/catalog/domain/slug-course.ts",
  "apps/web/src/catalog/domain/batch-plan.ts",
  "apps/web/src/catalog/domain/fields.ts",
] as const;

const EDITORIAL_WORD = /["'](?:published|draft|background|person)["']/g;

/**
 * D-050 editorial rules, for the functions named in this stage.
 * A quoted `published`, `draft`, `background`, or `person` outside the enum modules is a second spelling.
 * Provider comparisons and prose sentences are other words and stay.
 */
export function editorialLooseWords(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(EDITORIAL_CATALOG);
  const offenders: string[] = [];
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const text = stripComments(file.text);
    for (const match of text.matchAll(EDITORIAL_WORD)) offenders.push(`${file.path}: ${match[0]}`);
  }
  return offenders;
}

/** The only production file that may spell an empty result, the first element, or the floor of one (D-050). */
export const EXTENT_CATALOG = ["apps/web/src/kernel/extent.ts"] as const;

/** Functions this stage moved onto the extent keys. A bare empty result or a bare floor here fails the proof. */
export const EXTENT_CALLS = [
  "apps/web/src/catalog/server/table-io.ts",
  "apps/web/src/catalog/server/editions.ts",
  "apps/web/src/catalog/server/reference.ts",
  "apps/web/src/catalog/server/courses.ts",
  "apps/web/src/catalog/server/doctor.ts",
  "apps/web/src/catalog/domain/lesson-address.ts",
  "apps/web/src/catalog/domain/contracts.ts",
  "apps/web/src/platform/db/schema.ts",
] as const;

/**
 * D-050 extent, for the functions named in this stage.
 * `rows.length === 0` and `.min(1)` read `EXTENT`. The literal `BETWEEN 1 AND` does too.
 * `LIMIT 1` is the one row. A coefficient and a SQL default stay written.
 */
export function extentOffenders(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(EXTENT_CATALOG);
  const offenders: string[] = [];
  const rules = [/\.length\s*===\s*0\b/g, /\.min\(\s*1\)/g, /\bBETWEEN\s+1\s+AND\b/g];
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const text = stripComments(file.text);
    for (const rule of rules) {
      for (const match of text.matchAll(rule)) offenders.push(`${file.path}: ${match[0]}`);
    }
  }
  return offenders;
}

/** The only production file that may spell a page size (D-050). */
export const PAGINATION_CATALOG = ["apps/web/src/kernel/pagination.ts"] as const;

/**
 * D-050 pagination.
 * A SQL `LIMIT` other than 1, a full-page `rows.length` check, and the storage-walk cap
 * live in the catalog. `LIMIT 1` is the one row. `rows.length === 0` is an empty result,
 * a bare 0 deferred to the remainder. A bare `1000` is an area position or a text batch, not a page.
 * `windows.size > 10_000` is a rate-limit map cap, not this walk.
 */
export function paginationOffenders(files: readonly SourceFile[]): string[] {
  const catalog = new Set<string>(PAGINATION_CATALOG);
  const offenders: string[] = [];
  const seen = new Set<string>();
  const push = (item: string) => {
    if (seen.has(item)) return;
    seen.add(item);
    offenders.push(item);
  };
  const rules = [
    /\bLIMIT\s+(?!1\b)\d[\d_]*/g,
    /\brows\.length\s*(?:===|<)\s*(?!0\b)\d[\d_]*/g,
    /\bpages\s*>\s*\d[\d_]*/g,
  ];
  for (const file of files) {
    if (catalog.has(file.path)) continue;
    const text = stripComments(file.text);
    for (const rule of rules) {
      for (const match of text.matchAll(rule)) push(`${file.path}: ${match[0]}`);
    }
  }
  return offenders;
}
