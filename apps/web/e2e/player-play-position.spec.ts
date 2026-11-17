import type { Page } from "@playwright/test";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lesson = lessonsForCourse(catalog, course.id)[3];
if (!lesson) throw new Error("Lesson is required.");
const route = `/c/${course.slug}/${lesson.slug}`;

/**
 * Idle glass play over the poster at the spec size (Figma PlayerFrame Default 287:12440), centred on the frame.
 * Turbopack orders the CSS chunks by module graph: the production build loads the CSS-module chunk before
 * globals.css (glass.css), the test build the other way round, so equal-specificity rules resolve differently.
 * The geometry is therefore measured in the bundle's order and with the stylesheets reversed (production's).
 */
async function measure(page: Page) {
  return page.evaluate(() => {
    const play = document.querySelector<HTMLElement>('[data-testid="player-play"]');
    const frame = document.querySelector<HTMLElement>('[data-testid="player-frame"]');
    if (!play || !frame) return null;
    const p = play.getBoundingClientRect();
    const f = frame.getBoundingClientRect();
    return {
      dx: p.x + p.width / 2 - (f.x + f.width / 2),
      dy: p.y + p.height / 2 - (f.y + f.height / 2),
      width: p.width,
      height: p.height,
      inside: p.left >= f.left && p.top >= f.top && p.right <= f.right && p.bottom <= f.bottom,
      hit: document.elementFromPoint(f.x + f.width / 2, f.y + f.height / 2)?.closest('[data-testid="player-play"]') === play,
    };
  });
}

async function expectCentred(page: Page, width: number, order: string): Promise<void> {
  await expect(page.getByTestId("player-play")).toBeVisible();
  const found = await measure(page);
  if (!found) throw new Error(`No play/frame at ${String(width)} (${order}).`);
  const size = width < 768 ? 24 : 40;
  const at = `${String(width)}, ${order}`;
  expect(Math.abs(found.dx), `play centre x at ${at}`).toBeLessThanOrEqual(1);
  expect(Math.abs(found.dy), `play centre y at ${at}`).toBeLessThanOrEqual(1);
  expect(Math.abs(found.width - size), `play width at ${at}`).toBeLessThanOrEqual(0.5);
  expect(Math.abs(found.height - size), `play height at ${at}`).toBeLessThanOrEqual(0.5);
  expect(found.inside, `play inside the frame at ${at}`).toBe(true);
  expect(found.hit, `play takes the tap at the frame centre at ${at}`).toBe(true);
}

test("idle glass play is centred on the frame at the spec size, whatever the CSS chunk order", async ({ page, isMobile }) => {
  test.skip(isMobile, "Both viewports are measured in desktop Chromium.");
  for (const [width, height] of [[390, 844], [1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(route);
    await expectCentred(page, width, "bundle order");
    const count = await page.evaluate(() => {
      const sheets = [...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')];
      for (const sheet of sheets.reverse()) document.head.append(sheet);
      return sheets.length;
    });
    expect(count, "stylesheets to reorder").toBeGreaterThan(1);
    await expectCentred(page, width, "reversed order");
  }
});
