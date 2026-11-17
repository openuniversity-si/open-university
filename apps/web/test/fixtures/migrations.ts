import { readFileSync } from "node:fs";

/** How many migrations drizzle/ holds (its journal): the migration tests follow it instead of a hard-coded count. */
export const MIGRATION_COUNT = (JSON.parse(readFileSync(new URL("../../drizzle/meta/_journal.json", import.meta.url), "utf8")) as { entries: unknown[] }).entries.length;
