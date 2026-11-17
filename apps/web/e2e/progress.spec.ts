import type { Locator, Page } from "@playwright/test";
import pg from "pg";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";
import { readLessonProgress, seedProgress } from "./fixtures/progress.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";

const genesis = catalog.courses.find((course) => course.id === "course-1");
if (!genesis) throw new Error("Fixture Course 1 is required.");
const lessons = lessonsForCourse(catalog, genesis.id);
const lesson = (index: number) => {
  const entry = lessons[index];
  if (!entry) throw new Error("Lesson is required.");
  return entry;
};
const route = (index: number) => `/c/${genesis.slug}/${lesson(index).slug}`;

interface FakeEngineHandle { readonly position: number; emit(event: string): void; time(seconds: number): void }
type FakeWindow = Window & { __towerFakePlayback?: FakeEngineHandle[] };
const emit = (page: Page, event: "playing" | "ended") => page.evaluate((event) => { (window as FakeWindow).__towerFakePlayback?.at(-1)?.emit(event); }, event);
const time = (page: Page, seconds: number) => page.evaluate((seconds) => { (window as FakeWindow).__towerFakePlayback?.at(-1)?.time(seconds); }, seconds);
/** Where the Player will start (the saved second or `?t=`): the engine's position before the first play. */
const startSecond = (page: Page) => page.evaluate(() => (window as FakeWindow).__towerFakePlayback?.at(-1)?.position ?? null);
const progressPost = (page: Page) => page.waitForResponse((response) => response.url().endsWith("/api/progress") && response.request().method() === "POST");
const isDesktop = (page: Page) => page.evaluate(() => innerWidth >= 1024);
/** Visible label only: the Billboard CTA carries both the mobile and the desktop wording. */
const visibleText = (locator: Locator) => locator.evaluate((element) => (element as HTMLElement).innerText.replace(/\s+/g, " ").trim());

async function play(page: Page) {
  await page.waitForFunction(() => ((window as FakeWindow).__towerFakePlayback?.length ?? 0) > 0);
  await page.getByRole("button", { name: "Play lecture" }).click();
  await emit(page, "playing");
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "playing");
}

let pool: pg.Pool;
test.beforeAll(() => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString) throw new Error("TEST_DATABASE_URL is required for progress e2e.");
  validateDatabaseUrl(connectionString, "container");
  pool = new pg.Pool({ connectionString });
});
test.afterAll(async () => { await pool.end(); });

async function signIn(context: Parameters<typeof injectSession>[0], baseURL: string | undefined) {
  if (!baseURL) throw new Error("baseURL is required.");
  return injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
}

test("Spec 06 fixture: Continue Watching, Resume, Current/Watched rows, 18% and the saved Player position", async ({ page, context, baseURL }) => {
  const viewer = await signIn(context, baseURL);
  try {
    await seedProgress(pool, viewer.userId);
    const desktop = await isDesktop(page);
    await page.goto("/");
    const rail = page.locator("#content").getByTestId("rail-continue-watching");
    await expect(rail.locator('[data-type="continue"]')).toHaveCount(3);
    await expect(rail.locator('[data-type="continue"]').first()).toHaveAttribute("data-testid", "course-card-course-2");
    const card = rail.getByTestId("course-card-course-1");
    await expect(card.getByTestId("tower-card-continue")).toHaveText(/Fixture Course 1\s*Lecture 4 of 17\s*1h 40m left/);
    await expect(card).toHaveAttribute("href", `${route(3)}?t=3134`);
    const bar = await card.getByTestId("tower-card-progress").evaluate((element) => element.firstElementChild ? element.firstElementChild.getBoundingClientRect().width / element.getBoundingClientRect().width : 0);
    expect(bar).toBeCloseTo(3134 / 9128, 2);
    await expect(rail.getByTestId("course-card-course-4")).toContainText("Episode 12 of 51");
    const cta = page.locator("#content").getByTestId("tower-billboard").getByTestId("tower-primary-cta");
    await expect.poll(() => visibleText(cta)).toBe(desktop ? "Resume · Lecture 4" : "Resume");
    await expect(cta).toHaveAttribute("href", `${route(3)}?t=3134`);
    // Decision 2: the Continue Watching card selects first, then resumes at the saved second.
    await card.click();
    await expect(card).toHaveAttribute("data-selected", "true");
    await card.click();
    await expect(page).toHaveURL(`${route(3)}?t=3134`);
    await expect.poll(() => startSecond(page)).toBe(3134);
    await expect(page.locator("#content").getByTestId("player-completion")).toHaveText("Mark complete");
    await expect(page.locator("#content").getByTestId("player-rail")).toContainText("3 of 17 watched");
    await expect(page.locator('#content [data-testid="player-rail"] [data-status="watched"]')).toHaveCount(3);

    await page.goto(`/c/${genesis.slug}`);
    await expect(page.locator("#content").getByTestId("course-lectures-header")).toContainText("Fixture Course 1 · 3 of 17 watched");
    await expect(page.locator("#content").getByTestId("course-progress-percent")).toHaveText("18%");
    const current = page.locator("#content").getByTestId(`playlist-item-${lesson(3).id}`);
    await expect(current).toHaveAttribute("data-status", "current");
    await expect(current).toContainText("Resume · 1h 40m left");
    await expect(page.locator('#content [data-testid="course-lecture-list"] [data-status="watched"]')).toHaveCount(3);
    await expect.poll(() => visibleText(page.locator("#content").getByTestId("tower-billboard").getByTestId("tower-primary-cta"))).toBe(desktop ? "Resume · Lecture 4" : "Resume");
  } finally { await viewer.cleanup(); }
});

// @engine: pagehide/keepalive delivery on unload is engine-specific (src/progress/client/client.ts).
test("checkpoint → reload → Resume within 15 s in another context", { tag: "@engine" }, async ({ page, context, browser, baseURL }) => {
  const viewer = await signIn(context, baseURL);
  try {
    await page.goto(route(1));
    await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
    await play(page);
    const saved = progressPost(page);
    await time(page, 600);
    expect((await saved).status()).toBe(204);
    await time(page, 607);
    await page.reload();
    await expect.poll(() => startSecond(page)).toBeGreaterThanOrEqual(600);
    expect(await startSecond(page)).toBeLessThanOrEqual(609);
    const other = await browser.newContext();
    try {
      await other.addCookies([viewer.cookie]);
      const second = await other.newPage();
      await second.goto(`/c/${genesis.slug}`);
      const href = await second.locator("#content").getByTestId("tower-billboard").getByTestId("tower-primary-cta").getAttribute("href");
      const resumed = Number(new URL(href ?? "", baseURL).searchParams.get("t"));
      expect(Math.abs(resumed - 607)).toBeLessThanOrEqual(15);
      await second.goto(href ?? "");
      await expect.poll(() => startSecond(second)).toBeGreaterThanOrEqual(600);
      expect(await startSecond(second)).toBeLessThanOrEqual(609);
    } finally { await other.close(); }
  } finally { await viewer.cleanup(); }
});

// @engine: pagehide and beforeunload delivery when closing a background tab varies by engine.
test("two tabs don't regress: an idle tab writes nothing and a stale tab keeps the completion", { tag: "@engine" }, async ({ page, context, baseURL }) => {
  const viewer = await signIn(context, baseURL);
  try {
    const idle = await context.newPage();
    await idle.goto(route(2));
    await page.goto(route(2));
    await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
    await play(page);
    const saved = progressPost(page);
    await time(page, 900);
    expect((await saved).status()).toBe(204);
    const writes: string[] = [];
    idle.on("request", (request) => { if (request.url().endsWith("/api/progress")) writes.push(request.method()); });
    await idle.evaluate(() => { dispatchEvent(new Event("pagehide")); });
    await idle.close({ runBeforeUnload: true });
    expect(writes).toEqual([]);
    await expect.poll(() => readLessonProgress(pool, viewer.userId, lesson(2).id)).toMatchObject({ position_seconds: 900 });

    const stale = await context.newPage();
    await stale.goto(route(2));
    await expect(stale.getByTestId("tower-topnav-avatar")).toBeVisible();
    const completed = progressPost(page);
    await emit(page, "ended");
    expect((await completed).status()).toBe(204);
    await pool.query("UPDATE lesson_progress SET updated_at = updated_at - interval '6 seconds' WHERE user_id = $1", [viewer.userId]);
    await play(stale);
    const checkpoint = progressPost(stale);
    await time(stale, 950);
    expect((await checkpoint).status()).toBe(204);
    await expect.poll(() => readLessonProgress(pool, viewer.userId, lesson(2).id)).toMatchObject({ completed: true, position_seconds: 950 });
    await stale.reload();
    await expect(stale.locator("#content").getByTestId("player-completion")).toHaveText("Completed");
  } finally { await viewer.cleanup(); }
});

test("CompletionToggle is optimistic, reverts on error and persists", async ({ page, context, baseURL }) => {
  const viewer = await signIn(context, baseURL);
  try {
    await page.goto(route(5));
    await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
    const toggle = page.locator("#content").getByTestId("player-completion");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/progress", async (request) => { await held; await request.fulfill({ status: 500, body: "{}" }); }, { times: 1 });
    await toggle.click();
    await expect(toggle).toHaveText("Completed");
    release();
    await expect(toggle).toHaveText("Mark complete");
    const saved = progressPost(page);
    await toggle.click();
    expect((await saved).status()).toBe(204);
    await page.reload();
    await expect(page.locator("#content").getByTestId("player-completion")).toHaveText("Completed");
    await expect(page.locator(`#content [data-testid="playlist-item-${lesson(5).id}"]`)).toHaveAttribute("data-now-playing", "true");
    await expect.poll(() => readLessonProgress(pool, viewer.userId, lesson(5).id)).toMatchObject({ completed: true });
  } finally { await viewer.cleanup(); }
});

test("signed out sends nothing; Decision 4 persists the pending completion after sign-in", async ({ page, context, baseURL, request }) => {
  expect((await request.post("/api/progress", { headers: { origin: baseURL ?? "" }, data: { courseSlug: genesis.slug, lessonSlug: lesson(6).slug, positionSeconds: 5 } })).status()).toBe(401);
  const writes: string[] = [];
  page.on("request", (entry) => { if (entry.url().endsWith("/api/progress")) writes.push(entry.method()); });
  await page.goto(route(6));
  await expect(page.getByTestId("tower-topnav-sign-in")).toBeVisible();
  await play(page);
  await time(page, 600);
  await emit(page, "ended");
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("open-university:pending-completion:v1"))).toContain(lesson(6).slug);
  expect(writes).toEqual([]);

  const viewer = await signIn(context, baseURL);
  try {
    const persisted = progressPost(page);
    await page.reload();
    expect((await persisted).status()).toBe(204);
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("open-university:pending-completion:v1"))).toBeNull();
    await expect.poll(() => readLessonProgress(pool, viewer.userId, lesson(6).id)).toMatchObject({ completed: true });
  } finally { await viewer.cleanup(); }
});
