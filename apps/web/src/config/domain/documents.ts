import { authorKind, rightsStatus } from "../../catalog/domain/schema/fields.ts";
import { courseStatus } from "../../catalog/domain/course-status.ts";
import { lessonKind } from "../../catalog/domain/lesson-kind.ts";
import { STATUS_TRANSITIONS } from "../../catalog/domain/rules/status.ts";
import { invalid, revisionConflict } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import * as readerCopy from "../../site/domain/reader-copy.ts";
import { themeTokenNames } from "../../ui/tokens/names.ts";
import * as tokenValues from "../../ui/tokens/values.ts";

/** The four configuration kinds. Pagination and cache durations stay in code. */
export const CONFIG_KINDS = ["theme", "copy", "limits", "editorial"] as const;
export type ConfigKind = (typeof CONFIG_KINDS)[number];

export type ThemeDocument = Readonly<Record<string, string>>;
export type CopyDocument = Readonly<Record<string, string>>;
export type LimitsDocument = Readonly<Record<string, number>>;
export interface EditorialDocument {
  readonly lessonKind: Readonly<Record<string, string>>;
  readonly courseStatus: Readonly<Record<string, string>>;
  readonly rightsStatus: Readonly<Record<string, string>>;
  readonly authorKind: Readonly<Record<string, string>>;
  readonly statusTransitions: Readonly<Record<string, readonly string[]>>;
}
export type ConfigDocument = ThemeDocument | CopyDocument | LimitsDocument | EditorialDocument;

const STYLE_VALUE = /[;{}<>\n\r]/;
/** D-052. A binding is only a reference. A stored revision may not replace it with a private value. */
const THEME_BINDING = /^var\(--tower-[a-z0-9-]+\)$/;

/** `towerAccountPanelRight2` is the export of `--tower-account-panel-right-2`. */
export function exportNameToToken(ident: string): string {
  if (!Object.hasOwn(themeTokenNames, ident)) throw invalid(`Unknown theme token ${ident}.`);
  return themeTokenNames[ident as keyof typeof themeTokenNames];
}

function stringExports(bag: object): Record<string, string> {
  const body: Record<string, string> = {};
  for (const [key, value] of Object.entries(bag)) {
    if (typeof value === "string") body[key] = value;
  }
  return body;
}

/** Every generated theme token. The key is the CSS custom property without the leading dashes. */
export function codeTheme(): ThemeDocument {
  const body: Record<string, string> = {};
  const values = tokenValues as Record<string, unknown>;
  for (const ident of Object.keys(themeTokenNames)) {
    const value = values[ident];
    if (typeof value !== "string") throw invalid(`Theme token ${ident} is missing.`);
    body[themeTokenNames[ident as keyof typeof themeTokenNames]] = value;
  }
  return body;
}

/** Every reader-facing string. Functions stay in code. */
export function codeCopy(): CopyDocument {
  return stringExports(readerCopy);
}

/** The code ceilings. A stored limit may repeat one or go lower. It may not go higher. */
export function codeLimits(): LimitsDocument {
  return { ...LIMITS };
}

function copyRecord(source: Readonly<Record<string, string>>): Record<string, string> {
  return { ...source };
}

function copyTransitions(source: Readonly<Record<string, readonly string[]>>): Record<string, readonly string[]> {
  const body: Record<string, readonly string[]> = {};
  for (const [status, targets] of Object.entries(source)) body[status] = [...targets];
  return body;
}

/** The editorial vocabulary is the code. Only the transition map may later differ. */
export function codeEditorial(): EditorialDocument {
  return {
    lessonKind: copyRecord(lessonKind),
    courseStatus: copyRecord(courseStatus),
    rightsStatus: copyRecord(rightsStatus),
    authorKind: copyRecord(authorKind),
    statusTransitions: copyTransitions(STATUS_TRANSITIONS),
  };
}

export function codeDocument(kind: ConfigKind): ConfigDocument {
  if (kind === "theme") return codeTheme();
  if (kind === "copy") return codeCopy();
  if (kind === "limits") return codeLimits();
  return codeEditorial();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sameKeys(expected: readonly string[], actual: object): boolean {
  const got = Object.keys(actual);
  return got.length === expected.length && expected.every((key) => Object.hasOwn(actual, key));
}

function sameStrings(expected: Readonly<Record<string, string>>, actual: Readonly<Record<string, string>>): boolean {
  return sameKeys(Object.keys(expected), actual) && Object.keys(expected).every((key) => expected[key] === actual[key]);
}

/** Declarations that differ from the code theme. Empty when the served theme is the code. */
export function themeOverrideBlock(baseline: ThemeDocument, current: ThemeDocument): string {
  const lines: string[] = [];
  for (const key of Object.keys(baseline).sort()) {
    const value = current[key];
    if (value !== undefined && value !== baseline[key]) lines.push(`  --${key}: ${value};`);
  }
  return lines.length === 0 ? "" : `:root {\n${lines.join("\n")}\n}\n`;
}

export function parseTheme(input: unknown): ThemeDocument {
  const baseline = codeTheme();
  if (!isRecord(input) || !sameKeys(Object.keys(baseline), input)) throw invalid("Theme keys must stay the code keys.");
  const body: Record<string, string> = {};
  for (const key of Object.keys(baseline)) {
    const value = input[key];
    if (typeof value !== "string" || value.length === 0 || STYLE_VALUE.test(value)) throw invalid(`Theme value ${key} is outside the contract.`);
    const code = baseline[key];
    if (code !== undefined && THEME_BINDING.test(code) && value !== code) throw invalid(`Theme value ${key} is a binding.`);
    body[key] = value;
  }
  return body;
}

export function parseCopy(input: unknown): CopyDocument {
  const baseline = codeCopy();
  if (!isRecord(input) || !sameKeys(Object.keys(baseline), input)) throw invalid("Copy keys must stay the code keys.");
  const body: Record<string, string> = {};
  for (const key of Object.keys(baseline)) {
    const value = input[key];
    if (typeof value !== "string" || value.length === 0 || value.length > LIMITS.text) throw invalid(`Copy value ${key} is outside the contract.`);
    body[key] = value;
  }
  return body;
}

export function parseLimits(input: unknown): LimitsDocument {
  const baseline = codeLimits();
  if (!isRecord(input) || !sameKeys(Object.keys(baseline), input)) throw invalid("Limit keys must stay the code keys.");
  const body: Record<string, number> = {};
  for (const key of Object.keys(baseline)) {
    const value = input[key];
    const ceiling = baseline[key] ?? 0;
    if (typeof value !== "number" || !Number.isInteger(value) || value < 1 || value > ceiling) throw invalid(`Limit ${key} is outside the contract.`);
    body[key] = value;
  }
  return body;
}

function parseVocabulary(input: unknown, expected: Readonly<Record<string, string>>, label: string): Record<string, string> {
  if (!isRecord(input)) throw invalid(`${label} must keep the code words.`);
  const body: Record<string, string> = {};
  for (const [key, value] of Object.entries(input)) {
    if (typeof value !== "string") throw invalid(`${label} must keep the code words.`);
    body[key] = value;
  }
  if (!sameStrings(expected, body)) throw invalid(`${label} must keep the code words.`);
  return body;
}

export function parseEditorial(input: unknown): EditorialDocument {
  const baseline = codeEditorial();
  if (!isRecord(input)) throw invalid("Editorial value must be an object.");
  const lesson = parseVocabulary(input.lessonKind, baseline.lessonKind, "Lesson kinds");
  const course = parseVocabulary(input.courseStatus, baseline.courseStatus, "Course statuses");
  const rights = parseVocabulary(input.rightsStatus, baseline.rightsStatus, "Rights statuses");
  const author = parseVocabulary(input.authorKind, baseline.authorKind, "Author kinds");
  if (!isRecord(input.statusTransitions) || !sameKeys(Object.keys(baseline.statusTransitions), input.statusTransitions)) {
    throw invalid("Status transitions must name the code statuses.");
  }
  const transitions: Record<string, readonly string[]> = {};
  for (const status of Object.keys(baseline.statusTransitions)) {
    const targets = input.statusTransitions[status];
    if (!Array.isArray(targets) || targets.some((target) => typeof target !== "string" || !Object.hasOwn(course, target))) {
      throw invalid(`Status transitions from ${status} leave the contract.`);
    }
    if (new Set(targets).size !== targets.length) throw invalid(`Status transitions from ${status} repeat a target.`);
    transitions[status] = targets;
  }
  if (transitions[courseStatus.published]?.length !== 0) throw invalid("Published has no exit on the status route.");
  return { lessonKind: lesson, courseStatus: course, rightsStatus: rights, authorKind: author, statusTransitions: transitions };
}

export function parseDocument(kind: ConfigKind, input: unknown): ConfigDocument {
  if (kind === "theme") return parseTheme(input);
  if (kind === "copy") return parseCopy(input);
  if (kind === "limits") return parseLimits(input);
  return parseEditorial(input);
}

export function isConfigKind(value: string): value is ConfigKind {
  return (CONFIG_KINDS as readonly string[]).includes(value);
}

export type ConfigAction = "read" | "history" | "write" | "rollback";

/** A config admin path, or null when the path is not one of the four kinds. `action` null means the method is wrong. */
export function matchConfigRequest(method: string, pathname: string): { readonly kind: ConfigKind; readonly action: ConfigAction | null } | null {
  const parts = pathname.split("/").filter((part) => part.length > 0);
  if (parts.length < 4 || parts.length > 5 || parts[0] !== "api" || parts[1] !== "admin" || parts[2] !== "config") return null;
  const kind = parts[3];
  if (kind === undefined || !isConfigKind(kind)) return null;
  const tail = parts[4];
  if (tail === undefined) {
    if (method === "GET") return { kind, action: "read" };
    if (method === "PUT") return { kind, action: "write" };
    return { kind, action: null };
  }
  if (tail === "history") return { kind, action: method === "GET" ? "history" : null };
  if (tail === "rollback") return { kind, action: method === "POST" ? "rollback" : null };
  return null;
}

/** Empty style and an unchanged copy mean the shell HTML stays the code. */
export function servedShell(theme: ThemeDocument, copy: CopyDocument): { readonly style: string; readonly copyChanged: boolean } {
  const baseline = codeCopy();
  const keys = Object.keys(baseline);
  const copyChanged = keys.length !== Object.keys(copy).length || keys.some((key) => baseline[key] !== copy[key]);
  return { style: themeOverrideBlock(codeTheme(), theme), copyChanged };
}

/** The row after the one the caller saw. Zero means there is no row yet. */
export function nextStoredRevision(seen: number, expected: number): number {
  if (!Number.isInteger(seen) || seen < 0 || !Number.isInteger(expected) || expected < 0) throw invalid("Revision must be a whole number.");
  if (seen !== expected) throw revisionConflict(seen);
  return seen + 1;
}
