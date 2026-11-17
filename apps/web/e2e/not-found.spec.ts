import { expect, test } from "./fixtures/no-video-guard.ts";

/** ◆ 404 — Mobile 390 | Desktop 1920: one column centred between the fixed TopNav and the Footer (ADR-14). */
for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  // @engine: centred with dvh units (not-found.module.css), whose value differs in mobile engines.
  test(`404 is centred between header and footer at ${String(viewport.width)}×${String(viewport.height)}`, { tag: "@engine" }, async ({ page }) => {
    await page.setViewportSize(viewport);
    const response = await page.goto("/zzz");
    expect(response?.status()).toBe(404);
    await expect(page).toHaveTitle("Page not found · Open University");
    await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute("content", /noindex/);
    await expect(page.locator('link[rel="canonical"]')).toHaveCount(0);
    const heading = page.getByRole("heading", { level: 1, name: "Page not found" });
    await expect(heading).toBeVisible();
    await expect(page.getByText("404", { exact: true })).toBeVisible();
    await expect(page.getByText("This page does not exist, or it has moved. The courses are right where you left them.")).toBeVisible();
    const box = async (testId: string) => {
      const rect = await page.getByTestId(testId).boundingBox();
      if (!rect) throw new Error(`${testId} is not rendered.`);
      return rect;
    };
    const h1 = await heading.boundingBox();
    if (!h1) throw new Error("h1 is not rendered.");
    expect(Math.abs(h1.x + h1.width / 2 - viewport.width / 2)).toBeLessThanOrEqual(2);
    const header = await box("tower-topnav");
    const footer = await box("tower-footer");
    const column = await box("tower-not-found-column");
    const areaCentre = (header.y + header.height + footer.y) / 2;
    expect(Math.abs(column.y + column.height / 2 - areaCentre)).toBeLessThanOrEqual(24);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    const cta = page.getByTestId("tower-not-found").getByTestId("tower-primary-cta");
    await expect(cta).toHaveText("Home");
    await expect(cta.locator("svg")).toHaveCount(0);
    await cta.click();
    await expect(page).toHaveURL(/\/$/);
  });
}
