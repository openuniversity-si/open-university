import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { test as base, expect } from "@playwright/test";
import { applyLocalHttpPolicy } from "./local-http.ts";
import {
  describeViolation,
  isBlockedVideoUrl,
  PLAY_INSTRUMENTATION_SCRIPT,
  type NoVideoRecord,
  type NoVideoViolation,
} from "./no-video-policy.ts";

/** Where each test's record is written; `pnpm verify:no-video` consolidates them. */
export const NO_VIDEO_REPORT_DIR = path.resolve(import.meta.dirname, "../../.reports/no-video");

export interface NoVideoGuard {
  /** Violations recorded so far in the current test. */
  violations(): readonly NoVideoViolation[];
}

/**
 * Global guard (ADR-11). For every test it:
 * - aborts and records any browser request to *.mux.com / *.litix.io;
 * - replaces HTMLMediaElement.prototype.play so a call is recorded and never plays;
 * - records media "play" events (e.g. autoplay);
 * - writes a record for verify:no-video and fails the test on any violation.
 */
export const test = base.extend<{ noVideoGuard: NoVideoGuard }>({
  noVideoGuard: [
    async ({ context, baseURL }, run, testInfo) => {
      // Each isolated browser represents a different client. Keep the real DB limiter enabled.
      const ip = createHash("sha256").update(testInfo.testId).digest();
      await context.setExtraHTTPHeaders({ "x-forwarded-for": `198.18.${String(ip[0])}.${String(ip[1])}` });
      const violations: NoVideoViolation[] = [];

      await context.route(
        (url) => isBlockedVideoUrl(url.href),
        async (route) => {
          violations.push({ kind: "request", url: route.request().url() });
          await route.abort("blockedbyclient");
        },
      );
      await context.exposeBinding("__towerNoVideoReport", (_source, payload: { kind: "play-call" | "play-event"; src: string }) => {
        violations.push({ kind: payload.kind, src: payload.src });
      });
      await context.addInitScript({ content: PLAY_INSTRUMENTATION_SCRIPT });

      const restoreTransport = applyLocalHttpPolicy(context.request, baseURL);
      try {
        await run({ violations: () => [...violations] });
      } finally {
        restoreTransport();
      }

      const record: NoVideoRecord = {
        testId: testInfo.testId,
        title: testInfo.titlePath.join(" › "),
        project: testInfo.project.name,
        file: path.relative(testInfo.config.rootDir, testInfo.file),
        expectedStatus: testInfo.expectedStatus,
        violations,
      };
      await mkdir(NO_VIDEO_REPORT_DIR, { recursive: true });
      await writeFile(
        path.join(NO_VIDEO_REPORT_DIR, `${testInfo.testId}-retry${String(testInfo.retry)}.json`),
        `${JSON.stringify(record, null, 2)}\n`,
      );

      if (violations.length > 0) {
        throw new Error(`no-video guard (ADR-11): ${violations.map(describeViolation).join("; ")}`);
      }
    },
    { auto: true },
  ],
});

export { expect };
