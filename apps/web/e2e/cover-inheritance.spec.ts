import { test, expect } from "./fixtures/no-video-guard.ts";
import { TEST_EDITIONS_COURSE } from "../src/catalog/testing/fake.ts";

test("a course with no lesson cover rows renders its inherited cover in the course rail and player", async ({ page }) => {
  const path = `/c/${TEST_EDITIONS_COURSE.slug}`;
  await page.goto(path);
  const thumbnails = page.getByTestId("course-lecture-list").getByRole("img", { name: "Shared lecture fixture" });
  await expect(thumbnails).toHaveCount(3);
  await expect(thumbnails.first()).toHaveAttribute("src", /brand%2Fog\.jpg|brand\/og\.jpg/);
  await expect.poll(() => thumbnails.first().evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await page.goto(`${path}/edition-test-1`);
  const inherited = page.getByRole("img", { name: "Shared lecture fixture" });
  await expect(inherited.first()).toBeVisible();
  await expect(inherited.first()).toHaveAttribute("src", /brand%2Fog\.jpg|brand\/og\.jpg/);
});
