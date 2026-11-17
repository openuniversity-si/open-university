import { describe, expect, it } from "vitest";
import type { NoVideoRecord, NoVideoViolation } from "../../e2e/fixtures/no-video-policy.ts";
import { summarizeNoVideoRecords } from "./no-video-report.ts";

function record(file: string, violations: NoVideoViolation[], expectedStatus = "passed"): NoVideoRecord {
  return { testId: file, title: file, project: "chromium-desktop", file, expectedStatus, violations };
}

const selftests: NoVideoRecord[] = [
  record("e2e/no-video-guard.selftest.spec.ts", [{ kind: "request", url: "https://stream.mux.com/x.m3u8" }], "failed"),
  record("e2e/no-video-guard.selftest.spec.ts", [{ kind: "request", url: "https://inferred.litix.io/x" }], "failed"),
  record("e2e/no-video-guard.selftest.spec.ts", [{ kind: "play-call", src: "" }], "failed"),
  record("e2e/no-video-guard.selftest.spec.ts", [{ kind: "play-event", src: "" }], "failed"),
];

describe("summarizeNoVideoRecords", () => {
  it("passes with clean tests and complete self-tests", () => {
    const summary = summarizeNoVideoRecords([record("e2e/home.spec.ts", []), ...selftests]);
    expect(summary.ok).toBe(true);
    expect(summary.lines.at(-1)).toBe("verify:no-video: PASS");
  });

  it("fails when a regular test touched the Mux", () => {
    const summary = summarizeNoVideoRecords([record("e2e/home.spec.ts", [{ kind: "request", url: "https://stream.mux.com/a.m3u8" }]), ...selftests]);
    expect(summary.ok).toBe(false);
    expect(summary.lines.join("\n")).toContain("request to https://stream.mux.com/a.m3u8");
  });

  it("fails when a regular test called play()", () => {
    expect(summarizeNoVideoRecords([record("e2e/home.spec.ts", [{ kind: "play-call", src: "" }]), ...selftests]).ok).toBe(false);
  });

  it("fails without any regular record", () => {
    expect(summarizeNoVideoRecords(selftests).ok).toBe(false);
  });

  it("fails when the self-tests are missing (guard not proven active)", () => {
    expect(summarizeNoVideoRecords([record("e2e/home.spec.ts", [])]).ok).toBe(false);
  });

  it("fails when a self-test recorded nothing", () => {
    const silent = record("e2e/no-video-guard.selftest.spec.ts", [], "failed");
    expect(summarizeNoVideoRecords([record("e2e/home.spec.ts", []), ...selftests, silent]).ok).toBe(false);
  });

  it("fails when a self-test is not marked as an expected failure", () => {
    const unmarked = record("e2e/no-video-guard.selftest.spec.ts", [{ kind: "play-call", src: "" }], "passed");
    expect(summarizeNoVideoRecords([record("e2e/home.spec.ts", []), ...selftests, unmarked]).ok).toBe(false);
  });

  it("fails when a violation kind was never proven", () => {
    const partial = selftests.filter((r) => r.violations[0]?.kind !== "play-event");
    expect(summarizeNoVideoRecords([record("e2e/home.spec.ts", []), ...partial]).ok).toBe(false);
  });
});
