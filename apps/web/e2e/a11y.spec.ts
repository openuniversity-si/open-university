import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import pg from "pg";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";
import { seedProgress } from "./fixtures/progress.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { PAGE_ROUTES } from "./routes.ts";

// Verifies: REQ-web-wcag-22-aa
// The built site renders every page route and course page, the player and the not-found and error pages here.
// Verifies: UNIT:web
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lessons = lessonsForCourse(catalog, course.id);
const first = lessons[0];
const last = lessons.at(-1);
if (!first || !last) throw new Error("Course lessons are required.");
const PLAYER = `/c/${course.slug}/${first.slug}`;
const ROUTES = [...PAGE_ROUTES, ...catalog.courses.map((entry) => `/c/${entry.slug}`), PLAYER, `/c/${course.slug}/${last.slug}`,
  "/missing-shell-page", "/fixtures/error", "/fixtures/states", "/fixtures/long-titles"];

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(results.violations.map((v) => `${v.id} (${v.impact ?? "n/a"}): ${v.help} — ${v.nodes.map((node) => node.target.join(" ")).slice(0, 3).join(", ")}`)).toEqual([]);
}

type FakeWindow = Window & { __towerFakePlayback?: { emit(event: string): void }[] };

for (const path of ROUTES) {
  test(`axe finds no WCAG A/AA violations on ${path} @a11y`, async ({ page }) => {
    await page.goto(path);
    await axe(page);
  });
}

// @engine: :focus-visible heuristics are engine-specific.
test("axe: Selected card and Selected lesson, keyboard-focused @a11y", { tag: "@engine" }, async ({ page }) => {
  await page.goto("/authors");
  await page.getByTestId("course-card-course-2").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("course-card-course-2")).toHaveAttribute("aria-current", "true");
  await axe(page);
  await page.goto(`/c/${course.slug}`);
  // focus() does not wait for React hydration; Enter before handlers attach can follow the native link.
  await expect(page.getByTestId("course-lectures")).toHaveAttribute("data-hydrated", "true");
  await page.getByTestId(`playlist-item-${first.id}`).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(`playlist-item-${first.id}`)).toHaveAttribute("data-selected", "true");
  await axe(page);
});

test("axe: Player loading, playing and error states @a11y", async ({ page }) => {
  await page.goto(PLAYER);
  await page.waitForFunction(() => ((window as FakeWindow).__towerFakePlayback?.length ?? 0) > 0);
  await page.getByRole("button", { name: "Play lecture" }).click();
  await expect(page.getByRole("status", { name: "Loading lecture" })).toBeVisible();
  await axe(page);
  // Started: no control of ours; YouTube's own (in the embed) play, pause, seek and keyboard.
  await page.evaluate(() => { (window as FakeWindow).__towerFakePlayback?.at(-1)?.emit("playing"); });
  await expect(page.getByTestId("player-play")).toHaveCount(0);
  await expect(page.locator("#content").getByTestId("player-frame").getByRole("button")).toHaveCount(0);
  await axe(page);
  await page.evaluate(() => { (window as FakeWindow).__towerFakePlayback?.at(-1)?.emit("error"); });
  await expect(page.getByTestId("player-error")).toContainText("This lecture can’t play right now.");
  await axe(page);
});

test.describe("signed in", () => {
  let pool: pg.Pool;
  test.beforeAll(() => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required for signed-in a11y.");
    validateDatabaseUrl(connectionString, "container");
    pool = new pg.Pool({ connectionString });
  });
  test.afterAll(async () => { await pool.end(); });

  test("axe: Continue Watching, Current/Watched rows, progress and the open account menu @a11y", async ({ page, context, baseURL }) => {
    if (!baseURL) throw new Error("baseURL is required.");
    const viewer = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
    try {
      await seedProgress(pool, viewer.userId);
      for (const path of ["/", `/c/${course.slug}`, PLAYER]) {
        await page.goto(path);
        await axe(page);
      }
      await page.getByTestId("tower-topnav-avatar").click();
      await expect(page.getByRole("menu", { name: "Account" })).toBeVisible();
      await axe(page);
    } finally { await viewer.cleanup(); }
  });
});

/** Tab from the top: every stop is visible, labelled, shows a focus indicator, and stops follow reading order. */
async function tabStops(page: Page, count: number) {
  const stops: { name: string; testId: string; top: number; indicator: boolean }[] = [];
  for (let index = 0; index < count; index += 1) {
    await page.keyboard.press("Tab");
    stops.push(await page.evaluate(() => {
      const element = document.activeElement as HTMLElement;
      const style = getComputedStyle(element);
      const ring = getComputedStyle(element, "::after");
      const indicator = (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2) || style.boxShadow !== "none" || (ring.content !== "none" && ring.borderTopStyle === "solid");
      const name = (element.getAttribute("aria-label") ?? element.textContent).replace(/\s+/g, " ").trim();
      return { name: `${element.tagName.toLowerCase()} ${name.slice(0, 30)}`, testId: element.dataset.testid ?? "", top: element.getBoundingClientRect().top + scrollY, indicator };
    }));
  }
  return stops;
}

test("keyboard: Player Tab order is skip link → TopNav → Play lecture → lecture navigation, all with a visible indicator", async ({ page, isMobile }) => {
  test.skip(isMobile, "Desktop keyboard order; mobile engines are covered by the human review.");
  await page.goto(PLAYER);
  // Tab only after hydration: under parallel load the Play button can still be server markup that React replaces.
  await page.waitForLoadState("networkidle");
  await expect(page.locator("#content").getByRole("button", { name: "Play lecture" })).toBeEnabled();
  const stops = await tabStops(page, 9);
  expect(stops.map((stop) => stop.name)).toEqual([
    "a Skip to content",
    "a Back to course",
    "a Open University, Home",
    "a Home",
    "a Universities",
    "a Authors",
    "button Sign in",
    "button Play lecture",
    "a Next lecture",
  ]);
  expect(stops.filter((stop) => !stop.indicator).map((stop) => stop.name)).toEqual([]);
});

test("keyboard: Home Tab reaches the Billboard CTA before the rails and every stop shows a focus indicator", async ({ page, isMobile }) => {
  test.skip(isMobile, "Desktop keyboard order.");
  await page.goto("/authors");
  const stops = await tabStops(page, 12);
  expect(stops.filter((stop) => !stop.indicator).map((stop) => stop.name)).toEqual([]);
  const start = stops.findIndex((stop) => stop.name === "a Start");
  const firstCard = stops.findIndex((stop) => stop.testId.startsWith("course-card-"));
  expect(start).toBeGreaterThan(0);
  expect(firstCard).toBeGreaterThan(start);
  // Rail cards follow each other left to right.
  const cards = stops.slice(firstCard).filter((stop) => stop.testId.startsWith("course-card-") && stop.top === stops[firstCard]?.top);
  expect(cards.length).toBeGreaterThan(1);
});
