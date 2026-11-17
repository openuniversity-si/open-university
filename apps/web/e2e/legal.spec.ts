import { expect, test } from "./fixtures/no-video-guard.ts";

const PAGES = [
  { label: "Privacy", path: "/privacy", title: "Privacy" },
  { label: "Terms", path: "/terms", title: "Terms" },
  { label: "Contact", path: "/contact", title: "Contact" },
] as const;

for (const width of [390, 1440]) {
  for (const entry of PAGES) {
    test(`${entry.path} renders one h1 without horizontal scroll at ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const response = await page.goto(entry.path);
      expect(response?.status()).toBe(200);
      await expect(page).toHaveTitle(new RegExp(entry.title));
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(entry.title);
      expect(await page.getByRole("heading", { level: 2 }).count()).toBeGreaterThanOrEqual(1);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }

  test(`each footer link opens its page at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const entry of PAGES) {
      await page.goto("/");
      await page.getByTestId("tower-footer").getByRole("link", { name: entry.label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${entry.path}$`));
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(entry.title);
    }
  });

  test(`contact email links are mailto at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/contact");
    const card = page.getByTestId("tower-legal-email-card");
    await expect(card.getByRole("link", { name: "contact@openuniversity.si" })).toHaveAttribute("href", "mailto:contact@openuniversity.si");
    const cta = card.getByRole("link", { name: "Email us" });
    await expect(cta).toHaveAttribute("href", "mailto:contact@openuniversity.si");
    expect((await cta.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    await expect(cta.locator("svg")).toHaveCount(0);
  });
}

test("legal links open external pages in a new tab and email as mailto", async ({ page }) => {
  await page.goto("/privacy");
  const external = page.getByRole("link", { name: "https://policies.google.com/privacy" });
  await expect(external).toHaveAttribute("target", "_blank");
  await expect(external).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.getByRole("link", { name: "contact@openuniversity.si" }).first()).toHaveAttribute("href", "mailto:contact@openuniversity.si");
});
