import { describe, expect, it } from "vitest";
import { PAGINATION } from "./pagination.ts";

describe("D-050 page sizes", () => {
  it("keeps today's page, batch, and walk cap as separate keys", () => {
    expect(PAGINATION.objectListPage).toBe(500);
    expect(PAGINATION.idempotencySweep).toBe(500);
    expect(PAGINATION.maxStoragePages).toBe(10_000);
    expect(PAGINATION.objectListPage).not.toBe(PAGINATION.maxStoragePages);
  });
});
