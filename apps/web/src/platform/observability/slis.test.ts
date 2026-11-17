import { describe, expect, it } from "vitest";
import { collectOperationalSlis, lastPublishDuration, markPublishStart, publicDiagnostics, recordPublishCommitted } from "./slis.ts";

describe("operational SLIs", () => {
  it("counts provoked drift and leaves a cold start without a publish sample", async () => {
    expect(lastPublishDuration()).toBeNull();
    expect(publicDiagnostics()).toBe("unknown");
    const report = await collectOperationalSlis({
      activeReleaseNumber: () => Promise.resolve(4),
      projectionCount: () => Promise.resolve(3),
      projectionDriftCount: () => Promise.resolve(1),
      pool: () => ({ total: 1, idle: 0, waiting: 2 }),
    });
    expect(report).toEqual({
      activeReleaseNumber: 4, projectionCount: 3, projectionDriftCount: 1,
      pool: { total: 1, idle: 0, waiting: 2 }, lastPublishDurationMs: null, scope: "process",
    });
    expect(JSON.stringify(report)).not.toMatch(/postgres:|sha256|token/i);
    markPublishStart(1_000);
    expect(publicDiagnostics()).toBe("unknown");
    recordPublishCommitted(1_250);
    expect(lastPublishDuration()).toBe(250);
    expect(publicDiagnostics()).toBe("ok");
  });
});
