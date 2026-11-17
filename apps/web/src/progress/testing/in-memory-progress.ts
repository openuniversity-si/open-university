import { createInMemoryUnitOfWork, type InMemoryUnitOfWork, type TestClock, createTestClock } from "../../platform/db/testing/in-memory-uow.ts";
import { PROGRESS_THROTTLE_SECONDS, type ProgressRow } from "../domain/rules.ts";
import type { ProgressRepositoryPort, ProgressWrite } from "../ports/repo.ts";
import type { ProgressMaintenancePort } from "../ports/maintenance.ts";
import type { Queryable, UnitOfWork } from "../../platform/db/uow.ts";
import type { ProgressBench } from "./progress-contract.ts";

interface StoredProgress extends ProgressRow {
  readonly userId: string;
  readonly courseId: string;
  readonly completedAt: number | null;
}

function keyOf(userId: string, lessonId: string): string {
  return `${userId}/${lessonId}`;
}

/** Progress rows with an injected clock. Completion bypasses the position throttle and keeps the first completion time. */
export function createInMemoryProgress(clock: TestClock = createTestClock(), uow: InMemoryUnitOfWork = createInMemoryUnitOfWork()): ProgressBench {
  let rows = new Map<string, StoredProgress>();
  let closed = false;
  const participant = {
    snapshot: () => structuredClone(rows),
    restore(snapshot: Map<string, StoredProgress>) { rows = snapshot; },
  };
  uow.register(participant);

  function assertTx(tx: Queryable): asserts tx is UnitOfWork {
    if (!uow.owns(tx as UnitOfWork)) throw new Error("Transaction is not the in-memory unit of work.");
  }

  const port: ProgressRepositoryPort = {
    read(userId) {
      return Promise.resolve([...rows.values()].filter((row) => row.userId === userId).map((row) => ({
        lessonId: row.lessonId, courseId: row.courseId, positionSeconds: row.positionSeconds, durationSeconds: row.durationSeconds,
        completed: row.completed, updatedAt: row.updatedAt,
      })));
    },
    save(input: ProgressWrite) {
      const id = keyOf(input.userId, input.lessonId);
      const current = rows.get(id);
      const now = clock.now();
      if (input.completed === undefined) {
        if (input.positionSeconds === undefined) return Promise.reject(new Error("A progress write needs a position or a completion."));
        if (current && now - current.updatedAt < PROGRESS_THROTTLE_SECONDS * 1000) return Promise.resolve(false);
        rows.set(id, {
          userId: input.userId, courseId: input.courseId, lessonId: input.lessonId, positionSeconds: input.positionSeconds,
          durationSeconds: input.durationSeconds, completed: current?.completed ?? false, completedAt: current?.completedAt ?? null, updatedAt: now,
        });
        return Promise.resolve(true);
      }
      const completedAt = input.completed ? current?.completedAt ?? now : null;
      rows.set(id, {
        userId: input.userId, courseId: input.courseId, lessonId: input.lessonId,
        positionSeconds: input.positionSeconds ?? current?.positionSeconds ?? 0, durationSeconds: input.durationSeconds,
        completed: input.completed, completedAt, updatedAt: now,
      });
      return Promise.resolve(true);
    },
  };

  function maintenanceIn(tx: UnitOfWork): ProgressMaintenancePort {
    assertTx(tx);
    return {
      countForLessons(lessonIds) {
        assertTx(tx);
        if (lessonIds.length === 0) return Promise.resolve(0);
        const known = new Set(lessonIds);
        return Promise.resolve([...rows.values()].filter((row) => known.has(row.lessonId)).length);
      },
      orphanedLessons(knownLessonIds) {
        assertTx(tx);
        const known = new Set(knownLessonIds);
        const orphans = [...rows.values()].filter((row) => !known.has(row.lessonId));
        const sample = [...new Set(orphans.map((row) => row.lessonId))].sort();
        return Promise.resolve({ count: orphans.length, sample: sample.slice(0, 10) });
      },
    };
  }

  return {
    port, maintenanceIn, clock,
    completedAt(userId, lessonId) { return Promise.resolve(rows.get(`${userId}/${lessonId}`)?.completedAt ?? null); },
    reset() {
      if (closed) throw new Error("The in-memory progress store is closed.");
      rows = new Map();
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    transaction(work) {
      if (closed) return Promise.reject(new Error("The in-memory progress store is closed."));
      return uow.run(work);
    },
  };
}
