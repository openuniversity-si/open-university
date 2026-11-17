import type { Page } from "@playwright/test";
import pg from "pg";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonAbout, lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lessons = lessonsForCourse(catalog, course.id);
function entry(index: number) {
  const lesson = lessons[index];
  if (!lesson) throw new Error("Lesson is required.");
  return lesson;
}
const route = (index: number) => `/c/${course.slug}/${entry(index).slug}`;
type FakeWindow = Window & { __towerFakePlayback?: { readonly position: number; readonly seeks: number[] }[] };
/** Signed out always starts at 0:00 (D1): the test build's engine never moved, whatever `?t=` says. */
async function startsAtZero(page: Page): Promise<void> {
  await page.waitForFunction(() => ((window as FakeWindow).__towerFakePlayback?.length ?? 0) > 0);
  expect(await page.evaluate(() => { const fake = (window as FakeWindow).__towerFakePlayback?.at(-1); return fake ? { position: fake.position, seeks: [...fake.seeks] } : null; })).toEqual({ position: 0, seeks: [] });
}

test("Home → Course → Player → previous/next → View lectures", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Course details" }).click();
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}$`));
  const row = page.getByTestId(`playlist-item-${entry(3).id}`);
  await row.click();
  await expect(row).toHaveAttribute("data-selected", "true");
  await row.click();
  await expect(page).toHaveURL(new RegExp(`${route(3)}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(entry(3).displayTitle);
  await page.getByTestId("player-previous").click();
  await expect(page).toHaveURL(new RegExp(`${route(2)}$`));
  await page.getByTestId("player-next").click();
  await expect(page).toHaveURL(new RegExp(`${route(3)}$`));
  const url = page.url();
  await page.getByTestId("player-view-lectures").click();
  await expect(page.getByTestId("player-rail")).toBeFocused();
  await expect(page.getByTestId("player-rail-header")).toBeInViewport();
  expect(page.url()).toBe(url);
  const playing = page.getByTestId(`playlist-item-${entry(3).id}`);
  await expect(playing).toHaveAttribute("aria-current", "true");
  await expect(playing).toHaveAttribute("data-selected", "false");
  const target = page.getByTestId(`playlist-item-${entry(4).id}`);
  await target.click();
  await expect(target).toHaveAttribute("data-selected", "true");
  await expect(playing).toHaveAttribute("aria-current", "true");
  expect(page.url()).toBe(url);
  await target.click();
  await expect(page).toHaveURL(new RegExp(`${route(4)}$`));
  await page.getByTestId("tower-topnav-back").click();
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}$`));
  await page.getByTestId("tower-topnav-back").click();
  await expect(page).toHaveURL(/\/$/);
});

test("first and last lesson navigation keeps the remaining action in place", async ({ page }) => {
  await page.goto(route(0));
  await expect(page.getByTestId("player-previous")).toHaveCount(0);
  await expect(page.getByTestId("player-next")).toBeVisible();
  const nav = await page.getByTestId("player-navigation").boundingBox();
  const next = await page.getByTestId("player-next").boundingBox();
  if (!nav || !next) throw new Error("Navigation geometry is required.");
  expect(Math.abs((nav.x + nav.width) - (next.x + next.width))).toBeLessThan(1);
  await page.goto(route(lessons.length - 1));
  await expect(page.getByTestId("player-next")).toHaveCount(0);
  await expect(page.getByTestId("player-previous")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to course", exact: true })).toHaveCount(2); // Header parent plus the single next action.
  await page.getByTestId("player-back-to-course").click();
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}$`));
});

test("poster reads t while keeping signed-out chrome empty and video absent", async ({ page }) => {
  await page.goto(`${route(3)}?t=3134`);
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-requested-second", "3134");
  await expect(page.getByTestId("player-page")).toHaveCSS("font-family", /Inter/);
  await startsAtZero(page);
  await expect(page.getByTestId("player-youtube")).toHaveCount(0);
  await expect(page.locator("video, mux-player")).toHaveCount(0);
  await expect(page.getByTestId("player-completion")).toHaveText("Mark complete");
  await expect(page.getByTestId("player-completion")).not.toHaveAttribute("aria-pressed"); // D1: no checks signed out.
  await expect(page.getByRole("button", { name: "Play lecture" })).toBeEnabled();
  await expect(page.getByTestId("tower-bottom-fade")).toHaveCount(0);
  await expect(page.getByTestId("tower-footer")).toHaveCSS("opacity", "1");
  await expect(page.getByTestId("player-lecture-list")).toHaveCSS("overflow-y", await page.evaluate(() => innerWidth >= 1024) ? "auto" : "visible");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("poster is the lesson's own cover, the same asset as its playlist thumbnail", async ({ page }) => {
  await page.goto(route(3));
  const original = async (selector: string) => {
    const src = await page.locator(selector).getAttribute("src");
    if (!src) throw new Error(`Missing image for ${selector}.`);
    // ADR-31 serves immutable originals directly; /_next/image?url=... was retired by H1.
    expect(src).toMatch(/^\/api\/media\/fixture\/[a-f0-9]{64}$/);
    return src;
  };
  const poster = await original('[data-testid="player-poster"] img');
  expect(poster).toMatch(/^\/api\/media\/fixture\//);
  expect(poster).toBe(await original(`[data-testid="playlist-item-${entry(3).id}"] [data-testid="playlist-thumb"] img`));
  expect(poster).not.toBe(await original(`[data-testid="playlist-item-${entry(2).id}"] [data-testid="playlist-thumb"] img`));
});

for (const width of [390, 1366, 1920]) {
  test(`poster geometry at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(route(3));
    const box = await page.locator("#content").getByTestId("player-frame").boundingBox();
    if (!box) throw new Error("Poster geometry is required.");
    const expectedWidth = width === 390 ? 390 : Math.min(width - 476, 1444);
    expect(box.width).toBe(expectedWidth);
    expect(Math.abs(box.height - Math.round(expectedWidth * 9 / 16))).toBeLessThan(1);
    expect(box.y).toBe(width === 390 ? 56 : 96);
    if (width >= 1024) {
      const rail = await page.getByTestId("player-rail").boundingBox();
      const stage = await page.getByTestId("player-stage").boundingBox();
      if (!rail || !stage) throw new Error("Player rail geometry is required.");
      expect(rail.width).toBe(380);
      expect(Math.abs(rail.height - (stage.height - 8))).toBeLessThan(1);
      await expect(page.getByTestId("lecture-about")).toBeVisible();
    }
    else await expect(page.getByTestId("lecture-about")).toBeHidden();
  });
}

test("unapproved About is omitted and unknown lessons return not found", async ({ page }) => {
  const lesson = catalog.lessons.find((entry) => lessonAbout(entry) === null);
  const parent = catalog.courses.find((entry) => entry.id === lesson?.courseId);
  if (!lesson || !parent) throw new Error("A lesson without approved About is required.");
  await page.goto(`/c/${parent.slug}/${lesson.slug}`);
  await expect(page.getByTestId("lecture-about")).toHaveCount(0);
  await page.goto(`/c/${course.slug}/unknown-lesson`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
});

test("Player sign-in returns to the requested second paused", async ({ page }) => {
  await page.route("**/api/auth/sign-in/social", (route) => route.fulfill({ status: 503, json: {} }));
  await page.goto(`${route(3)}?t=3134`);
  const request = page.waitForRequest("**/api/auth/sign-in/social");
  await page.getByTestId("tower-topnav-sign-in").click();
  const returnTo = `${route(3)}?t=3134`;
  expect((await request).postDataJSON()).toMatchObject({ callbackURL: returnTo, newUserCallbackURL: returnTo, errorCallbackURL: returnTo });
  await expect(page.getByTestId("tower-signin-feedback")).toBeVisible();
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "idle");
  await startsAtZero(page);
});

test("AccountMenu overlays the actual Player and restores focus", async ({ page, context, baseURL }) => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString || !baseURL) throw new Error("Local auth test database and baseURL required.");
  validateDatabaseUrl(connectionString, "container");
  const pool = new pg.Pool({ connectionString });
  const session = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
  try {
    await page.goto(route(3));
    const avatar = page.getByTestId("tower-topnav-avatar");
    await avatar.click();
    const overlay = page.getByTestId("tower-account-overlay");
    await expect(overlay).toBeFocused();
    expect(await overlay.evaluate((element) => element.parentElement?.tagName)).toBe("BODY");
    await expect(page.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(avatar).toBeFocused();
    await expect(overlay).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`${route(3)}$`));
  } finally { await session.cleanup(); await pool.end(); }
});
