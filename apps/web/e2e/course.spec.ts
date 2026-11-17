import { test, expect } from "./fixtures/no-video-guard";
import { snapshotCatalog } from "../src/catalog/testing/fake.ts";

const { courses, lessons } = snapshotCatalog;

for (const course of courses) {
  test(`course ${course.slug} uses catalog URLs, copy, labels and first lesson`, async ({ page }) => {
    await page.goto(`/c/${course.slug}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(course.displayTitle);
    const entries = lessons.filter((lesson) => lesson.courseId === course.id).sort((a, b) => a.order - b.order);
    if (!entries[0]) throw new Error("Course requires a first lesson.");
    const rows = page.locator('[data-testid^="playlist-item-"]');
    await expect(rows).toHaveCount(entries.length);
    await expect(rows.locator("img")).toHaveCount(entries.length);
    await expect(page.getByRole("link", { name: "Start", exact: true })).toHaveAttribute("href", `/c/${course.slug}/${entries[0].slug}`);
    for (const lesson of entries) {
      const label = lesson.kind === "background" ? "Background" : lesson.kind === "trailer" ? "Trailer" : course.lessonNoun;
      await expect(page.getByTestId(`playlist-item-${lesson.id}`)).toHaveAttribute("aria-label", new RegExp(`^${label}:`));
    }
    await expect(page.getByTestId("tower-topnav-back")).toHaveAttribute("href", "/");
    await expect(page.getByTestId("tower-bottom-fade")).toHaveCount(0);
    await expect(page.getByTestId("tower-footer")).toHaveCSS("opacity", "1");
    await expect(page.getByText(/watched|Now playing|Current/)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("lesson selection is exclusive; second activation navigates, with keyboard parity", async ({ page }) => {
  const course = courses[0];
  if (!course) throw new Error("Fixture Course 1 is required.");
  const entries = lessons.filter((lesson) => lesson.courseId === course.id).sort((a, b) => a.order - b.order);
  if (!entries[0] || !entries[1]) throw new Error("Two lessons required.");
  await page.goto(`/c/${course.slug}`);
  const first = page.getByTestId(`playlist-item-${entries[0].id}`);
  const second = page.getByTestId(`playlist-item-${entries[1].id}`);
  await first.click();
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}$`));
  await expect(first).toHaveAttribute("data-selected", "true");
  await expect(first).toHaveAttribute("aria-description", /Selected/);
  await expect(first).not.toHaveAttribute("aria-current");
  await second.focus();
  await page.keyboard.press("Space");
  await expect(first).toHaveAttribute("data-selected", "false");
  await expect(second).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/c/${course.slug}/${entries[1].slug}$`));
});

for (const width of [390, 768, 1024, 1366, 1920]) {
  for (const courseIndex of [0, 3]) {
    test(`${String(width)}px course with ${String(courseIndex === 0 ? 17 : 51)} lessons contains long titles and reaches its last row`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const course = courses[courseIndex];
      if (!course) throw new Error("Course is required.");
      await page.goto(`/c/${course.slug}`);
      const list = page.getByTestId("course-lecture-list");
      const rows = list.locator('[data-testid^="playlist-item-"]');
      // Measure after the panel is laid out (a boundingBox() before hydration returned null intermittently).
      await expect(page.getByTestId("course-lectures")).toBeVisible();
      await expect(rows.first()).toBeVisible();
      const panel = await page.getByTestId("course-lectures").boundingBox();
      if (width >= 1024) {
        expect(panel?.width).toBe(width - 160 - 64 - 380);
        // 660 px of rows plus 4 px above them for the focus ring (F12); the rows do not move.
        await expect(list).toHaveCSS("height", "664px");
        await expect(list).toHaveCSS("overflow-y", "auto");
        await expect(page.getByTestId("course-about")).toBeVisible();
      } else {
        await expect(list).toHaveCSS("overflow-y", "visible");
        await expect(page.getByTestId("course-about")).toBeHidden();
      }
      const last = rows.last();
      await last.scrollIntoViewIfNeeded();
      await expect(last).toBeInViewport();
      await last.click();
      await expect(last).toHaveAttribute("data-selected", "true");
      const contained = await rows.evaluateAll((elements) => elements.every((element) => element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight));
      expect(contained).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByTestId("tower-footer").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("tower-footer")).toBeInViewport();
    });
  }
}

test("unknown course returns the not-found screen", async ({ page }) => {
  await page.goto("/c/unknown-course");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
});
