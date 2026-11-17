import pg from "pg";
import { test, expect } from "./fixtures/no-video-guard.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";

// @engine: WebKit does not focus buttons on click, so focus restoration differs.
test("avatar opens the account menu, restores focus, and logout deletes its DB session in place", { tag: "@engine" }, async ({ page, context, baseURL }) => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString || !baseURL) throw new Error("Local auth test database and baseURL required");
  validateDatabaseUrl(connectionString, "container");
  const pool = new pg.Pool({ connectionString });
  const fixture = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
  try {
    await page.goto("/c/fixture-course-1?view=lectures#content");
    const avatar = page.getByTestId("tower-topnav-avatar");
    await expect(avatar).toHaveText("D");
    expect((await avatar.boundingBox())?.height).toBe(44);
    const circle = page.getByTestId("tower-avatar-circle");
    expect((await circle.boundingBox())?.width).toBe(await page.evaluate(() => innerWidth >= 1024 ? 36 : 32));
    const lesson = page.locator('[data-testid^="playlist-item-"]').first();
    await lesson.click();
    const route = page.url();
    const scroll = await page.evaluate(() => scrollY);
    await avatar.click();
    await expect(avatar).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("menu", { name: "Account" })).toContainText("Daniel Bello");
    await expect(page.getByTestId("tower-account-overlay")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("tower-account-menu")).toHaveCount(0);
    await expect(avatar).toBeFocused();
    await avatar.click();
    await page.getByRole("button", { name: "Close account menu" }).click({ position: { x: 10, y: 200 } });
    await expect(avatar).toBeFocused();
    await avatar.click();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("menuitem", { name: "Sign out" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("tower-topnav-sign-in")).toBeVisible();
    await expect(page.getByTestId("tower-account-menu")).toHaveCount(0);
    expect((await pool.query('SELECT id FROM "session" WHERE id=$1', [fixture.sessionId])).rowCount).toBe(0);
    expect(page.url()).toBe(route);
    expect(await page.evaluate(() => scrollY)).toBe(scroll);
    await expect(lesson).toHaveAttribute("data-selected", "true");
    expect(await (await context.request.get("/api/auth/get-session")).json()).toBeNull();
  } finally { await fixture.cleanup(); await pool.end(); }
});

for (const error of ["access_denied", "oauth_failed"]) {
  test(`callback ${error} consumes query in place and feedback lasts four seconds`, async ({ page }) => {
    const now = new Date("2026-10-09T12:00:00Z");
    await page.clock.install({ time: now });
    await page.clock.pauseAt(now);
    const sessionReady = page.waitForResponse("**/api/auth/get-session");
    await page.goto(`/authors?keep=1&error=${error}&error_description=provider#content`);
    await sessionReady;
    await page.clock.runFor(16);
    const feedback = page.getByTestId("tower-signin-feedback");
    await expect(feedback).toHaveAttribute("data-kind", error === "access_denied" ? "cancelled" : "error");
    await expect(page).toHaveURL(/\/authors\?keep=1#content$/);
    const card = page.getByTestId("course-card-course-2");
    await card.click();
    await page.evaluate(() => { window.scrollTo(0, 300); });
    const scroll = await page.evaluate(() => scrollY);
    await page.clock.fastForward(3999);
    await expect(feedback).toBeVisible();
    await page.clock.fastForward(1);
    await expect(feedback).toHaveCount(0);
    await expect(card).toHaveAttribute("data-selected", "true");
    expect(await page.evaluate(() => scrollY)).toBe(scroll);
    await expect(page).toHaveURL(/\/authors\?keep=1#content$/);
  });
}

test("Google initiation and retry preserve route, scroll, and selection on failure", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/auth/sign-in/social", async (route) => {
    calls++;
    expect(route.request().postDataJSON()).toMatchObject({ provider: "google", callbackURL: "/authors?keep=1#content", disableRedirect: true });
    await route.fulfill({ status: 503, json: { code: "GOOGLE_SIGN_IN_UNAVAILABLE" } });
  });
  await page.goto("/authors?keep=1#content");
  await page.getByTestId("course-card-course-2").click();
  await page.evaluate(() => { window.scrollTo(0, 300); });
  const scroll = await page.evaluate(() => scrollY);
  await page.getByTestId("tower-topnav-sign-in").click();
  await expect(page.getByTestId("tower-signin-feedback")).toHaveAttribute("data-kind", "error");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("tower-signin-feedback")).toBeVisible();
  expect(calls).toBe(2);
  expect(await page.evaluate(() => scrollY)).toBe(scroll);
  await expect(page.getByTestId("course-card-course-2")).toHaveAttribute("data-selected", "true");
  await expect(page).toHaveURL(/\/authors\?keep=1#content$/);
});

for (const trigger of ["Mark complete", "TopNav"]) {
  test(`D2/D11 ${trigger} returns to the same lesson and second paused without completing it`, async ({ page }) => {
    const request = page.waitForRequest("**/api/auth/sign-in/social");
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/auth/sign-in/social", async (route) => { await held; await route.fulfill({ status: 503, json: {} }); });
    await page.goto("/fixtures/auth-player");
    if (trigger === "TopNav") await page.getByTestId("tower-topnav-sign-in").click();
    else await page.getByRole("button", { name: trigger }).click();
    const body = (await request).postDataJSON() as Record<string, unknown>;
    expect(body).toMatchObject({ provider: "google", callbackURL: "/c/genesis/lecture-4?view=lecture&t=3134#notes", newUserCallbackURL: "/c/genesis/lecture-4?view=lecture&t=3134#notes", errorCallbackURL: "/c/genesis/lecture-4?view=lecture&t=3134#notes" });
    await expect(page.getByTestId("auth-continuing")).toHaveText("Continuing with Google…");
    await expect(page.getByTestId("auth-player-state")).toHaveText("Paused");
    expect(await page.evaluate(() => sessionStorage.getItem("open-university:pending-completion:v1"))).toBeNull();
    release?.();
    await expect(page.getByTestId("tower-signin-feedback")).toBeVisible();
  });
}

test("a successful Google response navigates to the external provider", async ({ page }) => {
  await page.route("**/api/auth/sign-in/social", (route) => route.fulfill({ json: { url: "https://accounts.google.com/o/oauth2/v2/auth?state=synthetic" } }));
  await page.route("https://accounts.google.com/**", (route) => route.fulfill({ body: "Synthetic Google page" }));
  await page.goto("/authors");
  await page.getByTestId("tower-topnav-sign-in").click();
  await expect(page).toHaveURL("https://accounts.google.com/o/oauth2/v2/auth?state=synthetic");
});

test("OAuth return restores scroll and selection and hands pending completion to deferred F11 persistence", async ({ page, context, baseURL }) => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString || !baseURL) throw new Error("Local auth test database and baseURL required");
  validateDatabaseUrl(connectionString, "container");
  const pool = new pg.Pool({ connectionString });
  await page.route("**/api/auth/sign-in/social", (route) => route.fulfill({ json: { url: "https://accounts.google.com/o/oauth2/v2/auth?state=synthetic" } }));
  await page.route("https://accounts.google.com/**", (route) => route.fulfill({ body: "Synthetic Google page" }));
  await page.goto("/authors?view=selected");
  await page.getByTestId("course-card-course-2").click();
  await page.evaluate(() => {
    window.scrollTo(0, 300);
    sessionStorage.setItem("open-university:pending-completion:v1", JSON.stringify({ courseSlug: "genesis", lessonSlug: "lecture-4", endedAt: 123 }));
  });
  const scroll = await page.evaluate(() => scrollY);
  await page.getByTestId("tower-topnav-sign-in").click();
  await expect(page).toHaveURL("https://accounts.google.com/o/oauth2/v2/auth?state=synthetic");
  const fixture = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET });
  try {
    await page.goto("/authors?view=selected");
    await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
    await expect(page.getByTestId("course-card-course-2")).toHaveAttribute("data-selected", "true");
    expect(await page.evaluate(() => scrollY)).toBe(scroll);
    expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("open-university:pending-completion:v1") ?? "null") as unknown))
      .toEqual({ courseSlug: "genesis", lessonSlug: "lecture-4", endedAt: 123 });
    expect(await page.evaluate(() => sessionStorage.getItem("open-university:auth-return-ui:v1"))).toBeNull();
    expect((await pool.query('SELECT lesson_id FROM lesson_progress WHERE user_id=$1', [fixture.userId])).rowCount).toBe(0);
  } finally { await fixture.cleanup(); await pool.end(); }
});

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  test(`Continuing with Google capsule hugs its text and is centred at ${String(viewport.width)}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.route("**/api/auth/sign-in/social", () => undefined);
    await page.goto("/authors");
    // Production may ship glass.css after the CSS Module chunk; replay that order so the capsule cannot rely on winning the cascade.
    await page.addStyleTag({ content: ".tower-glass { position: relative; }" });
    await page.getByTestId("tower-topnav-sign-in").click();
    const capsule = page.getByTestId("auth-continuing-message");
    await expect(capsule).toBeVisible();
    const box = await capsule.evaluate((element) => { const r = element.getBoundingClientRect(); return { width: r.width, x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
    expect(box.width).toBeLessThan(300);
    expect(Math.abs(box.x - viewport.width / 2)).toBeLessThan(8);
    expect(Math.abs(box.y - viewport.height / 2)).toBeLessThan(8);
  });
}
