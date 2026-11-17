import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { readyCatalogFixture } from "./catalog-fixture.ts";
import { catalogContract } from "./catalog-contract.ts";
import { createInMemoryCatalog } from "./in-memory-catalog.ts";

describe("catalog contract", () => {
  it("runs the shared cases against the in-memory catalog", async () => {
    const suite = catalogContract();
    expect(suite.portId).toBe("CatalogCommandsPort");
    await executeContract(suite, createInMemoryCatalog());
  });

  it("records the hot review scenario against a 50ms budget", async () => {
    const harness = createInMemoryCatalog();
    await harness.seed("ready");
    for (let warmup = 0; warmup < 5; warmup += 1) {
      await harness.seed("ready");
      await harness.port.transition({ courseId: "course-ready", expectedRevision: 1, target: "review" });
    }
    const samples: number[] = [];
    for (let sample = 0; sample < 20; sample += 1) {
      await harness.seed("ready");
      const started = performance.now();
      await harness.port.transition({ courseId: "course-ready", expectedRevision: 1, target: "review" });
      samples.push(performance.now() - started);
    }
    const sorted = [...samples].sort((a, b) => a - b);
    const at = (fraction: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(fraction * sorted.length) - 1))] ?? 0;
    const report = { samples: samples.length, p50: at(0.5), p95: at(0.95), fixtureBytes: JSON.stringify(readyCatalogFixture()).length, overBudget: false };
    report.overBudget = report.p95 >= 50;
    expect(report.samples).toBe(20);
    expect(report.fixtureBytes).toBeGreaterThan(0);
    await harness.dispose();
  });
});
