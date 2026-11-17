import { describe, expect, it } from "vitest";
import { batchShas, benchReport, syntheticBatch } from "./factory-bench.ts";

describe("factory bench", () => {
  it("builds a CatalogBatchV2 of the requested size with its own institution", () => {
    const batch = syntheticBatch(3);
    expect(batch.courses.map((item) => item.course.id)).toEqual(["b0000", "b0001", "b0002"]);
    expect(batch.institutions.map((item) => item.kind)).toEqual(["institution"]);
    expect(batch.lecturers.map((item) => item.id)).toEqual(["bench-lecturer"]);
    expect(new Set(batch.courses.flatMap((item) => item.lessons.map((lesson) => lesson.youtubeId))).size).toBe(6);
    expect(batchShas(batch).length).toBeGreaterThan(0);
    const resident = syntheticBatch(2, "e");
    expect(resident.courses.map((item) => item.course.id)).toEqual(["e0000", "e0001"]);
    expect(resident.institutions.map((item) => item.id)).toEqual(["bench-e"]);
    const ids = new Set([...batch.courses, ...resident.courses].map((item) => item.course.id));
    expect(ids.size).toBe(5);
  });

  it("lists every phase and warns above the dry-run and write budgets without dropping a phase", () => {
    const report = benchReport(1000, [
      { name: "dryRun", ms: 30_001 },
      { name: "write", ms: 60_001 },
      { name: "releaseMs", ms: 40 },
    ]);
    expect(report.phases.map((phase) => phase.name)).toEqual(["dryRun", "write", "releaseMs"]);
    expect(report.warnings).toEqual(["dry run 30001ms exceeds 30000ms", "write 60001ms exceeds 60000ms"]);
    expect(benchReport(1, [{ name: "dryRun", ms: 10 }, { name: "write", ms: 20 }, { name: "releaseMs", ms: 5 }]).warnings).toEqual([]);
  });
});
