import { expect, test } from "./fixtures/no-video-guard.ts";

/**
 * Proves the ADR-11 guard rejects a test (expected failures via test.fail).
 * The page lives only inside this spec (route-fulfilled on a reserved .invalid
 * host), never in a production build. Nothing reaches the network and no
 * media plays: requests are aborted and play() never runs the real method.
 */
const SELFTEST_URL = "http://guard-selftest.invalid/";

// @engine: the guard patches each engine's HTMLMediaElement and network stack; it must hold in every engine.
test.describe("no-video guard self-test", { tag: "@engine" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.route(SELFTEST_URL, (route) =>
      route.fulfill({ contentType: "text/html", body: "<!doctype html><title>guard self-test</title><video></video>" }),
    );
    await page.goto(SELFTEST_URL);
  });

  test.fail("rejects a request to *.mux.com", async ({ page, noVideoGuard }) => {
    await page.evaluate(() => fetch("https://stream.mux.com/guard-selftest.m3u8").catch(() => undefined));
    await expect.poll(() => noVideoGuard.violations().map((v) => v.kind)).toContain("request");
  });

  test.fail("rejects a request to *.litix.io", async ({ page, noVideoGuard }) => {
    await page.evaluate(() => fetch("https://inferred.litix.io/guard-selftest").catch(() => undefined));
    await expect.poll(() => noVideoGuard.violations().map((v) => v.kind)).toContain("request");
  });

  test.fail("rejects HTMLMediaElement.play() and never runs the real method", async ({ page, noVideoGuard }) => {
    const outcome = await page.evaluate(async () => {
      const video = document.querySelector("video");
      if (video === null) return "missing video";
      try {
        await video.play();
        return "played";
      } catch (error) {
        return error instanceof DOMException ? error.name : "other error";
      }
    });
    expect(outcome).toBe("NotAllowedError");
    await expect.poll(() => noVideoGuard.violations().map((v) => v.kind)).toContain("play-call");
  });

  test.fail("rejects a media play event (autoplay path)", async ({ page, noVideoGuard }) => {
    await page.evaluate(() => document.querySelector("video")?.dispatchEvent(new Event("play")));
    await expect.poll(() => noVideoGuard.violations().map((v) => v.kind)).toContain("play-event");
  });
});
