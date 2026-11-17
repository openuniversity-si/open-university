import { expect, test } from "./fixtures/no-video-guard.ts";
import { PRODUCTION_ORIGIN } from "../src/site/domain/origin.ts";

/**
 * Production-like mode (`pnpm e2e:production`, ADR-12): a build with SITE_ENV=production must be fully
 * indexable. HTTP requests only, so no page (and no video) is ever loaded in a browser.
 */
const COURSE = "/c/biblical-series-genesis";
const LESSON = `${COURSE}/biblical-series-i-introduction-to-the-idea-of-god`;

test.describe("production is indexable (SITE_ENV=production)", () => {
  for (const path of ["/", COURSE, LESSON, "/api/health", "/robots.txt", "/sitemap.xml"]) {
    test(`no X-Robots-Tag on ${path}`, async ({ request }) => {
      const response = await request.get(path);
      expect(response.status()).toBe(200);
      expect(response.headers()["x-robots-tag"]).toBeUndefined();
    });
  }

  for (const path of ["/", COURSE, LESSON]) {
    test(`meta robots index, follow on ${path}`, async ({ request }) => {
      const html = await (await request.get(path)).text();
      expect(html).toContain('<meta name="robots" content="index, follow"/>');
      expect(html).not.toMatch(/noindex|nofollow/);
    });
  }

  test("robots.txt allows pages, hides only /api/, points at the sitemap", async ({ request }) => {
    const body = await (await request.get("/robots.txt")).text();
    expect(body).toMatch(/^Allow: \/$/m);
    expect(body).not.toMatch(/^Disallow: \/$/m);
    expect(body).toMatch(/^Disallow: \/api\/$/m);
    expect(body).toContain(`Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`);
  });

  test("sitemap.xml lists the static pages, every course and lesson, and each one answers 200", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml")).text();
    const urls = [...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1] ?? "");
    expect(urls).toHaveLength(1 + 4 + 5 + 126);
    expect(urls).toContain(`${PRODUCTION_ORIGIN}${LESSON}`);
    for (const url of urls) {
      expect(url.startsWith(`${PRODUCTION_ORIGIN}/`)).toBe(true);
      expect((await request.get(url.slice(PRODUCTION_ORIGIN.length))).status(), url).toBe(200);
    }
  });

  test("admin API still requires credentials", async ({ request }) => {
    expect((await request.get("/api/admin/media")).status()).toBe(401);
    expect((await request.post("/api/admin/media/rollback")).status()).toBe(401);
  });
});
