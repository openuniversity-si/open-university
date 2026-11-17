import { LIMITS } from "../../kernel/limits.ts";
import { createR2MediaStore, type MediaObjectStore } from "./storage.ts";
import type { R2Budget } from "./r2-budget.ts";
import type { R2Access } from "./r2.ts";

type Env = Readonly<Record<string, string | undefined>>;

export { assertR2Budget, DEFAULT_R2_BUDGET, mapLimited, physicalSlotsInFlight, setPhysicalSlotLimit, withPhysicalSlot, type R2Budget } from "./r2-budget.ts";

/** Builds the store from explicit configuration. Migration DNS stays in the CLI adapter. */
export function createBulkR2Store(env: Env, access: R2Access): MediaObjectStore {
  return createR2MediaStore(env, access);
}

export function budgetForConcurrency(concurrency: number): R2Budget {
  return { concurrency, attempts: LIMITS.r2Attempts, attemptTimeoutMs: LIMITS.r2AttemptMs, totalTimeoutMs: LIMITS.r2TotalMs };
}
