import { describe, expect, it } from "vitest";
import { toMetadata } from "../../app/to-metadata.ts";
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { readFileSync } from "node:fs";
import { courseMetadataInput, lessonMetadataInput } from "../../catalog/server/metadata.ts";
import { publicRouteSnapshot } from "../../catalog/server/public-routes.ts";
import { PRODUCTION_ORIGIN } from "./origin.ts";
import { PUBLIC_STATIC_ROUTES, publicCatalogRoutes } from "./route-registry.ts";
import { installSiteData, parseSiteData } from "./site-data.ts";
import { clippedDescription, courseMetadata, courseShareImage, coverShareImage, lessonMetadata, ogImage, pageMetadata, resolvedTitle, siteMetadata, staticPageMetadata, type PageMeta } from "./metadata.ts";

installSiteData(parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))));
const DEFAULT_TITLE = parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))).metadata.defaultTitle;
const OG_IMAGE = ogImage();

/** Every public page with the metadata its route resolves (static pages, then the whole catalog). */
const snapshot = publicRouteSnapshot(catalog);
const pages: readonly (readonly [path: string, metadata: PageMeta])[] = [
  ...PUBLIC_STATIC_ROUTES.map((route) => [route, staticPageMetadata(route)] as const),
  ...publicCatalogRoutes(snapshot).map((route) => [route.path, route.lessonSlug === undefined ? courseMetadata(courseMetadataInput(catalog, route.courseSlug)) : lessonMetadata(lessonMetadataInput(catalog, route.courseSlug, route.lessonSlug))] as const),
];

const absolute = (url: unknown) => new URL(String(url), siteMetadata().metadataBase).href;
const title = (metadata: PageMeta) => resolvedTitle(metadata.title);

describe("site metadata (ADR-13)", () => {
  it("maps each page onto the same title, description and image the domain returned", () => {
    expect(toMetadata(siteMetadata())).toEqual(siteMetadata());
    for (const [, metadata] of pages) expect(toMetadata(metadata)).toEqual(metadata);
  });

  it("covers every static page, course and lesson", () => {
    expect(pages).toHaveLength(PUBLIC_STATIC_ROUTES.length + catalog.courses.length + catalog.lessons.length);
  });

  it("points the browser icons at the Saturn PNGs", () => {
    expect(siteMetadata().icons).toEqual({
      icon: [{ url: "/icons/icon-192.png", type: "image/png", sizes: "192x192" }, { url: "/favicon.ico", sizes: "16x16 32x32 48x48" }],
      apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
    });
  });

  it("resolves the root defaults and the template", () => {
    expect(String(siteMetadata().metadataBase)).toBe(`${PRODUCTION_ORIGIN}/`);
    expect(siteMetadata().title).toEqual({ default: DEFAULT_TITLE, template: "%s · Open University" });
    expect(resolvedTitle("Privacy")).toBe("Privacy · Open University");
    expect(title(staticPageMetadata("/"))).toBe("Open University — Great lecture courses, in order");
  });

  it("gives every page a unique title of at most 70 characters", () => {
    const titles = pages.map(([, metadata]) => title(metadata));
    for (const [index, value] of titles.entries()) expect(value.length, pages[index]?.[0]).toBeLessThanOrEqual(70);
    expect(new Set(titles).size).toBe(titles.length);
  });

  for (const [path, metadata] of pages) {
    it(`ships description, canonical, Open Graph and Twitter on ${path}`, () => {
      const description = metadata.description ?? "";
      expect(description.length).toBeGreaterThanOrEqual(50);
      expect(description.length).toBeLessThanOrEqual(160);
      expect(absolute(metadata.alternates?.canonical)).toBe(`${PRODUCTION_ORIGIN}${path}`);
      const og = metadata.openGraph as { title?: string; description?: string; url?: string; type?: string; images?: { url: string; width: number; height: number }[] } | undefined;
      expect(og?.title).toBe(title(metadata));
      expect(og?.description).toBe(description);
      expect(og?.type).toBe("website");
      expect(absolute(og?.url)).toBe(`${PRODUCTION_ORIGIN}${path}`);
      const image = og?.images?.[0];
      expect(absolute(image?.url)).toMatch(/^https:\/\/openuniversity\.si\/.+\.jpg$/);
      expect([image?.width, image?.height]).toEqual([1200, 630]);
      expect((metadata.twitter as { card?: string } | undefined)?.card).toBe("summary_large_image");
    });
  }

  it("returns no page metadata, without throwing, for unknown slugs", () => {
    expect(courseMetadata(courseMetadataInput(catalog, "no-such-course"))).toEqual({});
    expect(lessonMetadata(lessonMetadataInput(catalog, "no-such-course", "x"))).toEqual({});
    expect(lessonMetadata(lessonMetadataInput(catalog, catalog.courses[0]?.slug ?? "", "no-such-lesson"))).toEqual({});
    expect(courseMetadata(null)).toEqual({});
  });
});

describe("clippedDescription", () => {
  it("keeps short text and cuts long text on whole sentences or words", () => {
    expect(clippedDescription("Short enough.")).toBe("Short enough.");
    const sentences = `${"A sentence that is long enough to count. ".repeat(4)}Tail sentence that will not fit at all here.`;
    expect(clippedDescription(sentences)).toBe("A sentence that is long enough to count. ".repeat(3).trim());
    const words = clippedDescription(`Opening. ${"word ".repeat(60)}`);
    expect(words.length).toBeLessThanOrEqual(160);
    expect(words).toMatch(/ word…$/);
  });
});

describe("share images: the course's own landscape art, the university cover, else the brand card", () => {
  const art = (kind: string, variant = "default") => ({ kind, variant, url: `https://media.openuniversity.si/covers/x/${kind}/a.jpg`, width: 1920, height: 1080 });
  it("prefers the 1200×630 og JPEG, then the desktop hero, then the still", () => {
    expect(courseShareImage([art("hero_desktop_16x9"), art("hero_desktop_16x9", "og")], "X").url).toContain("/hero_desktop_16x9/");
    expect(courseShareImage([art("hero_desktop_16x9"), { ...art("hero_desktop_16x9", "og"), url: "https://media.openuniversity.si/covers/x/og.jpg", width: 1200, height: 630 }], "X")).toMatchObject({ url: "https://media.openuniversity.si/covers/x/og.jpg", width: 1200, height: 630 });
  });
  it("prefers the desktop hero, then the still, default variant only", () => {
    expect(courseShareImage([art("thumb"), art("still_16x9"), art("hero_desktop_16x9")], "X").url).toContain("/hero_desktop_16x9/");
    expect(courseShareImage([art("hero_desktop_16x9", "alt"), art("still_16x9")], "X").url).toContain("/still_16x9/");
    expect(courseShareImage([art("poster_9x16")], "X")).toEqual(OG_IMAGE);
    expect(courseShareImage(undefined, "X")).toEqual(OG_IMAGE);
  });
  it("course and lesson pages put the course art in og:image and twitter:image", () => {
    const route = publicCatalogRoutes(snapshot).find((entry) => entry.lessonSlug !== undefined);
    if (!route?.lessonSlug) throw new Error("fixture has no lesson");
    const hero = art("hero_desktop_16x9");
    for (const metadata of [courseMetadata(courseMetadataInput(catalog, route.courseSlug, [hero])), lessonMetadata(lessonMetadataInput(catalog, route.courseSlug, route.lessonSlug, [hero]))]) {
      expect(JSON.stringify(metadata.openGraph?.images)).toContain(hero.url);
      expect(JSON.stringify(metadata.twitter?.images)).toContain(hero.url);
    }
    expect(JSON.stringify(courseMetadata(courseMetadataInput(catalog, route.courseSlug)).openGraph?.images)).toContain(OG_IMAGE.url);
  });
  it("a university page uses its cover, or the brand card", () => {
    const cover = { url: "https://media.openuniversity.si/covers/mit/university_cover_9x16/a.jpg", width: 1080, height: 1920 };
    expect(coverShareImage(cover, "MIT")).toEqual({ ...cover, alt: "MIT" });
    expect(coverShareImage(null, "MIT")).toEqual(OG_IMAGE);
    const og = { url: "https://media.openuniversity.si/covers/mit/university_og/a.jpg", width: 1200, height: 630 };
    expect(coverShareImage({ ...cover, og }, "MIT")).toEqual({ ...og, alt: "MIT" });
    const metadata = pageMetadata("/universities/mit", "d", "MIT", coverShareImage(cover, "MIT"));
    expect(JSON.stringify(metadata.openGraph?.images)).toContain(cover.url);
    expect(metadata.alternates?.canonical).toBe("/universities/mit");
  });
});
