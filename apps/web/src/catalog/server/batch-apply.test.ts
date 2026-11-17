import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function between(source: string, start: string, end: string): string {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  return source.slice(from, to);
}

describe("batch apply halves", () => {
  it("D-053: the row write does not publish, and apply calls publication only for a live batch", () => {
    const source = readFileSync(new URL("./batch-apply.ts", import.meta.url), "utf8");
    const write = between(source, "export async function writeBatchRows", "export async function publishAppliedBatch");
    expect(write).not.toContain("publishShipCourses");
    expect(write).not.toContain("publishRelease");
    expect(write).not.toContain("evaluateRules");
    const publish = between(source, "export async function publishAppliedBatch", "function summary");
    expect(publish).toContain("publishShipCourses");
    expect(publish).toContain('evaluateRules("published"');
    expect(publish).toContain("publishRelease");
    const apply = source.slice(source.indexOf("export async function applyBatch"));
    expect(apply).toContain("writeBatchRows(");
    expect(apply).toContain("if (!body.draft)");
    expect(apply).toContain("publishAppliedBatch(");
    expect(apply).toContain("course.publish.apply");
  });
});
