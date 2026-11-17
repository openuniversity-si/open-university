import { describe, expect, it } from "vitest";
import { isSiteIndexable, NOINDEX_HEADER_VALUE } from "./indexing.ts";

describe("isSiteIndexable", () => {
  it.each([undefined, "", "false", "TRUE", "1", "true"])("is true in production whatever SITE_INDEXABLE is (%j)", (siteIndexable) => {
    expect(isSiteIndexable({ production: true, siteIndexable })).toBe(true);
  });

  it.each([{}, { SITE_ENV: "preview" }, { SITE_ENV: "development" }, { SITE_ENV: "Production" }, { SITE_ENV: "preview", SITE_INDEXABLE: "false" }])("is false for %j", (env) => {
    const siteIndexable = "SITE_INDEXABLE" in env ? env.SITE_INDEXABLE : undefined;
    expect(isSiteIndexable({ production: false, siteIndexable })).toBe(false);
  });

  it.each(["", "false", "TRUE", "True", "1", "yes", " true"])("ignores SITE_INDEXABLE=%j outside production", (siteIndexable) => {
    expect(isSiteIndexable({ production: false, siteIndexable })).toBe(false);
  });

  it("accepts the exact SITE_INDEXABLE=\"true\" opt-in", () => {
    expect(isSiteIndexable({ production: false, siteIndexable: "true" })).toBe(true);
  });

  it("blocks both indexing and link following", () => {
    expect(NOINDEX_HEADER_VALUE).toBe("noindex, nofollow");
  });
});
