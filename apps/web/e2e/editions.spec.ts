import { fakeCatalog as catalog, TEST_EDITIONS_COURSE } from "../src/catalog/testing/fake.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

// Course editions (ADR-21) on the test build's two-edition course: Spring 2025 (2 lectures + 1 lab) opens, Fall 2024 (2 lectures).
const path = `/c/${TEST_EDITIONS_COURSE.slug}`;
const genesis = catalog.courses[0];

test("a course with editions opens on the newest, switches without navigating and keeps the choice in ?edition=", async ({ page }) => {
  await page.goto(path);
  const tabs = page.getByRole("tablist", { name: "Edition" });
  await expect(tabs.getByRole("tab")).toHaveText(["Spring 2025", "Fall 2024"]);
  const spring = tabs.getByRole("tab", { name: "Spring 2025" });
  const fall = tabs.getByRole("tab", { name: "Fall 2024" });
  await expect(spring).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toHaveCount(1);
  const springList = page.locator("#edition-panel-spring-2025");
  await expect(springList.getByTestId("course-part-header")).toHaveText(["Lectures · 2", "Labs · 1"]);
  await expect(page.getByTestId("edition-summary")).toHaveText(/Spring 2025\s+·\s+2 lectures \+ 1 labs\s+·\s+1\.5 h/);

  const before = await page.evaluate(() => window.history.length);
  await fall.click();
  await expect(fall).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(`${path}?edition=fall-2024`);
  expect(await page.evaluate(() => window.history.length)).toBe(before);
  await expect(page.locator("#edition-panel-fall-2024").getByTestId("course-lecture-list").getByRole("link")).toHaveCount(2);
  await expect(springList).toBeHidden();
  await expect(page.getByTestId("edition-summary")).toHaveText(/Fall 2024\s+·\s+2 lectures/);

  // Keyboard: arrows move and select, focus follows.
  await fall.press("ArrowLeft");
  await expect(spring).toBeFocused();
  await expect(spring).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(path);

  // A shared link opens the named edition.
  await page.goto(`${path}?edition=fall-2024`);
  await expect(page.getByRole("tab", { name: "Fall 2024" })).toHaveAttribute("aria-selected", "true");
});

test("the Player stays inside the lesson's edition and names it", async ({ page }, testInfo) => {
  await page.goto(`${path}/edition-test-3`);
  await expect(page.getByTestId("player-lesson-header").locator("p").first()).toHaveText("Spring 2025 · Lab 3 of 3 · Two Editions");
  await expect(page.getByTestId("edition-badge")).toHaveText("Spring 2025");
  await expect(page.getByTestId("player-next")).toHaveCount(0);
  await expect(page.getByTestId("player-back-to-course")).toBeVisible();
  if (testInfo.project.name.includes("desktop")) await expect(page.getByTestId("player-lecture-list").getByRole("link")).toHaveCount(3);
  await page.goto(`${path}/edition-test-4`);
  await expect(page.getByTestId("player-previous")).toHaveCount(0);
  await expect(page.getByTestId("player-next")).toHaveAttribute("href", `${path}/edition-test-5`);
});

test("a course with one edition shows no selector, no edition kicker and no badge", async ({ page }) => {
  if (!genesis) throw new Error("The snapshot needs a course.");
  await page.goto(`/c/${genesis.slug}`);
  await expect(page.getByTestId("course-lectures")).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Edition" })).toHaveCount(0);
  await expect(page.getByTestId("course-part-header")).toHaveCount(0);
  const first = catalog.lessons.find((lesson) => lesson.courseId === genesis.id && lesson.order === 1);
  await page.goto(`/c/${genesis.slug}/${first?.slug ?? ""}`);
  await expect(page.getByTestId("edition-badge")).toHaveCount(0);
});
