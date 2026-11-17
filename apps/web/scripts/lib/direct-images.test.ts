import { describe, expect, it } from "vitest";
import { assertDirectImages } from "./direct-images.ts";

describe("built image delivery guard", () => {
  it("rejects optimizer config and generated optimizer URLs", () => {
    for (const images of [undefined, { unoptimized: false }, { unoptimized: true, loaderFile: "paid.ts" }, { unoptimized: true, loader: "imgix" }]) {
      expect(() => { assertDirectImages({ images }, ""); }).toThrow();
    }
    for (const html of ['<img src="/_next/image?url=x">', '<img srcset="%2F_next%2Fimage?url=x 640w">', '<img src="/cdn-cgi/image/width=96/x">']) {
      expect(() => { assertDirectImages({ images: { unoptimized: true } }, html); }).toThrow();
    }
    expect(() => { assertDirectImages({ images: { unoptimized: true } }, '<img src="/brand/og.jpg">'); }).not.toThrow();
  });
});
