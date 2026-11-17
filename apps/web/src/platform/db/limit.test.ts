import { describe, expect, it } from "vitest";
import { limitConcurrency } from "./limit.ts";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("limitConcurrency", () => {
  it("keeps results in call order and never runs more than the limit", async () => {
    const occupy = limitConcurrency(2);
    let active = 0;
    let peak = 0;
    const results = await Promise.all([0, 1, 2, 3, 4].map((value) => occupy(async () => {
      active += 1;
      peak = Math.max(peak, active);
      await delay(15);
      active -= 1;
      return value;
    })));
    expect(results).toEqual([0, 1, 2, 3, 4]);
    expect(peak).toBe(2);
  });

  it("releases a slot when a task fails so the rest still finish", async () => {
    const occupy = limitConcurrency(1);
    const results = await Promise.allSettled([
      occupy(() => Promise.reject(new Error("first"))),
      occupy(() => Promise.resolve("second")),
    ]);
    expect(results[0].status).toBe("rejected");
    expect(results[1]).toEqual({ status: "fulfilled", value: "second" });
  });
});
