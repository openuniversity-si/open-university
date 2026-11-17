import type { Page } from "@playwright/test";
import pg from "pg";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";
import { snapshotCatalog as catalog } from "../src/catalog/testing/fake.ts";
import { lessonsForCourse } from "../src/catalog/domain/queries.ts";
import { expect, test } from "./fixtures/no-video-guard.ts";
import { seedProgress } from "./fixtures/progress.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";

const course = catalog.courses[0];
if (!course) throw new Error("Featured course is required.");
const lessons = lessonsForCourse(catalog, course.id);
const first = lessons[0];
const last = lessons.at(-1);
if (!first || !last) throw new Error("Course lessons are required.");
const ROUTES = ["/", `/c/${course.slug}`, `/c/${course.slug}/${first.slug}`, `/c/${course.slug}/${last.slug}`, "/fixtures/states", "/fixtures/long-titles", "/missing-shell-page"] as const;

interface Target { readonly name: string; readonly scope: string; readonly x: number; readonly y: number; readonly width: number; readonly height: number }

/**
 * Every visible, enabled interactive element with its target box in content coordinates.
 * A box of at least 44 × 44 whose centre hits the element is its own target. A smaller control
 * may extend its hit area with a pseudo-element (TopNav `::after`, Play, Seek), so its target is
 * the first 44 × 44 square, sampled every CSS pixel within 44 px of it, where every point hits the
 * element (another control on top, such as full screen over the seek band, wins its pixels).
 * Containers of other targets (the scrollable lecture list), unfocusable dismiss layers and the focus-only
 * skip link are excluded.
 */
async function targets(page: Page, root: string): Promise<Target[]> {
  const count = await page.evaluate((root) => {
    for (const marked of document.querySelectorAll<HTMLElement>("[data-tower-target]")) delete marked.dataset.towerTarget;
    const selector = 'a[href], button, input, select, textarea, summary, [role="button"], [role="link"], [role="checkbox"], [role="slider"], [role="menuitem"], [tabindex]';
    const nodes = [...document.querySelectorAll<HTMLElement>(`${root} :is(${selector})`)].filter((node) => {
      if (node.classList.contains("tower-skip-link") || node.closest('[aria-hidden="true"], [inert]') || node.getAttribute("aria-disabled") === "true" || node.tabIndex < 0 || node.querySelector(selector)) return false;
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && box.width > 0 && box.height > 0;
    });
    nodes.forEach((node, index) => { node.dataset.towerTarget = String(index); });
    return nodes.length;
  }, root);
  const found: Target[] = [];
  for (let index = 0; index < count; index += 1) {
    const node = page.locator(`[data-tower-target="${String(index)}"]`);
    // This page is already hydrated and its fonts loaded. Native instant scrolling
    // updates offsets synchronously; the bounding-box/hit-test below forces layout.
    await node.evaluate((element) => { element.scrollIntoView({ behavior: "instant", block: "center", inline: "center" }); });
    found.push(await node.evaluate((element) => {
      const MIN = 44;
      const box = element.getBoundingClientRect();
      const name = `${element.tagName.toLowerCase()} "${(element.getAttribute("aria-label") ?? element.textContent).trim().slice(0, 40)}"`;
      // Content coordinates: undo window and inner (rail, lecture list) scrolling; fixed chrome stays in viewport space.
      // Overlap is compared within one scope: the nearest scroll container, fixed chrome or the page.
      let dx = 0; let dy = 0; let fixed = false; let scope = "";
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        dx += parent.scrollLeft; dy += parent.scrollTop;
        const style = getComputedStyle(parent);
        if (style.position === "fixed") fixed = true;
        if (scope === "" && parent !== document.body && parent !== document.documentElement && /auto|scroll/.test(style.overflowX + style.overflowY)) {
          parent.dataset.towerScope ??= String(document.querySelectorAll("[data-tower-scope]").length);
          scope = `scroller ${parent.dataset.towerScope}`;
        }
      }
      if (scope === "") scope = fixed ? "fixed" : "page";
      if (!fixed) { dx += scrollX; dy += scrollY; }
      const hits = (x: number, y: number) => { const hit = document.elementFromPoint(x, y); return hit !== null && (hit === element || element.contains(hit)); };
      const missing = { name, scope, x: 0, y: 0, width: 0, height: 0 };
      if (box.width >= MIN && box.height >= MIN) {
        return hits(box.x + box.width / 2, box.y + box.height / 2) ? { name, scope, x: box.x + dx, y: box.y + dy, width: box.width, height: box.height } : { ...missing, name: `${name} (covered)` };
      }
      const left = Math.floor(box.left - MIN); const top = Math.floor(box.top - MIN);
      const columns = Math.ceil(box.right + MIN) - left; const rows = Math.ceil(box.bottom + MIN) - top;
      // Summed-area table of hit samples at pixel centres.
      const sum = new Int32Array((columns + 1) * (rows + 1));
      let hitCount = 0;
      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
          const hit = hits(left + column + 0.5, top + row + 0.5) ? 1 : 0;
          hitCount += hit;
          sum[(row + 1) * (columns + 1) + column + 1] = hit + (sum[row * (columns + 1) + column + 1] ?? 0) + (sum[(row + 1) * (columns + 1) + column] ?? 0) - (sum[row * (columns + 1) + column] ?? 0);
        }
      }
      const at = (row: number, column: number) => sum[row * (columns + 1) + column] ?? 0;
      for (let row = 0; row + MIN <= rows; row += 1) {
        for (let column = 0; column + MIN <= columns; column += 1) {
          if (at(row + MIN, column + MIN) - at(row, column + MIN) - at(row + MIN, column) + at(row, column) === MIN * MIN) {
            return { name, scope, x: left + column + dx, y: top + row + dy, width: MIN, height: MIN };
          }
        }
      }
      return { ...missing, name: `${name} (no ${String(MIN)} × ${String(MIN)} hit square; ${String(hitCount)} px hit)` };
    }));
  }
  return found;
}

function overlaps(a: Target, b: Target): boolean {
  if (a.scope !== b.scope) return false;
  const x = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const y = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return x > 0.5 && y > 0.5;
}

/** Targets under `root` (an open menu covers the page, so only its own items are measured then). */
async function expectTargets(page: Page, root = "body"): Promise<void> {
  const found = await targets(page, root);
  expect(found.length).toBeGreaterThan(0);
  expect(found.filter((target) => target.width < 44 || target.height < 44).map((target) => `${target.name} ${target.width.toFixed(1)}×${target.height.toFixed(1)}`)).toEqual([]);
  const pairs: string[] = [];
  for (const [index, a] of found.entries()) for (const b of found.slice(index + 1)) if (overlaps(a, b)) pairs.push(`${a.name} ∩ ${b.name}`);
  expect(pairs).toEqual([]);
}

for (const route of ROUTES) {
  // @engine: no explicit viewport: only the mobile projects measure 390 px touch targets.
  test(`${route}: every target is at least 44 × 44 CSS px and none overlap`, { tag: "@engine" }, async ({ page }) => {
    await page.goto(route);
    // Measure the settled page: under parallel load a hit-test before hydration/fonts finds the footer briefly covered.
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await expectTargets(page);
  });
}

test.describe("signed in (Spec 06 progress)", () => {
  let pool: pg.Pool;
  test.beforeAll(() => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required for signed-in targets.");
    validateDatabaseUrl(connectionString, "container");
    pool = new pg.Pool({ connectionString });
  });
  test.afterAll(async () => { await pool.end(); });

  // @engine: no explicit viewport: only the mobile projects measure 390 px touch targets.
  test("Home, Course, Player and the open account menu keep 44 px targets without overlap", { tag: "@engine" }, async ({ page, context, baseURL }) => {
    if (!baseURL) throw new Error("baseURL is required.");
    const viewer = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" });
    try {
      await seedProgress(pool, viewer.userId);
      for (const route of ["/", `/c/${course.slug}`, `/c/${course.slug}/${first.slug}`]) {
        await page.goto(route);
        await expectTargets(page);
      }
      await page.getByTestId("tower-topnav-avatar").click();
      await expect(page.getByTestId("tower-account-menu")).toBeVisible();
      await expectTargets(page, '[data-testid="tower-account-menu"]');
    } finally { await viewer.cleanup(); }
  });
});
