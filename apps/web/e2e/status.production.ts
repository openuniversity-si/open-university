import { TEST_REDIRECTS } from "../src/catalog/testing/fake.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

/**
 * Production-like mode (`pnpm e2e:production`, ADR-14/ADR-17): unknown slugs answer a real HTTP 404 and old ones a 308,
 * never a 200 "soft 404" streamed after loading.tsx. HTTP requests only, so no page (and no video) is loaded.
 */
const COURSE = "/c/biblical-series-genesis";
const LESSON = `${COURSE}/biblical-series-i-introduction-to-the-idea-of-god`;
const FOREIGN_LESSON = `${COURSE}/lecture-2017-maps-of-meaning-01-context-and-background`;

test.describe("HTTP status by construction", () => {
  for (const path of ["/zzz", "/c/zzz", `${COURSE}/zzz`, "/c/zzz/zzz", FOREIGN_LESSON]) {
    test(`404 on ${path}`, async ({ request }) => {
      const response = await request.get(path);
      expect(response.status()).toBe(404);
      expect(await response.text()).toContain("Page not found");
    });
  }

  for (const { from, to } of TEST_REDIRECTS) {
    test(`308 on ${from}`, async ({ request }) => {
      const response = await request.get(from, { maxRedirects: 0 });
      expect(response.status()).toBe(308);
      expect(response.headers().location).toContain(to);
    });
  }

  for (const path of ["/", COURSE, LESSON, "/privacy", "/terms", "/contact"]) {
    test(`200 on ${path}`, async ({ request }) => {
      expect((await request.get(path)).status()).toBe(200);
    });
  }
});
