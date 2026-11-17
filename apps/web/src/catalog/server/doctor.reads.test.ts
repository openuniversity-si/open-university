import { describe, expect, it } from "vitest";
import { runDoctor } from "./doctor.ts";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("runDoctor", () => {
  it("keeps the legacy-media check and overlaps independent reads", async () => {
    let active = 0;
    let peak = 0;
    const db = {
      async query(sql: string) {
        active += 1;
        peak = Math.max(peak, active);
        await delay(5);
        active -= 1;
        if (sql.includes("course_assets")) return { rows: [{ ref: "course_assets" }] };
        if (sql.includes("jsonb_agg")) return { rows: [{ rows: [] }] };
        return { rows: [] };
      },
    };
    const outcome = await runDoctor({ db, deps: { now: () => new Date("2026-10-24T00:00:00.000Z") } } as never);
    const data = outcome.data as { ok: boolean; findings: { code: string }[] };
    const codes = data.findings.map((finding) => finding.code);
    expect(codes[0]).toBe("media.legacy.reader");
    expect(codes).toContain("release.none");
    expect(data.ok).toBe(false);
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(5);
  });
});
