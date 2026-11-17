import type { Locator, Page } from "@playwright/test";
import pg from "pg";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";
import { seedProgress } from "./fixtures/progress.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";

const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lessons = lessonsForCourse(catalog, course.id);
const first = lessons[0];
if (!first) throw new Error("Course lessons are required.");
const HAIRLINE = "rgb(44, 44, 48)";
const WHITE = "rgb(255, 255, 255)";

/** FocusRing 293:14464 Shape=Rounded: 2 px white ring, 2 px gap, radius 4; `null` when not drawn. */
async function ring(target: Locator) {
  return target.evaluate((element) => {
    const style = getComputedStyle(element, "::after");
    if (style.content === "none" || style.borderTopStyle !== "solid") return null;
    return { inset: style.top, width: style.borderTopWidth, color: style.borderTopColor, radius: style.borderTopLeftRadius };
  });
}
const ROUNDED = { inset: "-4px", width: "2px", color: WHITE, radius: "4px" };

/** Reach the target with the keyboard (Shift+Tab, Tab), so :focus-visible matches in every engine. */
async function keyboardFocus(page: Page, target: Locator) {
  // Under parallel load the keyboard can run before hydration finishes and React replaces the focused node; wait for it.
  await page.waitForLoadState("networkidle");
  await target.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(target).toBeFocused();
}
const canHover = (page: Page) => page.evaluate(() => matchMedia("(hover: hover) and (pointer: fine)").matches);

// @engine: pointer activation, hover media queries and :focus-visible differ with engine/input device.
test("CourseCard: hover lift, keyboard-only rounded ring, focus + Selected keeps both", { tag: "@engine" }, async ({ page }) => {
  await page.goto("/authors");
  const card = page.getByTestId("course-card-course-2");
  const frame = card.getByTestId("tower-card-poster");
  if (await canHover(page)) {
    await card.hover();
    await expect(frame).toHaveCSS("opacity", "1");
    await expect(frame).toHaveCSS("box-shadow", /rgba\(0, 0, 0, 0\.55\)/);
    await page.mouse.move(0, 0);
  }
  // Pointer activation selects without a focus ring.
  await card.click();
  await expect(card).toHaveAttribute("aria-current", "true");
  expect(await ring(card)).toBeNull();
  // Keyboard focus on another card: ring only; Enter selects and the ring stays with Selected.
  const other = page.getByTestId("course-card-course-3");
  await keyboardFocus(page, other);
  expect(await ring(other)).toEqual(ROUNDED);
  await expect(other).not.toHaveAttribute("aria-current");
  await page.keyboard.press("Enter");
  await expect(other).toHaveAttribute("aria-current", "true");
  await expect(other).toHaveAttribute("data-selected", "true");
  expect(await ring(other)).toEqual(ROUNDED);
  await expect(card).not.toHaveAttribute("aria-current");
});

// @engine: pointer activation, hover media queries and :focus-visible differ with engine/input device.
test("PlaylistItem: hover, keyboard ring, focus + Selected, Space opens; Escape is inert", { tag: "@engine" }, async ({ page }) => {
  await page.goto(`/c/${course.slug}`);
  const row = page.getByTestId(`playlist-item-${first.id}`);
  if (await canHover(page)) {
    await row.hover();
    await expect(row).toHaveCSS("background-color", HAIRLINE);
    await page.mouse.move(0, 0);
  }
  await keyboardFocus(page, row);
  expect(await ring(row)).toEqual(ROUNDED);
  await page.keyboard.press("Escape");
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("data-selected", "true");
  await expect(row).toHaveAttribute("aria-description", "Selected. Activate again to open the lesson.");
  await expect(row).toHaveCSS("background-color", HAIRLINE);
  expect(await ring(row)).toEqual(ROUNDED);
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}/${first.slug}$`));
});

// @engine: pointer activation, hover media queries and :focus-visible differ with engine/input device.
test("Player: focus + Now playing keeps aria-current and its row visuals under the ring", { tag: "@engine" }, async ({ page }) => {
  await page.goto(`/c/${course.slug}/${first.slug}`);
  const row = page.getByTestId("player-rail").getByTestId(`playlist-item-${first.id}`);
  await expect(row).toHaveAttribute("aria-current", "true");
  await keyboardFocus(page, row);
  expect(await ring(row)).toEqual(ROUNDED);
  await expect(row).toHaveAttribute("data-now-playing", "true");
  await expect(row).toHaveCSS("background-color", HAIRLINE);
});

test("PrimaryCTA secondary: hover turns the label white", async ({ page }) => {
  test.skip(!(await canHover(page)), "Hover needs a fine pointer.");
  await page.goto("/fixtures/states");
  const secondary = page.getByTestId("tower-secondary-cta");
  await expect(secondary).toHaveCSS("color", "rgba(242, 243, 245, 0.85)");
  await secondary.hover();
  await expect(secondary).toHaveCSS("color", WHITE);
});

// @engine: line-clamp is WebKit's legacy -webkit-line-clamp and differs between engines.
test("long titles: cards and playlist clamp to two lines with the full title as the name; Player title wraps freely", { tag: "@engine" }, async ({ page }) => {
  const LONG = "Awakening from the Fixture Course 4: The Complete Lecture Series and Commentary";
  await page.goto("/fixtures/long-titles");
  const cards = page.getByTestId("fixture-long-titles").getByRole("link");
  await expect(cards).toHaveCount(2);
  for (const card of await cards.all()) {
    await expect(card).toHaveAttribute("title", LONG);
    await expect(card).toHaveAttribute("aria-label", new RegExp(`^${LONG}`));
    const text = card.locator('[data-testid="tower-card-name"], [data-testid="tower-card-continue"] > span:first-child');
    const lines = await text.evaluate((element) => {
      const style = getComputedStyle(element);
      return { clamp: style.webkitLineClamp, lines: element.clientHeight / parseFloat(style.lineHeight), clipped: element.scrollHeight > element.clientHeight };
    });
    expect(lines.clamp).toBe("2");
    expect(lines.lines).toBeLessThan(3); // the row reserve is two lines plus leading
    expect(lines.clipped).toBe(true);
  }
  const row = page.getByTestId("playlist-item-long-title");
  await expect(row).toHaveAttribute("aria-label", /with an Extended Q&A, 2h 38m$/);
  const title = await row.locator("span > span").last().evaluate((element) => ({ clamp: getComputedStyle(element).webkitLineClamp, height: element.clientHeight, line: parseFloat(getComputedStyle(element).lineHeight) }));
  expect(title.clamp).toBe("2");
  expect(title.height).toBeLessThanOrEqual(title.line * 2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  // Longest catalog lesson title: no clamp, the whole title is laid out.
  const longest = [...catalog.lessons].sort((a, b) => b.displayTitle.length - a.displayTitle.length)[0];
  const owner = catalog.courses.find((entry) => entry.id === longest?.courseId);
  if (!longest || !owner) throw new Error("Catalog lessons are required.");
  await page.goto(`/c/${owner.slug}/${longest.slug}`);
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toHaveText(longest.displayTitle);
  expect(await heading.evaluate((element) => ({ clamp: getComputedStyle(element).webkitLineClamp, clipped: element.scrollHeight > element.clientHeight }))).toEqual({ clamp: "none", clipped: false });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("empty catalog has no CTA and no ghost cards", async ({ page }) => {
  await page.goto("/fixtures/states");
  const empty = page.getByTestId("tower-empty-catalog");
  await expect(empty.getByRole("heading", { name: "No courses yet" })).toBeVisible();
  await expect(empty.locator("a, button")).toHaveCount(0);
  await expect(empty.locator('[data-testid^="course-card-"], [data-testid="tower-course-card-skeleton"]')).toHaveCount(0);
});

test.describe("signed in", () => {
  let pool: pg.Pool;
  test.beforeAll(() => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required for signed-in states.");
    validateDatabaseUrl(connectionString, "container");
    pool = new pg.Pool({ connectionString });
  });
  test.afterAll(async () => { await pool.end(); });

  test("no history: Continue Watching and its space are gone; the first section is Explore", async ({ page, context, baseURL }) => {
    if (!baseURL) throw new Error("baseURL is required.");
    await page.goto("/");
    const signedOut = await page.locator("#content h2").first().boundingBox();
    const viewer = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
    try {
      await page.goto("/");
      await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
      await expect(page.getByTestId("rail-continue-watching")).toHaveCount(0);
      await expect(page.getByText("Continue Watching")).toHaveCount(0);
      await expect(page.locator("#content h2").first()).toHaveText("Explore");
      expect((await page.locator("#content h2").first().boundingBox())?.y).toBe(signedOut?.y);
    } finally { await viewer.cleanup(); }
  });

  // @engine: pointer activation, hover media queries and :focus-visible differ with engine/input device.
test("focus + Current keeps aria-current=step and the Resume meta under the ring", { tag: "@engine" }, async ({ page, context, baseURL }) => {
    if (!baseURL) throw new Error("baseURL is required.");
    const viewer = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
    try {
      await seedProgress(pool, viewer.userId);
      // Scoped to #content: while React streams, the hidden <div id="S:0"> keeps a copy of the page until it is swapped in.
      await page.goto(`/c/${course.slug}`);
      const current = page.locator("#content").locator('[data-testid^="playlist-item-"][aria-current="step"]');
      await expect(current).toHaveCount(1);
      await keyboardFocus(page, current);
      expect(await ring(current)).toEqual(ROUNDED);
      await expect(current).toHaveAttribute("data-status", "current");
      await expect(current).toHaveCSS("background-color", HAIRLINE);
      await expect(current).toHaveAttribute("aria-description", /^Resume/);
    } finally { await viewer.cleanup(); }
  });
});

test("prefers-reduced-motion: nothing animates or transitions on any route, including the Player spinner", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const moving = () => page.evaluate(() => [
    ...document.getAnimations().map((animation) => `animation ${animation instanceof CSSAnimation ? animation.animationName : animation.id}`),
    ...[...document.querySelectorAll("*")].filter((element) => getComputedStyle(element).transitionDuration.split(",").some((value) => parseFloat(value) > 0))
      .map((element) => `transition ${element.tagName.toLowerCase()}.${String(element.getAttribute("class")).slice(0, 40)}`),
  ]);
  for (const route of ["/", `/c/${course.slug}`, `/c/${course.slug}/${first.slug}`, "/fixtures/states"]) {
    await page.goto(route);
    expect(await moving(), route).toEqual([]);
  }
  await page.goto(`/c/${course.slug}/${first.slug}`);
  await page.getByRole("button", { name: "Play lecture" }).click();
  const spinner = page.getByTestId("player-loading");
  await expect(spinner).toBeVisible();
  expect(await moving()).toEqual([]);
});
