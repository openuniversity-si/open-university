import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import { APPROVED_FONT_SHA256, APPROVED_LOCAL_FONT } from "./fixtures/approved-font.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

/** P8: posters below the eager rows/cards are requested only near the viewport (200 px), and all of them load on scroll. */
const ROUTE = "/fixtures/lazy-posters";
const POSTERS = "**/fixtures/lazy-posters/poster/*.svg";
const NEAR = 200;
const TOTAL = 8 * 24;
/** Held back long enough that the first paint always uses the fallback, so the swap itself is measured. */
const FONT_DELAY_MS = 500;
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="540" height="960"><rect width="540" height="960" fill="#334"/></svg>';

function servePosters(page: Page) {
  const requested = new Set<string>();
  void page.route(POSTERS, async (route) => {
    requested.add(new URL(route.request().url()).pathname.split("/").at(-1)?.replace(".svg", "") ?? "");
    await route.fulfill({ contentType: "image/svg+xml", body: SVG });
  });
  return requested;
}
/** Card ids and image alts in DOM order (the live <img>, not the <noscript> fallback). */
function cardOrder(page: Page) {
  return page.locator('[data-testid^="course-card-fixture-"]').evaluateAll((cards) => cards.map((card) => `${card.getAttribute("data-testid") ?? ""}|${card.querySelector("img")?.getAttribute("alt") ?? "missing"}`));
}

// @engine: WebKit has no IntersectionObserver scrollMargin (src/ui/LazyPoster/near.ts) and each engine swaps fonts and lays out rails itself.
test("requests only the posters near the first viewport, then every poster on scroll, without shifts", { tag: "@engine" }, async ({ page }) => {
  // The only local "Inter" the browser can paint first is the approved font the page then downloads.
  expect([...new Set(execFileSync("fc-list", ["-f", "%{file}\\n", "Inter"], { encoding: "utf8" }).split("\n").filter(Boolean))]).toEqual([APPROVED_LOCAL_FONT]);
  test.setTimeout(120_000); // 192 cards scrolled in one by one; WebKit needs ~40 s
  const requested = servePosters(page);
  const fonts: { status: number; sha256: string }[] = []; // every font response the page received
  await page.route("**/_next/static/media/*.woff2", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, FONT_DELAY_MS));
    const response = await route.fetch();
    fonts.push({ status: response.status(), sha256: createHash("sha256").update(await response.body()).digest("hex") });
    await route.fulfill({ response });
  });
  await page.addInitScript(() => {
    (window as unknown as { towerShift: number }).towerShift = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!entry.hadRecentInput) (window as unknown as { towerShift: number }).towerShift += entry.value;
    }).observe({ type: "layout-shift", buffered: true });
  });
  const response = await page.goto(ROUTE);
  const html = await response?.text() ?? "";
  // Only the eager cards of the first row carry a src in the HTML (ADR-23, #137), and no poster is preloaded.
  expect(html.replaceAll(/<noscript>.*?<\/noscript>/g, "").match(/<img[^>]* src="\/fixtures\/lazy-posters\/poster\//g)).toHaveLength(3);
  expect(html).not.toMatch(/rel="preload"[^>]*lazy-posters/);
  await page.waitForLoadState("networkidle");
  const before = await cardOrder(page);
  expect(before).toHaveLength(TOTAL);
  expect(before.every((entry) => entry.endsWith("|"))).toBe(true);

  const viewport = page.viewportSize() ?? { width: 0, height: 0 };
  // On-demand cards (no src in the HTML) farther than the margin from the first viewport, on either axis.
  const far = await page.locator('[data-testid^="course-card-fixture-"]:has(img[data-poster-src])').evaluateAll((cards, [width, height, near]) => cards.flatMap((card) => {
    const box = card.getBoundingClientRect();
    return box.top > height + near || box.left > width + near ? [(card.getAttribute("data-testid") ?? "").replace("course-card-", "")] : [];
  }), [viewport.width, viewport.height, NEAR + 50] as const);
  expect(far.length).toBeGreaterThan(TOTAL / 2);
  expect(far.filter((id) => requested.has(id))).toEqual([]);
  expect(requested.has("fixture-3-1")).toBe(false);

  // Bring every card into view, rail by rail, the way a reader scrolls (WebKit has no IntersectionObserver scrollMargin,
  // so a card is only "near" once its rail scrolls it in; page-sized programmatic jumps skipped some in WebKit).
  await page.locator('[data-testid^="course-card-fixture-"]').evaluateAll(async (cards) => {
    for (const card of cards) {
      card.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
      // Observe the actual result of IO/native lazy loading before moving on. Cards
      // already loaded by the near margin need no actionability/frame polling.
      const image = card.querySelector("img");
      if (!image) throw new Error("Every fixture card must contain its poster");
      if (!image.complete || image.naturalWidth === 0) {
        await new Promise<void>((resolve, reject) => {
          image.addEventListener("load", () => { resolve(); }, { once: true });
          image.addEventListener("error", () => { reject(new Error("Poster failed to load")); }, { once: true });
        });
      }
    }
  });
  await page.evaluate(() => { window.scrollTo(0, document.body.scrollHeight); });
  await expect.poll(() => requested.size).toBe(TOTAL);
  await expect.poll(() => page.locator('[data-testid^="course-card-fixture-"] img:not(noscript img)').evaluateAll((images) => images.filter((image) => !(image as HTMLImageElement).complete || (image as HTMLImageElement).naturalWidth === 0).length)).toBe(0);
  expect(await cardOrder(page)).toEqual(before);
  // The page used the approved Inter bytes (HTTP 200, same SHA-256) and the late swap from the fallback moved nothing.
  expect(await page.evaluate(() => document.fonts.status)).toBe("loaded");
  expect([...new Set(fonts.map(({ status, sha256 }) => `${String(status)} ${sha256}`))]).toEqual([`200 ${APPROVED_FONT_SHA256}`]); // WebKit fetches twice
  expect(await page.evaluate(() => (window as unknown as { towerShift: number }).towerShift)).toBe(0);
});

// @engine: native loading="lazy" thresholds are engine-specific.
test("without IntersectionObserver every poster falls back to native lazy loading", { tag: "@engine" }, async ({ page }) => {
  servePosters(page);
  await page.addInitScript(() => { Reflect.deleteProperty(window, "IntersectionObserver"); });
  await page.goto(ROUTE);
  const live = page.locator('[data-testid^="course-card-fixture-"] img[data-poster-src]');
  await expect(live).toHaveCount(TOTAL - 3);
  await expect.poll(() => live.evaluateAll((images) => images.filter((image) => image.getAttribute("src") === image.getAttribute("data-poster-src") && image.getAttribute("loading") === "lazy").length)).toBe(TOTAL - 3);
});
