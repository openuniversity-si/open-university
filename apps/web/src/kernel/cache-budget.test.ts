import { describe, expect, it } from "vitest";
import { CACHE_ENTRY_BUDGET_BYTES, CacheEntryOverBudget, assertCacheEntry, jsonBytes, loadWithinBudget } from "./cache-budget.ts";

describe("cache entry budget (D-037)", () => {
  it("accepts a value under 1.5 MB and refuses one over it", () => {
    assertCacheEntry({ ok: true });
    const over = "x".repeat(CACHE_ENTRY_BUDGET_BYTES + 1);
    expect(jsonBytes(over)).toBeGreaterThan(CACHE_ENTRY_BUDGET_BYTES);
    expect(() => { assertCacheEntry(over); }).toThrow(CacheEntryOverBudget);
  });

  it("halves a slice that does not fit in one entry", async () => {
    const seen: number[][] = [];
    const result = await loadWithinBudget([1, 2, 3, 4], (slice) => {
      if (slice.length > 1) throw new CacheEntryOverBudget(CACHE_ENTRY_BUDGET_BYTES + slice.length);
      seen.push([...slice]);
      const [first] = slice;
      return Promise.resolve(first);
    }, 4);
    expect(result).toEqual([1, 2, 3, 4]);
    expect(seen).toEqual([[1], [2], [3], [4]]);
  });
});
