import type { Page } from "@playwright/test";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

const WIDTHS = [767, 768, 1023, 1024, 1365, 1366, 1440, 1920, 1921, 2560] as const;
const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lessons = lessonsForCourse(catalog, course.id);
const first = lessons[0];
const last = lessons.at(-1);
if (!first || !last) throw new Error("Course lessons are required.");
const ROUTES = ["/", `/c/${course.slug}`, `/c/${course.slug}/${first.slug}`, `/c/${course.slug}/${last.slug}`, "/fixtures/states", "/fixtures/long-titles"] as const;

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}
async function width(page: Page, selector: string): Promise<number> {
  const target = page.locator(selector).first();
  await expect(target).toBeVisible();
  const box = await target.boundingBox();
  if (!box) throw new Error(`${selector} is not rendered.`);
  return box.width;
}

test.describe("responsive contracts (reference Chromium)", () => {
  test.skip(({ browserName, isMobile }) => browserName !== "chromium" || isMobile, "Width sweep runs on desktop Chromium.");

  for (const W of WIDTHS) {
    test(`${String(W)} px: no horizontal overflow, fixed cards, Player main/About/actions`, async ({ page }) => {
      await page.setViewportSize({ width: W, height: 900 });
      for (const route of ROUTES) {
        await page.goto(route);
        expect(await overflow(page), `${route} overflows at ${String(W)}`).toBe(0);
      }

      await page.goto("/");
      const cards = page.locator('[data-testid^="course-card-"]');
      const cardWidth = W >= 1024 ? 208 : 140;
      for (const box of await cards.evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width))) expect(box).toBe(cardWidth);

      for (const lesson of [first, last]) {
        await page.goto(`/c/${course.slug}/${lesson.slug}`);
        const main = await width(page, '[data-testid="player-stage"] > div:first-child');
        if (W >= 1024) expect(main).toBe(Math.min(W - 476, 1444));
        else expect(main).toBeLessThanOrEqual(W);
        const about = page.getByTestId("lecture-about").locator("p").first();
        if (W >= 1024 && (await about.count()) > 0) expect((await about.boundingBox())?.width).toBe(Math.min(720, main));
        // Actions wrap only when the row does not fit: one row whenever their natural width fits main.
        const actions = page.getByTestId("player-actions");
        const rows = await actions.evaluate((node) => new Set([...node.children].map((child) => Math.round(child.getBoundingClientRect().top))).size);
        const natural = await actions.evaluate((node) => {
          const children = [...node.children].filter((child) => child.getBoundingClientRect().width > 0);
          const gap = parseFloat(getComputedStyle(node).columnGap) || 0;
          return children.reduce((sum, child) => sum + child.getBoundingClientRect().width, 0) + gap * (children.length - 1);
        });
        const mainBox = await page.locator('[data-testid="player-stage"] > div:first-child').boundingBox();
        const right = await actions.evaluate((node) => Math.max(...[...node.children].map((child) => child.getBoundingClientRect().right)));
        expect(mainBox && right, `${lesson.slug} actions overflow main at ${String(W)}`).toBeLessThanOrEqual((mainBox?.x ?? 0) + main);
        if (W >= 1024 && natural <= main) expect(rows, `${lesson.slug} actions wrapped at ${String(W)}`).toBe(1);
      }
    });
  }
});

// @engine: mobile-only (skips on desktop): the meta-viewport layout of each mobile engine.
test("390 DOM contracts (every mobile engine): no overflow, 140 px cards, full-width Player", { tag: "@engine" }, async ({ page, isMobile }) => {
  test.skip(!isMobile, "Mobile projects only.");
  for (const route of ROUTES) {
    await page.goto(route);
    expect(await overflow(page), route).toBe(0);
  }
  await page.goto("/");
  for (const box of await page.locator('[data-testid^="course-card-"]').evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width))) expect(box).toBe(140);
  await page.goto(`/c/${course.slug}/${first.slug}`);
  expect(await width(page, '[data-testid="player-stage"] > div:first-child')).toBe(390);
  const actions = await page.getByTestId("player-actions").boundingBox();
  expect(actions && actions.x + actions.width).toBeLessThanOrEqual(390);
});
