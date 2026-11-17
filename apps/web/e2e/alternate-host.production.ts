import { expect, test } from "./fixtures/no-video-guard.ts";
import { ALTERNATE_HOSTS, CANONICAL_HOST, TEMPORARY_REDIRECT_HOSTS } from "../src/site/domain/hosts.ts";
import { PRODUCTION_ORIGIN } from "../src/site/domain/origin.ts";

/**
 * Production-like mode (`pnpm e2e:production`, ADR-12, ADR-19 and ADR-20): the canonical host openuniversity.si is indexable (no noindex, no blanket
 * Disallow) and names itself in the canonical link, robots.txt and sitemap; every alternate host only redirects (307 for thetower.si, 308 for the rest).
 */
for (const host of ALTERNATE_HOSTS) {
  const status = (TEMPORARY_REDIRECT_HOSTS as readonly string[]).includes(host) ? 307 : 308;
  test(`${host} redirects with ${String(status)}, keeping the path`, async ({ request }) => {
    for (const path of ["/", "/about", "/c/biblical-series-genesis"]) {
      const response = await request.get(path, { headers: { host }, maxRedirects: 0 });
      expect(response.status()).toBe(status);
      expect(new URL(response.headers().location ?? "").href).toBe(new URL(path, PRODUCTION_ORIGIN).href);
    }
  });
}

test.describe(`${CANONICAL_HOST} in production`, () => {
  for (const path of ["/", "/about", "/c/biblical-series-genesis"]) {
    test(`${path} is indexable and canonical points at ${CANONICAL_HOST}`, async ({ request }) => {
      const response = await request.get(path, { headers: { host: CANONICAL_HOST } });
      expect(response.status()).toBe(200);
      expect(response.headers()["x-robots-tag"]).toBeUndefined();
      const html = await response.text();
      expect(html).toContain('<meta name="robots" content="index, follow"/>');
      expect(html).toContain(`<link rel="canonical" href="${PRODUCTION_ORIGIN}${path === "/" ? "" : path}"/>`);
    });
  }

  test("robots.txt allows pages and points at the canonical sitemap", async ({ request }) => {
    const body = await (await request.get("/robots.txt", { headers: { host: CANONICAL_HOST } })).text();
    expect(body).toMatch(/^Allow: \/$/m);
    expect(body).not.toMatch(/^Disallow: \/$/m);
    expect(body).toContain(`Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`);
  });

  test("sitemap.xml lists only canonical URLs", async ({ request }) => {
    const body = await (await request.get("/sitemap.xml", { headers: { host: CANONICAL_HOST } })).text();
    const urls = [...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1] ?? "");
    expect(urls.length).toBeGreaterThan(100);
    for (const url of urls) expect(url.startsWith(`${PRODUCTION_ORIGIN}/`), url).toBe(true);
  });
});
