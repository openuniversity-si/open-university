import { expect, test } from "./fixtures/no-video-guard.ts";
import { MEDIA_PUBLIC_HOST } from "../src/media/domain/types.ts";
import { ALTERNATE_HOSTS, CANONICAL_HOST, PERMANENT_REDIRECT_HOSTS, TEMPORARY_REDIRECT_HOSTS } from "../src/site/domain/hosts.ts";
import { PRODUCTION_ORIGIN } from "../src/site/domain/origin.ts";

/**
 * Alternate hosts (src/site/domain/hosts.ts, ADR-19/ADR-20): openuniversity.si is canonical and the only host that serves pages. thetower.si and www.thetower.si
 * answer 307 (temporary: The Tower gets its own site later) and the other Open University addresses 308, always to the same path and query on the
 * canonical origin. HTTP requests only (a `Host` header on the test server, redirects not followed), so no page or video loads in a browser.
 */
const COURSE = "/c/fixture-course-1";
const LESSON = `${COURSE}/fixture-lesson-1`;
const PATHS = ["/", "/about", "/terms", "/privacy", "/contact", COURSE, LESSON, "/sitemap.xml", "/robots.txt", "/api/health"] as const;

const attribute = (html: string, tag: string, match: string, name: string) => {
  for (const [element] of html.matchAll(new RegExp(`<${tag}\\s[^>]*>`, "g"))) {
    if (element.includes(match)) return new RegExp(`\\s${name}="([^"]*)"`).exec(element)?.[1];
  }
  return undefined;
};
/** Next renders the root URL without its trailing slash; both spell the same URL. */
const same = (url: string | undefined) => (url === undefined ? undefined : new URL(url).href);

for (const host of ALTERNATE_HOSTS) {
  const status = (TEMPORARY_REDIRECT_HOSTS as readonly string[]).includes(host) ? 307 : 308;
  test.describe(`${host} redirects with ${String(status)} to ${CANONICAL_HOST}`, () => {
    for (const path of PATHS) {
      test(`${path}: ${String(status)} to the same path on ${PRODUCTION_ORIGIN}`, async ({ request }) => {
        const response = await request.get(path, { headers: { host }, maxRedirects: 0 });
        expect(response.status()).toBe(status);
        expect(new URL(response.headers().location ?? "").href).toBe(new URL(path, PRODUCTION_ORIGIN).href);
      });
    }

    test("keeps the query string", async ({ request }) => {
      const response = await request.get("/c/fixture-course-1?utm_source=x&a=1", { headers: { host }, maxRedirects: 0 });
      expect(response.status()).toBe(status);
      expect(response.headers().location).toBe(`${PRODUCTION_ORIGIN}/c/fixture-course-1?utm_source=x&a=1`);
    });

    test("keeps the method for a POST (no body is turned into a GET)", async ({ request }) => {
      const response = await request.post("/api/auth/sign-out", { headers: { host }, maxRedirects: 0 });
      expect(response.status()).toBe(status);
      expect(response.headers().location).toBe(`${PRODUCTION_ORIGIN}/api/auth/sign-out`);
    });
  });
}

test("thetower.si moves are temporary (307), the second Open University domain permanent (308)", () => {
  expect([...TEMPORARY_REDIRECT_HOSTS].sort()).toEqual(["thetower.si", "www.thetower.si"]);
  expect(PERMANENT_REDIRECT_HOSTS).toContain("theopenuniversity.si");
});

test.describe(`${CANONICAL_HOST} and unknown hosts serve, with every pointer on the canonical origin`, () => {
  for (const host of [CANONICAL_HOST, "unknown-host.example.invalid", "evil-openuniversity.si", MEDIA_PUBLIC_HOST]) {
    test(`/about answers 200 without a redirect or a canonical Link header on ${host}`, async ({ request }) => {
      const response = await request.get("/about", { headers: { host }, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      expect(response.headers().location).toBeUndefined();
      expect(response.headers().link ?? "").not.toContain('rel="canonical"');
    });
  }

  for (const path of ["/", "/about", "/terms", COURSE, LESSON]) {
    test(`${path}: canonical link and og:url name ${PRODUCTION_ORIGIN}`, async ({ request }) => {
      const response = await request.get(path, { headers: { host: CANONICAL_HOST }, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      const html = await response.text();
      expect(same(attribute(html, "link", 'rel="canonical"', "href"))).toBe(same(`${PRODUCTION_ORIGIN}${path}`));
      expect(same(attribute(html, "meta", 'property="og:url"', "content"))).toBe(same(`${PRODUCTION_ORIGIN}${path}`));
    });
  }

  test("sitemap.xml lists only canonical URLs and robots.txt points at it", async ({ request }) => {
    const sitemap = await request.get("/sitemap.xml", { headers: { host: CANONICAL_HOST } });
    const urls = [...(await sitemap.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1] ?? "");
    expect(urls.length).toBeGreaterThan(100);
    for (const url of urls) expect(url.startsWith(`${PRODUCTION_ORIGIN}/`), url).toBe(true);
    const robots = await (await request.get("/robots.txt", { headers: { host: CANONICAL_HOST } })).text();
    for (const line of robots.split("\n").filter((entry) => /^sitemap:/i.test(entry))) expect(line).toBe(`Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`);
  });
});

test("the Terms explain Open University and disclaim any tie", async ({ request }) => {
  const html = await (await request.get("/terms", { headers: { host: CANONICAL_HOST } })).text();
  expect(html).toContain("Open University");
  expect(html).toContain("is not affiliated with, or endorsed by, The Open University (United Kingdom)");
});
