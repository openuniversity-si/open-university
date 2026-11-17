import { describe, expect, it } from "vitest";
import { runBench } from "./factory-bench.ts";

describe("factory bench", () => {
  it("dry-runs and writes two courses, then releases one of them", async () => {
    const report = await runBench(2);
    expect(report.courses).toBe(2);
    expect(report.phases.map((phase) => phase.name)).toEqual(["dryRun", "write", "releaseMs"]);
    expect(report.phases.every((phase) => phase.ms >= 0)).toBe(true);
    expect(report.warnings).toEqual([]);
  });

  it("D-033: dry-runs one course on top of a resident catalog", async () => {
    const report = await runBench(1, 1);
    expect(report.courses).toBe(1);
    expect(report.phases.map((phase) => phase.name)).toEqual(["dryRun", "write", "releaseMs"]);
    expect(report.warnings).toEqual([]);
  });
});
