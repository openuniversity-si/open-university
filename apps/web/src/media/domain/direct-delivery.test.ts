import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import config from "../../../next.config.ts";
import { MediaImage } from "../client/MediaImage.tsx";
import { MEDIA_PUBLIC_HOST, type MediaAsset } from "./types.ts";

describe("direct image delivery (H1)", () => {
  it("disables the optimizer globally, without a replacement service", () => {
    expect(config.images?.unoptimized).toBe(true);
    expect(config.images?.loaderFile).toBeUndefined();
    expect(config.images?.loader ?? "default").toBe("default");
  });

  it("renders the immutable origin URL with the same dimensions, class and alt, even without Next config", () => {
    const url = `https://${MEDIA_PUBLIC_HOST}/covers/lesson-1/cover_16x9/${"a".repeat(40)}.jpg`;
    const asset = { url, width: 1920, height: 1080, alt: "Lecture cover" } as MediaAsset;
    const html = renderToStaticMarkup(createElement(MediaImage, { asset, sizes: "96px", className: "cover" }));
    expect(html).toContain(`src="${url}"`);
    expect(html).toContain('width="1920" height="1080"');
    expect(html).toContain('alt="Lecture cover"');
    expect(html).toContain('class="cover"');
    expect(html).toContain('loading="lazy"');
    expect(html).not.toMatch(/\/_next\/image|srcSet=/i);
    expect(renderToStaticMarkup(createElement(MediaImage, { asset: undefined, sizes: "96px" }))).toContain("data-media-placeholder");
  });

  it("keeps image loaders centralized and rejects metered transformation URLs in product sources", () => {
    function walk(dir: string): string[] {
      return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        return entry.isDirectory() ? walk(path) : /\.(ts|tsx|css)$/.test(path) && !/\.test\./.test(path) ? [path] : [];
      });
    }
    for (const path of walk("src")) {
      const text = readFileSync(path, "utf8");
      expect(text, path).not.toMatch(/\/_next\/image|\/cdn-cgi\/image\/|images\.ctfassets\.net|\.imgix\.net|res\.cloudinary\.com/);
      expect(text, path).not.toMatch(/unoptimized\s*=\s*\{?\s*false|\bloader\s*=/);
      if (path !== join("src", "media", "client", "MediaImage.tsx")) expect(text, path).not.toMatch(/(?:from\s*|import\s*\()["']next\/image["']/);
    }
  });
});
