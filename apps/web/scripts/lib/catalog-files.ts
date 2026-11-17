import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const appRoot = fileURLToPath(new URL("../../", import.meta.url));
export function readJson(path: string): unknown { return JSON.parse(readFileSync(path, "utf8")) as unknown; }
/** The repository's JSON file format: two-space indent and a final newline. */
export function jsonText(value: unknown): string { return `${JSON.stringify(value, null, 2)}\n`; }
export function writeJson(path: string, value: unknown): void {
  const temporary = `${path}.${String(process.pid)}.tmp`;
  writeFileSync(temporary, jsonText(value));
  renameSync(temporary, path);
}
export function reportFailure(error: unknown): void {
  console.error(error instanceof Error ? error.message : "Catalog command failed.");
  process.exitCode = 1;
}
