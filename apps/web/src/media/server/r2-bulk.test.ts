import { afterEach, describe, expect, it } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import { createS3Bucket, r2Config, type StorageClock } from "./r2.ts";
import { assertR2Budget, DEFAULT_R2_BUDGET, mapLimited, physicalSlotsInFlight, setPhysicalSlotLimit, withPhysicalSlot } from "./r2-budget.ts";

const budget = DEFAULT_R2_BUDGET;
const wait = (ms: number) => new Promise((resolve) => { setTimeout(resolve, ms); });

afterEach(() => { setPhysicalSlotLimit(DEFAULT_R2_BUDGET.concurrency); });

describe("R2 budget", () => {
  it("rejects concurrency outside 1..16 before any work", async () => {
    for (const concurrency of [0, -1, 1.5, 17]) {
      expect(() => { assertR2Budget({ ...budget, concurrency }); }).toThrow(AppError);
      await expect(mapLimited([1], () => Promise.resolve(1), { ...budget, concurrency })).rejects.toThrow(AppError);
    }
  });

  it("keeps result order, stops scheduling after the first failure and drains in-flight work", async () => {
    const ordered = await mapLimited([1, 2, 3], (item) => Promise.resolve(item * 2), { ...budget, concurrency: 2 });
    expect(ordered).toEqual([2, 4, 6]);
    const started: number[] = [];
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const failed = mapLimited([1, 2, 3], async (item) => {
      started.push(item);
      if (item === 1) throw new Error("stop");
      await gate;
      return item;
    }, { ...budget, concurrency: 1 });
    await expect(failed).rejects.toThrow("stop");
    release?.();
    expect(started).toEqual([1]);
    expect(physicalSlotsInFlight()).toBe(0);
  });

  it("shares one physical semaphore across two batches and a single operation", async () => {
    setPhysicalSlotLimit(2);
    let current = 0;
    let max = 0;
    const occupy = async () => {
      await withPhysicalSlot(async () => {
        current += 1;
        max = Math.max(max, current);
        await wait(30);
        current -= 1;
      });
    };
    await Promise.all([
      mapLimited([1, 2, 3, 4], occupy, { ...budget, concurrency: 4 }),
      mapLimited([5, 6], occupy, { ...budget, concurrency: 4 }),
      occupy(),
    ]);
    expect(max).toBeLessThanOrEqual(2);
    expect(max).toBe(2);
    expect(physicalSlotsInFlight()).toBe(0);
  });

  it("does not take a physical slot for logical fan-out", async () => {
    let seen = -1;
    await mapLimited([1, 2], () => { seen = physicalSlotsInFlight(); return Promise.resolve(); }, { ...budget, concurrency: 2 });
    expect(seen).toBe(0);
  });

  it("stops retrying when the injected clock passes the total deadline", async () => {
    let now = 0;
    const waits: number[] = [];
    const clock: StorageClock = {
      now: () => now,
      wait(ms) { waits.push(ms); now += 61_000; return Promise.resolve(); },
      jitter: () => 3,
    };
    const bucket = createS3Bucket(r2Config({
      R2_ENDPOINT: "http://127.0.0.1:9", R2_ACCESS_KEY_ID_RW: "key", R2_SECRET_ACCESS_KEY_RW: "secret",
    }, "open-university-media", "rw"), clock);
    const fetches: number[] = [];
    const original = globalThis.fetch;
    globalThis.fetch = () => { fetches.push(now); return Promise.reject(new TypeError("fetch failed")); };
    try {
      await expect(bucket.head("covers/deadline.jpg")).rejects.toThrow(/deadline|failed before a response/);
    } finally { globalThis.fetch = original; }
    expect(fetches.length).toBeLessThan(5);
    expect(waits[0]).toBe(53);
  });
});
