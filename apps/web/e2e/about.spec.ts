import { expect, test } from "./fixtures/no-video-guard.ts";

const SIZES = { 390: { lead: "26px", body: "18px", wink: "20px" }, 1440: { lead: "40px", body: "22px", wink: "26px" } } as const;

for (const width of [390, 1440] as const) {
  test(`/about renders one h1, no h2, the approved type sizes and Enter at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const response = await page.goto("/about");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(/^About · Open University$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Open University");
    await expect(page.getByRole("heading", { level: 2 })).toHaveCount(0);
    const article = page.getByTestId("tower-legal-page");
    await expect(article).not.toContainText("Last updated");
    const lead = article.getByText(/^The lectures worth remembering\./);
    await expect(lead).toContainText("The world's great universities, in one big, beautiful library.");
    await expect(lead).toHaveCSS("font-size", SIZES[width].lead);
    await expect(article.getByText(/^Universities publish extraordinary teaching/)).toHaveCSS("font-size", SIZES[width].body);
    await expect(article.getByText(/^It is made as a companion to formal study/)).toBeVisible();
    await expect(article.getByText(/^No short videos, no ads, no infinite scroll\./)).toBeVisible();
    const wink = article.getByText("One library to rule them all.", { exact: true });
    await expect(wink).toHaveCSS("font-size", SIZES[width].wink);
    const commitment = article.getByText(/^Open University is the free initiative of The Tower\. Our commitment: it is free, permanently\./);
    await expect(commitment).toBeVisible();
    const [winkBox, commitmentBox, quietRoomBox] = await Promise.all([wink.boundingBox(), commitment.boundingBox(), article.getByText(/^No short videos/).boundingBox()]);
    expect(quietRoomBox && winkBox && commitmentBox ? quietRoomBox.y < winkBox.y && winkBox.y < commitmentBox.y : false).toBe(true);
    await expect(article).not.toContainText(/open[- ]source|great again/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    const enter = article.getByRole("link", { name: "Enter" });
    await expect(enter.locator("svg")).toHaveCount(0);
    await enter.click();
    await expect(page).toHaveURL(/\/$/);
  });

  test(`home intro sits below the hero and before the first rail, and links to /about at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const intro = page.getByTestId("tower-home-intro");
    await expect(intro).toContainText("Great lectures, in order. Universal, Free & Luxurious.");
    const hero = await page.getByTestId("tower-billboard").boundingBox();
    const introBox = await intro.boundingBox();
    const rail = await page.locator("#content h2").first().boundingBox();
    expect(hero && introBox ? introBox.y >= hero.y + hero.height - 1 : false).toBe(true);
    expect(introBox && rail ? introBox.y + introBox.height <= rail.y : false).toBe(true);
    const link = intro.getByRole("link", { name: "About Open University ›" });
    expect((await link.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await link.click();
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Open University");
  });
}
