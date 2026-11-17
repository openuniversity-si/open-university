import type { Page } from "@playwright/test";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
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

/** The test build's FakeEngine registry (src/playback/testing/fake-engine.ts); oldest engine first. */
interface FakeEngineHandle { state: string; starts: number[]; seeks: number[]; emit(event: string, attempt?: number): void; time(seconds: number, attempt?: number): void }
type FakeWindow = Window & { __towerFakePlayback?: FakeEngineHandle[] };

async function opened(page: Page, count = 1): Promise<void> {
  await page.waitForFunction((count) => ((window as FakeWindow).__towerFakePlayback?.length ?? 0) >= count, count);
}
async function emit(page: Page, event: "playing" | "paused" | "ended" | "error", engine = -1, attempt?: number): Promise<void> {
  await page.evaluate(({ event, engine, attempt }) => { (window as FakeWindow).__towerFakePlayback?.at(engine)?.emit(event, attempt); }, { event, engine, attempt });
}
async function engine(page: Page, index = -1) {
  return page.evaluate((index) => {
    const fake = (window as FakeWindow).__towerFakePlayback?.at(index);
    return fake ? { state: fake.state, starts: [...fake.starts], seeks: [...fake.seeks] } : null;
  }, index);
}

/** Controls the Player drew before YouTube's native controls took over (ADR-11); none may come back. */
const RETIRED = ["player-scrubber", "player-back", "player-forward", "player-speed", "player-fullscreen", "player-time", "player-tap", "player-announce"];
async function onlyNativeControls(page: Page): Promise<void> {
  for (const testId of RETIRED) await expect(page.getByTestId(testId), testId).toHaveCount(0);
  await expect(page.locator("#content").getByTestId("player-frame").getByRole("slider")).toHaveCount(0);
  await expect(page.locator("#content").getByTestId("player-frame").getByRole("button", { name: /^(Pause|Play|Full screen|Exit full screen|Back 10 seconds|Forward 10 seconds|Playback speed.*)$/ })).toHaveCount(0);
}

test("poster + glass play until the video plays, then the embed (with YouTube's controls) is the picture, also at the end", async ({ page }) => {
  await page.goto(route(3));
  await opened(page);
  const frame = page.locator("#content").getByTestId("player-frame");
  await expect(frame).toHaveAttribute("data-state", "idle");
  // Idle: the opaque poster is the picture; the iframe host stays hidden and there is no YouTube chip.
  await expect(page.getByTestId("player-poster")).toBeVisible();
  await expect(page.getByTestId("player-media")).toBeHidden();
  await expect(page.getByTestId("player-youtube")).toHaveCount(0);
  await expect(page.getByTestId("player-play")).toBeVisible();
  await onlyNativeControls(page);
  await page.getByRole("button", { name: "Play lecture" }).click();
  await expect(frame).toHaveAttribute("data-state", "loading");
  await expect(page.getByTestId("player-loading")).toBeVisible();
  await expect(page.getByTestId("player-play")).toHaveCount(0);
  await expect(page.getByTestId("player-poster")).toBeVisible();
  await expect(page.getByTestId("player-media")).toBeHidden();
  await emit(page, "playing");
  await expect(frame).toHaveAttribute("data-state", "playing");
  await expect(page.getByTestId("player-media")).toBeVisible();
  await expect(page.getByTestId("player-poster")).toBeHidden();
  await expect(frame.getByRole("button")).toHaveCount(0);
  await onlyNativeControls(page);
  await emit(page, "ended");
  await expect(frame).toHaveAttribute("data-state", "ended");
  await expect(page.getByTestId("player-media")).toBeVisible();
  await expect(page.getByTestId("player-poster")).toBeHidden();
  await expect(frame.getByRole("button")).toHaveCount(0);
  expect(await engine(page)).toMatchObject({ state: "ended", starts: [1] });
});

test("a play that doesn't start is handed to YouTube's controls: the poster lifts and nothing of ours stays on top", async ({ page }) => {
  await page.goto(route(3));
  await opened(page);
  const frame = page.locator("#content").getByTestId("player-frame");
  await page.getByRole("button", { name: "Play lecture" }).click();
  await expect(frame).toHaveAttribute("data-state", "loading");
  // The transport's handoff (HANDOFF_MS, youtube-engine.ts) reports the unstarted play as paused.
  await emit(page, "paused");
  await expect(frame).toHaveAttribute("data-state", "paused");
  await expect(frame).toHaveAttribute("data-started", "true");
  await expect(page.getByTestId("player-media")).toBeVisible();
  await expect(page.getByTestId("player-poster")).toBeHidden();
  await expect(frame.getByRole("button")).toHaveCount(0);
});

test("no play without a gesture", async ({ page }) => {
  await page.goto(route(3));
  await opened(page);
  await page.evaluate(() => {
    const button = document.querySelector<HTMLButtonElement>('[data-testid="player-play"]');
    button?.click(); button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  // Our page shortcuts are gone (YouTube's own work inside the embed): K, L and F do nothing here.
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  for (const key of ["k", "l", "f"]) await page.keyboard.press(key);
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "idle");
  expect(await engine(page)).toMatchObject({ state: "idle", starts: [], seeks: [] });
  await expect(page.locator("video, mux-video, media-controller")).toHaveCount(0);
});

test("error → Try again rebuilds the player, then loads again", async ({ page }) => {
  await page.goto(route(3));
  await opened(page);
  await page.getByRole("button", { name: "Play lecture" }).click();
  await emit(page, "error");
  const error = page.getByTestId("player-error");
  await expect(error).toContainText("This lecture can’t play right now.");
  await expect(page.getByTestId("player-poster")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "loading");
  expect(await engine(page)).toMatchObject({ state: "loading", starts: [1, 3] });
  await emit(page, "playing");
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "playing");
});

test("lesson change drops late events from the previous lesson", async ({ page }) => {
  await page.goto(route(3));
  await opened(page);
  await page.getByRole("button", { name: "Play lecture" }).click();
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "loading");
  await page.getByTestId("player-next").click();
  await expect(page).toHaveURL(new RegExp(`${route(4)}$`));
  await opened(page, 2);
  await emit(page, "playing", 0, 1);
  await emit(page, "ended", 0, 1);
  await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "idle");
  expect(await engine(page, 0)).toMatchObject({ state: "loading" });
  expect(await engine(page)).toMatchObject({ state: "idle", starts: [] });
});

test("layout: the glass play sits in the centre of the poster; once started nothing of ours covers the embed", async ({ page, isMobile }) => {
  test.skip(isMobile, "Both viewports are measured in desktop Chromium.");
  for (const [width, height] of [[390, 844], [1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(route(3));
    await opened(page);
    const box = async (testId: string) => {
      const found = await page.getByTestId(testId).boundingBox();
      if (!found) throw new Error(`${testId} has no box at ${String(width)}.`);
      return found;
    };
    const centreY = (found: { y: number; height: number }) => found.y + found.height / 2;
    const frame = await box("player-frame");
    const play = await box("player-play");
    expect(Math.abs(play.x + play.width / 2 - (frame.x + frame.width / 2)), `play x at ${String(width)}`).toBeLessThan(1);
    expect(Math.abs(centreY(play) - centreY(frame)), `play y at ${String(width)}`).toBeLessThan(1);
    await onlyNativeControls(page);
    await page.getByRole("button", { name: "Play lecture" }).click();
    await emit(page, "playing");
    await expect(page.locator("#content").getByTestId("player-frame")).toHaveAttribute("data-state", "playing");
    for (const [x, y] of [[0.5, 0.5], [0.12, 0.5], [0.88, 0.5], [0.5, 0.95], [0.97, 0.95]] as const) {
      expect(await page.locator("#content").getByTestId("player-frame").evaluate((element, { x, y }) => {
        const box = element.getBoundingClientRect();
        return element.ownerDocument.elementFromPoint(box.x + box.width * x, box.y + box.height * y)?.closest("[data-testid]")?.getAttribute("data-testid");
      }, { x, y }), `${String(x)},${String(y)} at ${String(width)}`).toBe("player-media");
    }
  }
});
