import { expect } from "vitest";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import { PROGRESS_THROTTLE_SECONDS } from "../domain/rules.ts";
import type { ProgressRepositoryPort, ProgressWrite } from "../ports/repo.ts";
import type { ProgressMaintenancePort } from "../ports/maintenance.ts";

export interface ProgressBench {
  readonly port: ProgressRepositoryPort;
  maintenanceIn(tx: UnitOfWork): ProgressMaintenancePort;
  readonly clock: { now(): number; advance(milliseconds: number): void };
  completedAt(userId: string, lessonId: string): Promise<number | null>;
  reset(): Promise<void>;
  dispose(): Promise<void>;
  transaction<T>(work: (tx: UnitOfWork) => Promise<T>): Promise<T>;
}

const write = (userId: string, positionSeconds?: number, completed?: boolean): ProgressWrite => ({
  userId, courseId: "course-ready", lessonId: "lesson-ready", durationSeconds: 60, positionSeconds, completed,
});

/** Throttle, completion and orphan cases. The clock is injected; the bench does not read the wall clock. */
export function progressContract(): ContractSuite<ProgressBench> {
  const windowMs = PROGRESS_THROTTLE_SECONDS * 1000;
  return {
    portId: "ProgressRepositoryPort",
    cases: [
      { id: "progress.throttle.boundary", async run(harness) {
        expect(await harness.port.save(write("user-a", 10))).toBe(true);
        harness.clock.advance(windowMs - 1);
        expect(await harness.port.save(write("user-a", 11))).toBe(false);
        const held = await harness.port.read("user-a");
        expect(held[0]?.positionSeconds).toBe(10);
        harness.clock.advance(1);
        expect(await harness.port.save(write("user-a", 12))).toBe(true);
        expect((await harness.port.read("user-a"))[0]?.positionSeconds).toBe(12);
      } },
      { id: "progress.completion.preserves", async run(harness) {
        const started = harness.clock.now();
        expect(await harness.port.save(write("user-a", 4, true))).toBe(true);
        expect(await harness.completedAt("user-a", "lesson-ready")).toBe(started);
        harness.clock.advance(1);
        expect(await harness.port.save(write("user-a", undefined, true))).toBe(true);
        const second = (await harness.port.read("user-a"))[0];
        expect(second?.completed).toBe(true);
        expect(second?.positionSeconds).toBe(4);
        expect(second?.updatedAt).toBe(started + 1);
        expect(await harness.completedAt("user-a", "lesson-ready")).toBe(started);
      } },
      { id: "progress.completion.uncheck", async run(harness) {
        await harness.port.save(write("user-a", 4, true));
        harness.clock.advance(1);
        expect(await harness.port.save(write("user-a", undefined, false))).toBe(true);
        expect((await harness.port.read("user-a"))[0]?.completed).toBe(false);
      } },
      { id: "progress.users.isolated", async run(harness) {
        await harness.port.save(write("user-a", 3));
        await harness.port.save(write("user-b", 8));
        expect((await harness.port.read("user-a"))[0]?.positionSeconds).toBe(3);
        expect((await harness.port.read("user-b"))[0]?.positionSeconds).toBe(8);
        expect(await harness.port.read("user-c")).toEqual([]);
      } },
      { id: "progress.maintenance.orphans", async run(harness) {
        await harness.port.save(write("user-a", 1));
        await harness.port.save({ ...write("user-a", 2), lessonId: "lesson-old" });
        const count = await harness.transaction((tx) => harness.maintenanceIn(tx).countForLessons(["lesson-ready"]));
        const orphans = await harness.transaction((tx) => harness.maintenanceIn(tx).orphanedLessons(["lesson-ready"]));
        expect(count).toBe(1);
        expect(orphans).toEqual({ count: 1, sample: ["lesson-old"] });
        expect(await harness.transaction((tx) => harness.maintenanceIn(tx).countForLessons([]))).toBe(0);
      } },
      { id: "progress.save.rollback", async run(harness) {
        await expect(harness.transaction(async () => {
          await harness.port.save(write("user-a", 6));
          throw new Error("no");
        })).rejects.toThrow("no");
        expect(await harness.port.read("user-a")).toEqual([]);
      } },
    ],
  };
}
