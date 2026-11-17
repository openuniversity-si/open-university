import { expect, test } from "./fixtures/no-video-guard.ts";

test("home renders the signed-out catalog without errors or video", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  const response = await page.goto("/");
  expect(response?.status()).toBe(200);
  await expect(page).toHaveTitle("Open University — Great lecture courses, in order");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(12, 12, 13)");
  await expect(page.getByTestId("tower-topnav-sign-in")).toHaveText("Sign in");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Course 1");
  // Home "Portais" (Daniel 14/10/2026): no rails; one portal per populated tab (the snapshot has only author rows).
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Explore"]);
  await expect(page.locator('[data-testid^="course-card-"]')).toHaveCount(0);
  await expect(page.getByTestId("home-portal-universities")).toHaveCount(0);
  await expect(page.getByTestId("home-portal-authors")).toHaveAttribute("href", "/authors");
  await expect(page.getByTestId("home-portal-authors")).toContainText("Fixture Lecturer 1 · Fixture Lecturer 2");
  await expect(page.getByText("Continue Watching")).toHaveCount(0);
  await expect(page.getByText("Resume", { exact: true })).toHaveCount(0);
  // ADR-16: the visitor Home is ISR.
  expect(response?.headers()["cache-control"]).toMatch(/s-maxage=\d+/);
  expect(response?.headers()["cache-control"]).not.toMatch(/private|no-store/);
  await expect(page.locator("video, audio")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("home first activation selects even the featured course; second opens its Course", async ({ page }) => {
  await page.goto("/authors");
  const first = page.getByTestId("course-card-course-1");
  const meta = page.getByTestId("tower-billboard-text").locator("p").nth(1);
  await expect(first).not.toHaveAttribute("aria-current");
  await expect(meta).toHaveText(/^Featured {2}· {2}17 lectures/);
  await first.click();
  await expect(page).toHaveURL(/\/authors$/);
  await expect(first).toHaveAttribute("aria-current", "true");
  await expect(first).toHaveAttribute("aria-description", "Selected. Activate again to open the course.");
  await expect(page.getByTestId("tower-billboard")).toHaveAttribute("data-selected", "true");
  await expect(meta).toHaveText(/^Selected {2}· {2}17 lectures/);
  await first.click();
  await expect(page).toHaveURL(/\/c\/fixture-course-1$/);
});

test("home selection changes Billboard, Start, details and only the selected ring", async ({ page }) => {
  await page.goto("/authors");
  await page.getByTestId("course-card-course-2").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Course 2");
  await expect(page.getByTestId("tower-primary-cta")).toHaveAttribute("href", "/c/fixture-course-2/fixture-lesson-52");
  await expect(page.getByTestId("tower-secondary-cta")).toHaveAttribute("href", "/c/fixture-course-2");
  await expect(page.locator('[data-testid^="course-card-"][aria-current="true"]')).toHaveCount(1);
  await page.getByTestId("course-card-course-5").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Course 5");
  await expect(page.getByTestId("course-card-course-2")).not.toHaveAttribute("aria-current");
  await expect(page.getByTestId("course-card-course-5")).toHaveAttribute("aria-current", "true");
});

// @engine: (hover)/(pointer: coarse) media queries change with the device's pointer.
test("home hover preserves featured content and coarse pointers have no hover shadow", { tag: "@engine" }, async ({ page }) => {
  await page.goto("/authors");
  const card = page.getByTestId("course-card-course-2");
  await card.hover();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Course 1");
  await expect(card).not.toHaveAttribute("aria-current");
  const frame = card.locator('span').first();
  const hover = await page.evaluate(() => matchMedia("(hover: hover) and (pointer: fine)").matches);
  await expect(frame).toHaveCSS("box-shadow", hover ? /rgba\(0, 0, 0, 0\.55\)/ : "none");
});

for (const activation of ["modifier", "middle"] as const) {
  test(`home ${activation} activation opens a native new tab without selection`, async ({ page, context }) => {
    await page.goto("/authors");
    const card = page.getByTestId("course-card-course-1");
    const popupPromise = context.waitForEvent("page");
    if (activation === "middle") await card.click({ button: "middle" });
    else await card.click({ modifiers: ["ControlOrMeta"] });
    const popup = await popupPromise;
    await expect(popup).toHaveURL(/\/c\/fixture-course-1$/);
    await expect(page).toHaveURL(/\/authors$/);
    await expect(card).not.toHaveAttribute("aria-current");
    await popup.close();
  });
}

test("home keyboard Enter and Space follow the two-step activation", async ({ page }) => {
  await page.goto("/authors");
  const card = page.getByTestId("course-card-course-1");
  await card.focus();
  await page.keyboard.press("Enter");
  await expect(card).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/\/c\/fixture-course-1$/);
});

test("home CoverGlass is card-only, decorative, inert and layered below the outside ring", async ({ page }) => {
  await page.goto("/authors");
  const cards = page.locator('[data-testid^="course-card-"]');
  await expect(page.getByTestId("tower-cover-glass")).toHaveCount(5);
  await expect(page.getByTestId("tower-billboard").getByTestId("tower-cover-glass")).toHaveCount(0);
  // The posters come from the real cover cache (`pnpm media:cache`, gate-local --nightly); without it a card has no image
  // and the layer order below cannot hold. Fail with the cause instead of a bare diff.
  expect(await page.locator('[data-testid="tower-card-cover"] picture').count(), "no posters: run `pnpm media:cache --target staging` before build:test (scripts/gate-local --nightly does)").toBeGreaterThan(0);
  for (const card of await cards.all()) {
    const glass = card.getByTestId("tower-cover-glass");
    await expect(glass).toHaveAttribute("aria-hidden", "true");
    await expect(glass).toHaveCSS("pointer-events", "none");
    await expect(glass).toHaveCSS("position", "absolute");
    await expect(glass).toHaveCSS("border-radius", "12px");
    await expect(glass).toHaveCSS("background-color", "rgba(255, 255, 255, 0.008)");
    await expect(glass).toHaveCSS("animation-name", "none");
    await expect(card.getByTestId("tower-card-cover")).toHaveCSS("overflow", "hidden");
    const order = await card.evaluate((element) => {
      const cover = element.querySelector('[data-testid="tower-card-cover"]');
      if (!cover) throw new Error("Missing cover.");
      // The poster is a <picture> (no preload); an on-demand one adds a <noscript> fallback (P8).
      const layers = Array.from(cover.children).filter((child) => child.tagName !== "NOSCRIPT");
      return { layers: layers.map((child) => child.tagName === "PICTURE" ? "Image" : child.getAttribute("data-testid")), ringOutside: cover.nextElementSibling?.getAttribute("aria-hidden") === "true" };
    });
    expect(order).toEqual({ layers: ["Image", "tower-cover-glass"], ringOutside: true });
    await expect(card.locator("img")).toHaveAttribute("alt", "");
    await expect(card).toHaveAttribute("aria-label", /.+/);
  }
  await page.getByTestId("course-card-course-1").click();
  const mobile = await page.evaluate(() => innerWidth < 1024);
  await expect(page.getByTestId("tower-billboard-scrim")).toHaveCSS("background-image", mobile ? /0\.98/ : /0\.72/);
});

for (const width of [390, 767, 768, 1023, 1024, 1366, 1920, 1921, 2560]) {
  test(`home layout and scrollable fixed-width cards at ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/authors");
    const card = page.getByTestId("course-card-course-1");
    await expect(card).toBeVisible({ timeout: 15_000 });
    await page.evaluate(() => document.fonts.ready);
    const desktop = width >= 1024;
    await expect(page.getByTestId("tower-billboard")).toHaveCSS("height", desktop ? "540px" : "620px");
    const box = await card.boundingBox();
    expect(box?.width).toBe(desktop ? 208 : 140);
    expect(box?.height).toBe(desktop ? 418 : 291);
    const name = card.getByTestId("tower-card-name");
    await expect(name).toHaveText("Biblical Series: Fixture Course 1");
    const coverBox = await card.getByTestId("tower-card-cover").boundingBox();
    const nameBox = await name.boundingBox();
    expect(nameBox && coverBox ? nameBox.y - coverBox.y - coverBox.height : undefined).toBe(8);
    const header = await page.getByTestId("rail-header-fixture-lecturer-1").boundingBox();
    expect(header?.x).toBe(desktop ? 80 : width >= 768 ? 32 : 20);
    // Hero, then the Home intro (two lines of text at 390, one from 767), then 28 px to the first rail.
    expect(header?.y).toBe(desktop ? 620 : width === 390 ? 749.5 : 727.75);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const row = page.getByTestId("rail-row-fixture-lecturer-1");
    if (width === 390) {
      await row.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
      const last = await page.getByTestId("course-card-course-3").boundingBox();
      expect(last ? width - last.x - last.width : undefined).toBe(20);
    }
  });
}

test("home Authors portal leads to the Authors tab", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("home-portal-authors").click();
  await expect(page).toHaveURL(/\/authors$/);
  await expect(page.getByTestId("rail-header-fixture-lecturer-1")).toBeVisible();
});
