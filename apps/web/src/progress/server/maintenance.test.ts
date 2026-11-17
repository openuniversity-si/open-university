import { describe, expect, it } from "vitest";
import { countLessonProgress, progressMaintenance } from "./maintenance.ts";

describe("progress maintenance", () => {
  it("counts rows and never deletes them", async () => {
    const sqls: string[] = [];
    const db = { query: (sql: string) => { sqls.push(sql); return Promise.resolve({ rows: [{ n: 3, sample: ["lesson-9"] }] }); } };
    expect(await countLessonProgress(db, ["lesson-9"])).toBe(3);
    expect(await progressMaintenance(db).orphanedLessons(["lesson-1"])).toEqual({ count: 3, sample: ["lesson-9"] });
    expect(sqls.join("\n")).not.toMatch(/DELETE|UPDATE/i);
  });
});