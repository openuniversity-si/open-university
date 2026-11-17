import { mkdir, readFile, writeFile } from "node:fs/promises";
import { FIDELITY_FRAMES, VIEWPORT_HEIGHTS } from "../fidelity/frames.ts";
import type { GeometryBox } from "../fidelity/compare.ts";
import { test, expect } from "./fixtures/no-video-guard.ts";
import { readLocalSet } from "../fidelity/references/active.ts";
import { MEDIA_ART_MANIFEST, mediaArtKey, referenceMediaLayers } from "../fidelity/media.ts";
import pg from "pg";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { framesForPhase } from "../fidelity/resolve.ts";
import { seedProgress } from "./fixtures/progress.ts";

for (const frame of framesForPhase(FIDELITY_FRAMES, process.env.TOWER_FIDELITY_PHASE)) {
  test.describe(frame.id, () => {
    test.use({ viewport: { width: frame.viewport, height: VIEWPORT_HEIGHTS[frame.viewport] }, deviceScaleFactor: frame.dpr });
    test(`@fidelity capture ${frame.id}`, async ({ page, context, baseURL }, testInfo) => {
      const pool = frame.authState === "signed-in" ? new pg.Pool({ connectionString: process.env.TEST_DATABASE_URL }) : null;
      if (pool && (!process.env.TEST_DATABASE_URL || !baseURL)) throw new Error("F10 fidelity requires the local test database");
      const session = pool && baseURL ? await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET, name: "Daniel Bello" }) : null;
      if (pool && session && frame.progress === "spec06") await seedProgress(pool, session.userId);
      try {
        if (frame.authState === "continuing") await page.route("**/api/auth/sign-in/social", () => new Promise<void>(() => {}));
        await page.clock.install({ time: new Date("2026-10-08T12:00:00Z") });
        if (frame.capture === "fullPage") {
          // Figma's "Scroll content" is the static page: no fixed chrome (TopNav, BottomFadeScrim), and the
          // Footer in its Visible variant, which is what reduced motion renders at any scroll position.
          await page.emulateMedia({ reducedMotion: "reduce" });
        }
        await page.goto(frame.route);
        if (frame.authState === "signed-in") await expect(page.getByTestId("tower-topnav-avatar")).toBeVisible();
        if (frame.authState === "continuing") {
          await page.getByTestId("tower-topnav-sign-in").click();
          await expect(page.getByTestId("auth-continuing")).toBeVisible();
        }
        if (frame.route.includes("?error=")) await expect(page.getByTestId("tower-signin-feedback")).toBeVisible();
        for (const action of frame.actions ?? []) await page.locator(action.click).click();
        if (frame.capture === "fullPage") await page.addStyleTag({ content: "[data-fidelity-fixed] { visibility: hidden !important; }" });
        await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }" });
        // Capture offscreen rail art too. WebKit can abort decode() while a lazy image changes source.
        // On-demand posters (P8, ADR-23) have no src until they come near the viewport: give them theirs for the capture.
        await page.evaluate(() => {
          for (const image of document.images) {
            image.loading = "eager";
            if (!image.getAttribute("src") && image.dataset.posterSrc) image.src = image.dataset.posterSrc;
          }
        });
        await expect.poll(() => page.evaluate(() => Array.from(document.images).every((image) => image.complete && image.naturalWidth > 0))).toBe(true);
        await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all(Array.from(document.images, (image) => image.decode()));
          window.scrollTo(0, 0);
        });
        expect(frame.regions.length).toBeGreaterThan(0);
        const geometry: Record<string, GeometryBox> = {};
        for (const region of frame.regions) {
          // A refresh can briefly keep the outgoing tree beside the new one; measure the settled single node.
          await expect(page.locator(region.selector)).toHaveCount(1);
          const box = await page.locator(region.selector).boundingBox();
          if (!box) throw new Error(`Missing region ${frame.id}/${region.name}.`);
          geometry[region.name] = box;
        }
        if (testInfo.project.name === "chromium-desktop") {
          await mkdir(".reports/fidelity", { recursive: true });
          await page.screenshot({ path: `.reports/fidelity/${frame.id}.png`, fullPage: frame.capture === "fullPage", animations: "disabled", caret: "hide" });
          await writeFile(`.reports/fidelity/${frame.id}.geometry.json`, JSON.stringify(geometry));
          if (process.env.TOWER_FIDELITY_CAPTURE === "1") {
            const layers = referenceMediaLayers(frame, await readLocalSet());
            const artFiles = JSON.parse(await readFile(MEDIA_ART_MANIFEST, "utf8")) as Record<string, string>;
            const mediaGeometry: Record<string, GeometryBox> = {};
            for (const layer of layers) {
              const images = page.locator(layer.selector);
              // Hero media is clipped to its image container; the card image fills the poster.
              const container = layer.kind === "hero" ? page.getByTestId("tower-billboard-media") : images.first();
              const box = await container.boundingBox();
              if (!box) throw new Error(`Missing media geometry for ${frame.id}/${layer.nodeId}.`);
              mediaGeometry[layer.nodeId] = box;
              const file = artFiles[mediaArtKey(layer.nodeId, frame.dpr)];
              if (!file) throw new Error(`Missing locked artwork layer for ${frame.id}/${layer.nodeId}.`);
              const source = `data:image/png;base64,${(await readFile(file)).toString("base64")}`;
              await images.evaluateAll((elements, src) => {
                for (const element of elements) {
                  const image = element as HTMLImageElement;
                  image.closest("picture")?.querySelectorAll("source").forEach((source) => { source.remove(); });
                  image.removeAttribute("srcset");
                  image.src = src;
                  // The artwork export already has the locked crop. Only image-layer styles change;
                  // opacity, radius, glass, scrims, fades, text and their geometry remain untouched.
                  Object.assign(image.style, { left: "0", top: "0", width: "100%", height: "100%", transform: "none", objectFit: "fill" });
                }
              }, source);
            }
            await page.evaluate(async () => { await Promise.all(Array.from(document.images, (image) => image.decode())); });
            await page.screenshot({ path: `.reports/fidelity/${frame.id}.chrome.png`, fullPage: frame.capture === "fullPage", animations: "disabled", caret: "hide" });
            await writeFile(`.reports/fidelity/${frame.id}.media.json`, JSON.stringify(mediaGeometry));
          }
        }
      } finally { await session?.cleanup(); await pool?.end(); }
    });
  });
}
