import { expect, test } from "./fixtures/no-video-guard.ts";
import { PRODUCTION_ORIGIN } from "../src/site/domain/origin.ts";

/**
 * Production-like metadata guardian (`pnpm e2e:production`, ADR-13): every public page ships its title,
 * description, Open Graph, Twitter card, canonical, icons and manifest links; the icon, manifest and OG
 * files answer with the right content type. HTTP requests only, so no page (and no video) loads in a browser.
 */
const COURSE = "/c/biblical-series-genesis";
const LESSON = `${COURSE}/biblical-series-i-introduction-to-the-idea-of-god`;
const PAGES: readonly (readonly [path: string, title: string])[] = [
  ["/", "Open University — Great lecture courses, in order"],
  ["/privacy", "Privacy · Open University"],
  ["/terms", "Terms · Open University"],
  ["/contact", "Contact · Open University"],
  ["/about", "About · Open University"],
  [COURSE, "Genesis by Jordan B. Peterson · Open University"],
  [LESSON, "I: Introduction to the Idea of God · Genesis · Open University"],
];

function decode(value: string): string {
  return value.replaceAll("&amp;", "&").replaceAll("&quot;", '"').replaceAll("&#x27;", "'").replaceAll("&lt;", "<").replaceAll("&gt;", ">");
}

/** First tag of `name` whose attributes include `match`; returns the value of `attribute`. */
function attributeOf(html: string, name: string, match: string, attribute: string): string | undefined {
  for (const [tag] of html.matchAll(new RegExp(`<${name}\\s[^>]*>`, "g"))) {
    if (!tag.includes(match)) continue;
    const value = new RegExp(`\\s${attribute}="([^"]*)"`).exec(tag)?.[1];
    if (value !== undefined) return decode(value);
  }
  return undefined;
}

const meta = (html: string, match: string) => attributeOf(html, "meta", match, "content");
const link = (html: string, match: string) => attributeOf(html, "link", match, "href");
/** Next renders the root URL without its trailing slash; both spell the same URL. */
const normalized = (url: string | undefined) => (url === undefined ? undefined : new URL(url).href);

test.describe("every public page ships its metadata", () => {
  for (const [path, title] of PAGES) {
    test(`metadata on ${path}`, async ({ request }) => {
      const response = await request.get(path);
      expect(response.status()).toBe(200);
      const html = await response.text();
      const url = `${PRODUCTION_ORIGIN}${path}`;
      expect.soft(decode(/<title>([^<]*)<\/title>/.exec(html)?.[1] ?? ""), "title").toBe(title);
      expect.soft(meta(html, 'name="description"')?.length ?? 0, "description").toBeGreaterThanOrEqual(50);
      expect.soft(meta(html, 'property="og:title"'), "og:title").toBe(title);
      expect.soft(meta(html, 'property="og:description"'), "og:description").toBe(meta(html, 'name="description"'));
      expect.soft(meta(html, 'property="og:image"'), "og:image").toBe(`${PRODUCTION_ORIGIN}/brand/og.jpg`);
      expect.soft(normalized(meta(html, 'property="og:url"')), "og:url").toBe(url);
      expect.soft(meta(html, 'property="og:type"'), "og:type").toBe("website");
      expect.soft(meta(html, 'property="og:site_name"'), "og:site_name").toBe("Open University");
      expect.soft(meta(html, 'name="twitter:card"'), "twitter:card").toBe("summary_large_image");
      expect.soft(normalized(link(html, 'rel="canonical"')), "canonical").toBe(url);
      expect.soft(link(html, 'href="/icons/icon-192.png"'), "png icon").toBe("/icons/icon-192.png");
      expect.soft(link(html, 'href="/favicon.ico"'), "ico icon").toBe("/favicon.ico");
      expect.soft(link(html, 'rel="apple-touch-icon"'), "apple-touch-icon").toBe("/icons/apple-touch-icon.png");
      expect.soft(link(html, 'rel="manifest"'), "manifest").toBe("/manifest.webmanifest");
    });
  }

  const FILES: readonly (readonly [path: string, type: string])[] = [
    ["/favicon.ico", "image/x-icon"],
    ["/icons/favicon.ico", "image/x-icon"],
    ["/icons/apple-touch-icon.png", "image/png"],
    ["/icons/icon-192.png", "image/png"],
    ["/icons/icon-512.png", "image/png"],
    ["/manifest.webmanifest", "application/manifest+json"],
    ["/brand/og.jpg", "image/jpeg"],
  ];
  for (const [path, type] of FILES) {
    test(`${path} answers 200 as ${type}`, async ({ request }) => {
      const response = await request.get(path);
      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain(type);
    });
  }

  test("og.jpg is 1200×630", async ({ request }) => {
    const response = await request.get("/brand/og.jpg");
    expect(response.status()).toBe(200);
    const bytes = await response.body();
    // Walk the JPEG segments to the start-of-frame marker (SOF0–SOF2), which holds height then width.
    let offset = 2;
    while (offset < bytes.length && !(bytes[offset + 1] !== undefined && [0xc0, 0xc1, 0xc2].includes(bytes[offset + 1] ?? 0))) offset += 2 + bytes.readUInt16BE(offset + 2);
    expect([bytes.readUInt16BE(offset + 7), bytes.readUInt16BE(offset + 5)]).toEqual([1200, 630]);
  });

  test("the manifest names Open University and lists the 192 and 512 icons", async ({ request }) => {
    const response = await request.get("/manifest.webmanifest");
    expect(response.status()).toBe(200);
    const manifest = (await response.json()) as { name: string; icons: { src: string; sizes: string }[] };
    expect(manifest.name).toBe("Open University");
    expect(manifest.icons.map((icon) => `${icon.src} ${icon.sizes}`)).toEqual(["/icons/icon-192.png 192x192", "/icons/icon-512.png 512x512"]);
  });
});
