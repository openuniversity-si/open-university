import { expect, test } from "./fixtures/no-video-guard.ts";
import { PAGE_ROUTES } from "./routes.ts";

const NOINDEX = "noindex, nofollow";

/** Default e2e mode (no SITE_ENV): outside production everything is noindex. Production: indexing.production.ts. */
test.describe("noindex outside production", () => {
  for (const path of [...PAGE_ROUTES, "/api/health", "/robots.txt", "/sitemap.xml", "/route-that-does-not-exist"]) {
    test(`X-Robots-Tag on ${path}`, async ({ request }) => {
      const response = await request.get(path);
      expect(response.headers()["x-robots-tag"]).toBe(NOINDEX);
    });
  }

  test("robots.txt disallows everything", async ({ request }) => {
    const response = await request.get("/robots.txt");
    expect(response.status()).toBe(200);
    const body = await response.text();
    expect(body).toMatch(/User-Agent: \*/i);
    expect(body).toMatch(/^Disallow: \/$/m);
    expect(body).not.toMatch(/^Allow:/m);
  });

  for (const path of PAGE_ROUTES) {
    test(`meta robots on ${path}`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", NOINDEX);
    });
  }
});
