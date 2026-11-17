import { describe, expect, it } from "vitest";
import { rejectedRasterFiles } from "./repo-assets.ts";

describe("repo raster allowlist", () => {
  it("allows the logo, wordmark, OG brand card and icons only", () => {
    expect(rejectedRasterFiles([
      "apps/web/public/brand/logo.png", "apps/web/public/brand/wordmark.webp", "apps/web/public/brand/og.jpg",
      "apps/web/public/icons/favicon.ico", "apps/web/public/icons/icon-512.png", "apps/web/src/app/page.tsx",
    ])).toEqual([]);
  });

  it("rejects covers and other brand images", () => {
    const files = ["apps/web/public/brand/og-genesis.jpg", "apps/web/public/brand/cover.jpg", "apps/web/public/covers/genesis.jpg", "apps/web/src/app/favicon.ico", "apps/web/public/og.jpg"];
    expect(rejectedRasterFiles(files)).toEqual(files);
  });
});
