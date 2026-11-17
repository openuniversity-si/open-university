import { expect, test } from "./fixtures/no-video-guard.ts";

for (const kind of ["error", "cancelled"]) {
  test(`presentational sign-in ${kind} offers a 44 px retry target`, async ({ page }) => {
    await page.goto(`/fixtures/account?kind=${kind}`);
    const feedback = page.getByTestId("tower-signin-feedback");
    await expect(feedback).toBeVisible({ timeout: 15_000 });
    await expect(feedback).toContainText(kind === "error" ? "Couldn’t sign in." : "Sign-in cancelled.");
    await expect(feedback).toHaveCSS("border-radius", "18px");
    const retry = feedback.getByRole("button", { name: "Try again" });
    expect((await retry.boundingBox())?.height).toBe(44);
    await retry.click();
    await expect(page.getByTestId("account-fixture-action")).toHaveText("Try again");
    await expect(page).toHaveURL(new RegExp(`kind=${kind}$`));
  });
}

// @engine: WebKit does not focus buttons on click, so focus restoration differs.
test("account overlay closes outside and with Escape, restores focus and exposes Sign out", { tag: "@engine" }, async ({ page }) => {
  await page.goto("/fixtures/account?kind=menu");
  const panel = page.getByTestId("tower-account-menu");
  await expect(panel).toContainText("Daniel Bello");
  await expect(panel).toHaveCSS("border-radius", "14px");
  const box = await panel.boundingBox();
  expect(box?.width).toBe(99);
  expect(box?.height).toBe(84);
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  const open = page.getByTestId("account-fixture-open");
  await open.click();
  await expect(page.getByTestId("tower-account-overlay")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(panel.getByRole("menuitem")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  await open.click();
  await page.getByRole("button", { name: "Close account menu" }).click({ position: { x: 10, y: 300 } });
  await expect(panel).toHaveCount(0);
  await open.click();
  await panel.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("account-fixture-action")).toHaveText("Sign out");
});

test("account overlay escapes a transformed Player ancestor", async ({ page }) => {
  await page.goto("/fixtures/account?kind=menu");
  const result = await page.getByTestId("tower-account-overlay").evaluate((overlay) => {
    const main = document.querySelector("main");
    if (main) { main.style.transform = "translateZ(0)"; main.style.position = "relative"; main.style.zIndex = "50"; }
    return { parent: overlay.parentElement?.tagName, zIndex: getComputedStyle(overlay).zIndex };
  });
  expect(result).toEqual({ parent: "BODY", zIndex: "60" });
  await expect(page.getByTestId("tower-account-menu").getByRole("menuitem")).toBeVisible();
});

test("Clear CTA keeps its pill and keyboard focus; disabled CTA cannot navigate", async ({ page }) => {
  await page.goto("/");
  const cta = page.getByTestId("tower-primary-cta");
  const desktop = await page.evaluate(() => innerWidth >= 768);
  await expect(cta).toHaveCSS("height", desktop ? "48px" : "44px");
  await expect(cta).toHaveCSS("border-radius", desktop ? "24px" : "22px");
  await cta.focus();
  await expect(cta).toBeFocused();
  await expect(cta).toHaveCSS("box-shadow", /3px/);
  await page.goto("/fixtures/states");
  const disabled = page.locator('[data-testid="tower-primary-cta"][aria-disabled="true"]');
  await expect(disabled).toHaveAttribute("aria-disabled", "true");
  await expect(disabled).toHaveCSS("pointer-events", "none");
});
