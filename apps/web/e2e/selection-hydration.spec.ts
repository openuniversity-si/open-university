import { expect, test } from "./fixtures/no-video-guard.ts";

/** Cold/slow clients must exercise the real handler, never mistake streamed markup for a hydrated control. */
// @engine: native keyboard activation and focus retention exercise each engine after streamed hydration.
test("Enter selects a lesson after delayed hydration and a second Enter opens it @a11y", { tag: "@engine" }, async ({ page }) => {
  let release = () => {};
  const scriptsReady = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/_next/static/**/*.js", async (route) => { await scriptsReady; await route.continue(); });
  try {
    await page.goto("/c/fixture-course-1", { waitUntil: "commit" });
    const playlist = page.getByTestId("course-lectures");
    await expect(playlist).toBeVisible();
    await expect(playlist).toHaveAttribute("data-hydrated", "false");
    release();
    await expect(playlist).toHaveAttribute("data-hydrated", "true");
    const row = page.getByTestId("playlist-item-lesson-1");
    await row.focus();
    await page.keyboard.press("Enter");
    await expect(row).toHaveAttribute("data-selected", "true");
    await expect(row).toBeFocused();
    await expect(page).toHaveURL(/\/c\/fixture-course-1$/);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/fixture-lesson-1$/);
  } finally { release(); }
});
