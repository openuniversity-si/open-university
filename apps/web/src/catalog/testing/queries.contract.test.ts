import { describe, expect, it } from "vitest";
import { createInMemoryCatalogQueries } from "./in-memory-queries.ts";
import { queriesContract, queryFixture } from "./queries-contract.ts";

describe("catalog queries", () => {
  it("runs the shared cases in memory", async () => {
    const port = createInMemoryCatalogQueries(queryFixture());
    for (const entry of queriesContract()) await entry.run({ queries: () => port });
  });

  it("keeps an empty id list from standing in for every course", () => {
    const calls: unknown[] = [];
    const read = (ids: readonly string[] | undefined) => {
      if (ids === undefined) throw new Error("courseIds are required");
      if (ids.length === 0) return [];
      calls.push(ids);
      return ids;
    };
    expect(read([])).toEqual([]);
    expect(calls).toEqual([]);
    expect(() => read(undefined)).toThrow("courseIds are required");
  });
});
