import { expect, test } from "./fixtures/no-video-guard.ts";

// Chrome on Android flashed its default blue tap highlight (rgba(51, 181, 229, 0.4)) over every tapped card and control.
// @engine: tap highlight and touch selection exist only in touch engines (-webkit-tap-highlight-color).
test("touch surfaces use the theme, not the browser's blue tap highlight or selection", { tag: "@engine" }, async ({ page }) => {
  await page.goto("/authors");
  const card = page.locator('[data-testid^="course-card-"]').first();
  for (const target of [page.locator("html"), card, page.getByTestId("tower-topnav-sign-in")]) {
    await expect(target).toHaveCSS("-webkit-tap-highlight-color", "rgba(0, 0, 0, 0)");
  }
  await expect(card).toHaveCSS("user-select", "none");
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveCSS("user-select", "none");
  await expect(page.locator("html")).toHaveCSS("color-scheme", "dark");
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#0c0c0d");
  const selection = await page.evaluate(() => getComputedStyle(document.body, "::selection").backgroundColor);
  expect(selection).toBe("rgba(217, 219, 223, 0.4)");
});
