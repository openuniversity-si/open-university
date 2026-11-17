import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseStoredRelease, type StoredRelease } from "../../src/catalog/domain/release.ts";
import { catalogTables, catalogTablesSchema, sortTables, type CatalogTables } from "../../src/catalog/domain/tables.ts";
import { jsonText, writeJson } from "./catalog-files.ts";

/** PostgreSQL's jsonb key order (shorter keys first, then bytewise): how the free-form JSON column `courses.legacy` is read. */
export function jsonbKeyOrder(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(jsonbKeyOrder);
  if (value === null || typeof value !== "object") return value;
  const bytes = (key: string) => Buffer.from(key, "utf8");
  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => bytes(a).length - bytes(b).length || Buffer.compare(bytes(a), bytes(b)));
  return Object.fromEntries(entries.map(([key, item]) => [key, jsonbKeyOrder(item)]));
}

/**
 * The bytes of a snapshot directory, from the current admin API: release keys in schema order, rows in key order and
 * `legacy` in jsonb order, so the same release and tables give the same bytes whatever order they arrived in.
 */
export function snapshotFiles(release: StoredRelease, tables: CatalogTables): Map<string, string> {
  const sorted = sortTables(catalogTablesSchema.parse(tables));
  const normalized = { ...sorted, courses: sorted.courses.map((course) => ({ ...course, legacy: jsonbKeyOrder(course.legacy) as typeof course.legacy })) };
  const files = new Map<string, string>([["release.json", jsonText(parseStoredRelease(release))]]);
  for (const { name } of catalogTables) files.set(`tables/${name}.json`, jsonText(normalized[name]));
  return files;
}

/** Writes a snapshot (tower-catalog snapshot); returns the files whose bytes changed. */
export function writeSnapshot(directory: string, release: StoredRelease, tables: CatalogTables): string[] {
  mkdirSync(resolve(directory, "tables"), { recursive: true });
  const changed: string[] = [];
  for (const [name, text] of snapshotFiles(release, tables)) {
    const path = resolve(directory, name);
    let before: string | null = null;
    try { before = readFileSync(path, "utf8"); } catch { before = null; }
    if (before === text) continue;
    writeJson(path, JSON.parse(text));
    changed.push(name);
  }
  return changed;
}

