import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { assertWithinBudget, MEDIA_BYTE_BUDGETS, MediaBudgetError, overBudget } from "./budget.ts";

describe("media byte budgets", () => {
  it("allows up to the budget and refuses one byte more, unless forced", () => {
    expect(overBudget("poster_9x16", 120 * 1024)).toBeUndefined();
    expect(overBudget("poster_9x16", 120 * 1024 + 1)).toBe("poster_9x16 is 121 KiB, over its 120 KiB budget. Resize/compress it (WebP q≈78) or force a conscious exception with --force-oversize.");
    expect(() => { assertWithinBudget("thumb", 61 * 1024); }).toThrow(MediaBudgetError);
    expect(() => { assertWithinBudget("thumb", 61 * 1024, true); }).not.toThrow();
  });

  it("is the budget table the media command enforces", () => {
    const source = readFileSync(new URL("../../../scripts/lib/catalog-cli/commands/media.ts", import.meta.url), "utf8");
    expect(source).toContain("MEDIA_BYTE_BUDGETS");
    expect(source).not.toContain("budget_of");
    expect(MEDIA_BYTE_BUDGETS.poster_9x16).toBe(120 * 1024);
  });
});
