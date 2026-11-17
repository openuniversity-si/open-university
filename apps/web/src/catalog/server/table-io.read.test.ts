import { describe, expect, it } from "vitest";
import { catalogTables } from "../domain/tables.ts";
import { readCatalogTables } from "./table-io.ts";

const HEAVY = new Set(["lessons", "lesson_videos", "catalog_texts"]);
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("readCatalogTables", () => {
  it("overlaps light reads, keeps one heavy read, and returns every table", async () => {
    let active = 0;
    let peak = 0;
    let heavy = 0;
    let heavyPeak = 0;
    const seen: string[] = [];
    const db = {
      async query(sql: string) {
        const name = /FROM "([^"]+)"/.exec(sql)?.[1] ?? "";
        seen.push(name);
        const isHeavy = HEAVY.has(name);
        active += 1;
        if (isHeavy) heavy += 1;
        peak = Math.max(peak, active);
        heavyPeak = Math.max(heavyPeak, heavy);
        await delay(20);
        active -= 1;
        if (isHeavy) heavy -= 1;
        return { rows: [{ rows: [] }] };
      },
    };
    const tables = await readCatalogTables(db);
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(3);
    expect(heavyPeak).toBe(1);
    expect(seen).toEqual(expect.arrayContaining(catalogTables.map((table) => table.name)));
    expect(tables.lessons).toEqual([]);
    expect(tables.courses).toEqual([]);
    expect(tables.licenses).toEqual([]);
  });
});
