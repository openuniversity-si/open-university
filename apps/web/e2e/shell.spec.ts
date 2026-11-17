import { expect, test } from "./fixtures/no-video-guard.ts";

for (const width of [390, 1366, 1920]) {
  // @engine: fixed-header geometry and footer hit rectangles also run with each mobile meta-viewport.
  test(`shell geometry, glass header and bottom fade at ${String(width)} px`, { tag: "@engine" }, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/fixtures/shell");
    await page.evaluate(() => document.fonts.ready);
    const desktop = width >= 1024;
    const header = page.getByTestId("tower-topnav");
    await expect(header).toHaveCSS("height", desktop ? "72px" : "56px");
    await expect(header).toHaveCSS("position", "fixed");
    await expect(header).toHaveCSS("background-image", "none");
    await expect(page.getByTestId("tower-header-glass")).toHaveCSS("height", width >= 768 ? "52px" : "44px");
    await expect(page.getByTestId("tower-header-glass")).toHaveCSS("pointer-events", "none");
    const footer = page.getByTestId("tower-footer");
    await expect(footer).toHaveCSS("height", "44px");
    await expect(footer).toHaveCSS("margin-top", "40px");
    await expect(footer).toHaveCSS("margin-bottom", desktop ? "12px" : "8px");
    await expect(page.getByTestId("tower-bottom-fade")).toHaveCSS("height", desktop ? "80px" : "64px");
    await expect(page.getByTestId("tower-bottom-fade")).toHaveCSS("pointer-events", "none");
    await expect(header.getByRole("link", { name: /Privacy|Terms|Contact/ })).toHaveCount(0);
    await expect(header.getByTestId("tower-topnav-back")).toHaveCount(0);
    await page.evaluate(() => { window.scrollTo(0, document.documentElement.scrollHeight); });
    expect((await header.boundingBox())?.y).toBe(0);
    await expect(footer.getByRole("link")).toHaveText(["Privacy", "Terms", "Contact", "Credits"]);
    for (const link of await footer.getByRole("link").all()) {
      const box = await link.boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(44);
      expect(box?.height).toBeGreaterThanOrEqual(44);
    }
  });
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`footer scroll fade with ${reducedMotion}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion });
    await page.goto("/fixtures/shell");
    const footer = page.getByTestId("tower-footer");
    for (const distance of [80, 60, 40, 20, 0]) {
      await page.evaluate((remaining) => { window.scrollTo(0, document.documentElement.scrollHeight - window.innerHeight - remaining); }, distance);
      const t = 1 - distance / 80;
      const opacity = reducedMotion === "reduce" ? 1 : t * t * (3 - 2 * t);
      await expect.poll(() => footer.evaluate((element) => Number(getComputedStyle(element).opacity))).toBeCloseTo(opacity, 3);
    }
    await page.emulateMedia({ reducedMotion: reducedMotion === "reduce" ? "no-preference" : "reduce" });
    await page.evaluate(() => { window.scrollTo(0, 0); });
    await expect(footer).toHaveCSS("opacity", reducedMotion === "reduce" ? "0" : "1");
  });
}

test("the footer is the mark, the three legal links and Credits only: no slogan (removed in the 2026-10-11 rebrand)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/fixtures/shell");
  const footer = page.getByTestId("tower-footer");
  await expect(page.getByTestId("tower-footer-mega")).toHaveCount(0);
  await expect(footer).not.toContainText(/great again/i);
  await expect(footer.getByRole("link")).toHaveText(["Privacy", "Terms", "Contact", "Credits"]);
});

test("D7 skip link appears on keyboard focus and focuses content", async ({ page }) => {
  await page.goto("/fixtures/states");
  const skip = page.getByTestId("tower-skip-link");
  await expect(skip).toHaveCSS("clip-path", "inset(50%)");
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await expect(skip).toHaveCSS("clip-path", "none");
  await page.keyboard.press("Enter");
  await expect(page.locator("main#content")).toBeFocused();
  await expect(skip).toHaveCSS("clip-path", "inset(50%)");
});

test("D10 deep links navigate to their parent without browser history", async ({ page }) => {
  await page.goto("/c/fixture-course/fixture-lecture");
  await expect(page.getByTestId("tower-topnav-back")).toHaveAttribute("href", "/c/fixture-course");
  await page.getByTestId("tower-topnav-back").click();
  await expect(page).toHaveURL(/\/c\/fixture-course$/);
  await expect(page.getByTestId("tower-topnav-back")).toHaveAttribute("href", "/");
  await page.getByTestId("tower-topnav-back").click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("tower-topnav-back")).toHaveCount(0);
});

test("header hit rectangles are at least 44 px and never overlap", async ({ page }) => {
  for (const width of [390, 1366, 1920]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/c/fixture-course/fixture-lecture");
    const hits = await page.getByTestId("tower-topnav").getByRole("link").evaluateAll((links) => links.flatMap((link) => {
      const box = link.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) return [];
      const pseudo = getComputedStyle(link, "::after");
      if (pseudo.content === "none") return [{ x: box.x, y: box.y, width: box.width, height: box.height }];
      const matrix = new DOMMatrix(pseudo.transform);
      return [{ x: box.x + parseFloat(pseudo.left) + matrix.e, y: box.y + parseFloat(pseudo.top) + matrix.f, width: parseFloat(pseudo.width), height: parseFloat(pseudo.height) }];
    }));
    for (const hit of hits) {
      expect(hit.width).toBeGreaterThanOrEqual(44);
      expect(hit.height).toBeGreaterThanOrEqual(44);
    }
    for (const [index, hit] of hits.entries()) {
      for (const other of hits.slice(index + 1)) {
        const overlapX = Math.min(hit.x + hit.width, other.x + other.width) - Math.max(hit.x, other.x);
        const overlapY = Math.min(hit.y + hit.height, other.y + other.height) - Math.max(hit.y, other.y);
        expect(overlapX <= 0 || overlapY <= 0).toBe(true);
      }
    }
  }
});

for (const { path, title, status } of [
  { path: "/missing-shell-page", title: "Page not found", status: 404 },
  // No loading boundary streams before the render failure outside /c (ADR-16), so the status is a real 500.
  { path: "/fixtures/error", title: "Something went wrong", status: 500 },
]) {
  test(`D6 ${String(status)} has its h1 and the Home CTA`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(status);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await expect(page.getByTestId("tower-topnav-sign-in")).toBeVisible();
    await expect(page.getByTestId("tower-primary-cta")).toHaveAttribute("href", "/");
    await page.getByTestId("tower-primary-cta").click();
    await expect(page).toHaveURL(/\/$/);
  });
}

test("approved empty and skeleton states have no motion or cover glass", async ({ page }) => {
  await page.goto("/fixtures/states");
  await expect(page.getByRole("heading", { name: "No courses yet" })).toBeVisible();
  await expect(page.getByText("New lectures will appear here.")).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading" })).toBeVisible();
  const skeletons = page.getByTestId("tower-course-card-skeleton");
  await expect(skeletons).toHaveCount(8);
  for (const skeleton of await skeletons.all()) {
    await expect(skeleton).toHaveAttribute("aria-hidden", "true");
    await expect(skeleton).toHaveCSS("animation-name", "none");
    await expect(skeleton.locator('[data-testid="tower-cover-glass"]')).toHaveCount(0);
  }
  for (const width of [390, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    const desktop = width >= 1024;
    await expect(skeletons.first()).toHaveCSS("width", desktop ? "208px" : "140px");
    expect((await skeletons.first().boundingBox())?.height).toBe(desktop ? 448 : 334);
    await expect(page.getByTestId("tower-empty-catalog")).toHaveCSS("min-height", desktop ? "240px" : "200px");
  }
});

test("C1 Clear glass CTA has focus, pressed and disabled states", async ({ page }) => {
  await page.goto("/fixtures/states");
  const enabled = page.locator('[data-testid="tower-primary-cta"]:not([aria-disabled="true"])');
  const disabled = page.locator('[data-testid="tower-primary-cta"][aria-disabled="true"]');
  await expect(enabled).toHaveCSS("color", "rgb(242, 243, 245)");
  await expect(disabled).toHaveCSS("opacity", "0.4");
  await expect(disabled).not.toHaveAttribute("href");
  expect(await disabled.evaluate((element) => (element as HTMLElement).tabIndex)).toBe(-1);
  const canHover = await page.evaluate(() => window.matchMedia("(hover: hover) and (pointer: fine)").matches);
  if (canHover) {
    await enabled.hover();
    await expect(enabled).toHaveCSS("color", "rgb(255, 255, 255)");
    await page.mouse.move(0, 0);
    await expect(disabled).toHaveCSS("color", "rgb(242, 243, 245)");
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(enabled).toHaveCSS("transition-duration", "0s");
  await page.keyboard.press("Tab");
  await enabled.focus();
  await expect(enabled).toHaveCSS("outline-style", "none");
  await expect(enabled).toHaveCSS("box-shadow", /0px 0px 0px 3px/);
  const box = await enabled.boundingBox();
  if (!box) throw new Error("CTA must have a box.");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await expect(enabled).toHaveCSS("color", "rgb(214, 216, 220)");
  await page.mouse.move(0, 0);
  await page.mouse.up();
});
