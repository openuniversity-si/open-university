import { describe, expect, it } from "vitest";
import { CACHE, MEDIA_CACHE_CONTROL, PUBLIC_ASSET_CACHE_CONTROL } from "./cache.ts";
import { CACHE_CHUNK_ITEMS, CACHE_ENTRY_BUDGET_BYTES } from "./cache-budget.ts";

describe("D-050 cache", () => {
  it("keeps today's durations and the two no-store spellings", () => {
    expect(CACHE.homeSeconds).toBe(300);
    expect(CACHE.sitemapSeconds).toBe(3600);
    expect(CACHE.directorySeconds).toBe(86_400);
    expect(CACHE.mediaReadSeconds).toBe(86_400);
    expect(CACHE.publicAssetSeconds).toBe(86_400);
    expect(CACHE.untilTagged).toBe(false);
    expect(CACHE.sessionLifetimeSeconds).toBe(30 * 24 * 60 * 60);
    expect(CACHE.oembedFreshMs).toBe(24 * 60 * 60 * 1000);
    expect(CACHE.dayMs).toBe(86_400_000);
    expect(CACHE.responseNoStore).toBe("no-store");
    expect(CACHE.fetchNoStore).toBe("no-store");
    expect(CACHE.immediateExpiry).toBe(0);
    expect(CACHE_ENTRY_BUDGET_BYTES).toBe(CACHE.entryBudgetBytes);
    expect(CACHE_CHUNK_ITEMS).toBe(CACHE.chunkItems);
    expect(MEDIA_CACHE_CONTROL).toBe("public, max-age=31536000, immutable");
    expect(PUBLIC_ASSET_CACHE_CONTROL).toBe("public, max-age=86400, stale-while-revalidate=604800");
  });
});
