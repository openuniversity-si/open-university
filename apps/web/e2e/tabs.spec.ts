import { expect, test } from "./fixtures/no-video-guard.ts";

// Home tabs (docs/catalog/tabs.md): Home · Universities · Authors in the TopNav, active tab = aria-current.
for (const width of [390, 1440]) {
  test(`primary tabs at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    for (const [path, id] of [["/", "home"], ["/universities", "universities"], ["/authors", "authors"]] as const) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      const nav = page.getByTestId("tower-topnav").getByRole("navigation", { name: "Primary" });
      await expect(nav.getByRole("link")).toHaveText(["Home", "Universities", "Authors"]);
      await expect(page.getByTestId(`tower-topnav-${id}`)).toHaveAttribute("aria-current", "page");
      await expect(nav.locator("[aria-current=page]")).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
    await page.getByTestId("tower-topnav-authors").click();
    await expect(page).toHaveURL(/\/authors$/);
  });
}

test("the tabs are hidden on a mobile Course page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/c/fixture-course");
  await expect(page.getByTestId("tower-topnav-universities")).toBeHidden();
});
