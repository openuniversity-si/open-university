import type { Page, Response } from "@playwright/test";
import pg from "pg";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";
import { seedProgress } from "./fixtures/progress.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { PUBLIC_STATIC_ROUTES } from "../src/site/domain/route-registry.ts";

const OTHER_PUBLIC_ROUTES = new Set<string>(PUBLIC_STATIC_ROUTES.filter((route) => route !== "/"));

/** ADR-16: static Home for visitors, the same Home per viewer behind a session cookie; never a shared signed-in page. */
const CLS_BUDGET = 0.03;

function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  return errors;
}
/** Every same-origin document and fetch (RSC, API) response: the ones that could carry viewer data. */
function watchAppResponses(page: Page, baseURL: string) {
  const responses: Response[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === new URL(baseURL).origin && ["document", "fetch"].includes(response.request().resourceType())) responses.push(response);
  });
  return responses;
}
async function layoutShift(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(() => new Promise<number>((resolve) => {
    let total = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!entry.hadRecentInput) total += entry.value;
    }).observe({ type: "layout-shift", buffered: true });
    setTimeout(() => { resolve(total); }, 1000);
  }));
}
async function expectHome(page: Page) {
  await expect(page.getByTestId("tower-billboard")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Course 1");
  await expect(page.getByTestId("tower-home-intro")).toBeVisible();
  await expect(page.getByTestId("tower-home-portals")).toBeVisible();
}

for (const width of [390, 1440]) {
  test(`visitor Home at ${String(width)} px is the cached static page`, async ({ page, baseURL }) => {
    if (!baseURL) throw new Error("baseURL is required.");
    await page.setViewportSize({ width, height: 844 });
    const errors = watchErrors(page);
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);
    expect(response?.headers()["cache-control"]).toMatch(/s-maxage=\d+/);
    expect(response?.headers()["x-nextjs-cache"]).toMatch(/HIT|STALE/);
    await expectHome(page);
    await expect(page.getByTestId("rail-continue-watching")).toHaveCount(0);
    expect(await layoutShift(page)).toBeLessThanOrEqual(CLS_BUDGET);
    expect(errors).toEqual([]);
  });
}

test("the internal signed-in route is not reachable directly", async ({ request }) => {
  expect((await request.get("/signed-in-home")).status()).toBe(404);
});

test.describe("signed-in Home", () => {
  let pool: pg.Pool;
  test.beforeAll(() => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required for signed-in e2e.");
    validateDatabaseUrl(connectionString, "container");
    pool = new pg.Pool({ connectionString });
  });
  test.afterAll(async () => { await pool.end(); });

  for (const width of [390, 1440]) {
    test(`at ${String(width)} px renders Continue watching per viewer and is never cacheable`, async ({ page, context, baseURL }) => {
      if (!baseURL) throw new Error("baseURL is required.");
      const viewer = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
      try {
        await seedProgress(pool, viewer.userId);
        await page.setViewportSize({ width, height: 844 });
        const errors = watchErrors(page);
        const responses = watchAppResponses(page, baseURL);
        const response = await page.goto("/");
        expect(response?.url()).toBe(`${baseURL}/`);
        await expectHome(page);
        await expect(page.locator("#content").getByTestId("rail-continue-watching").locator('[data-type="continue"]')).toHaveCount(3);
        expect(await layoutShift(page)).toBeLessThanOrEqual(CLS_BUDGET);
        // Guardian: nothing carrying this viewer's progress may be stored by a shared cache.
        expect(responses.length).toBeGreaterThan(0);
        for (const entry of responses) {
          // Prefetched public pages (the Universities and Authors tabs, legal pages) are the same for everyone and cacheable.
          if (OTHER_PUBLIC_ROUTES.has(new URL(entry.url()).pathname)) continue;
          const cacheControl = entry.headers()["cache-control"] ?? "";
          expect(cacheControl, entry.url()).not.toMatch(/public|s-maxage/);
          if (new URL(entry.url()).pathname === "/") expect(cacheControl, entry.url()).toMatch(/private.*no-store|no-store.*private/);
        }
        expect(errors).toEqual([]);
      } finally { await viewer.cleanup(); }
    });
  }
});
