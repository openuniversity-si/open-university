import { TEST_REDIRECTS, snapshotCatalog } from "../src/catalog/testing/fake.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";

/** ADR-17: the layout guards answer from the active release (the snapshot in the test build) before anything streams. */
test("an unknown course is a real 404 with the not-found page", async ({ page }) => {
  const response = await page.goto("/c/nao-existe");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expect(page.getByTestId("tower-loading")).toHaveCount(0);
});

for (const { from, to } of TEST_REDIRECTS) {
  test(`an old path answers 308 → ${to}`, async ({ request }) => {
    const response = await request.get(from, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    // The static /c/ pages cache the 308 (ISR); `next start` repeats an identical Location on the first, uncached render.
    const locations = (response.headers().location ?? "").split(", ");
    for (const location of locations) expect(new URL(location, "http://x").pathname).toBe(to);
    expect((await request.get(to, { maxRedirects: 0 })).status()).toBe(200);
  });
}

test("the Authors tab renders the release rows and the featured course; the Home links to it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("home-portal-authors")).toHaveAttribute("href", "/authors");
  await page.goto("/authors");
  const featured = snapshotCatalog.courses.find((course) => course.id === snapshotCatalog.home.featuredCourseId);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(featured?.displayTitle ?? "");
  for (const row of snapshotCatalog.home.rows.filter((entry) => entry.kind !== "continue")) {
    await expect(page.getByTestId(`rail-header-${row.id}`)).toHaveText(row.title);
    await expect(page.getByTestId(`rail-row-${row.id}`).locator("a")).toHaveCount(row.courseIds.length);
  }
});
