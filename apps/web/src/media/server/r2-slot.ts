import { AppError } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";

/** Physical R2 pressure for this process. Logical fan-out does not take a slot. */
export interface R2Budget {
  readonly concurrency: number;
  readonly attempts: number;
  readonly attemptTimeoutMs: number;
  readonly totalTimeoutMs: number;
}

export const DEFAULT_R2_BUDGET: R2Budget = { concurrency: LIMITS.r2Concurrency, attempts: LIMITS.r2Attempts, attemptTimeoutMs: LIMITS.r2AttemptMs, totalTimeoutMs: LIMITS.r2TotalMs };

export function assertR2Budget(budget: R2Budget): void {
  const integer = (name: string, value: number, max: number) => {
    if (!Number.isInteger(value) || value < 1 || value > max) throw new AppError("invalid", `${name} must be an integer from 1 to ${String(max)}.`);
  };
  integer("concurrency", budget.concurrency, LIMITS.r2ConcurrencyCap);
  integer("attempts", budget.attempts, LIMITS.r2AttemptsCap);
  integer("attemptTimeoutMs", budget.attemptTimeoutMs, LIMITS.r2AttemptCapMs);
  integer("totalTimeoutMs", budget.totalTimeoutMs, LIMITS.r2TotalCapMs);
}

let slotLimit = DEFAULT_R2_BUDGET.concurrency;
let slotsInFlight = 0;
const slotWaiters: (() => void)[] = [];

export function setPhysicalSlotLimit(concurrency: number): void {
  assertR2Budget({ ...DEFAULT_R2_BUDGET, concurrency });
  slotLimit = concurrency;
}

export function physicalSlotsInFlight(): number {
  return slotsInFlight;
}

function acquirePhysicalSlot(): Promise<void> {
  if (slotsInFlight < slotLimit) {
    slotsInFlight += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => { slotWaiters.push(resolve); });
}

function releasePhysicalSlot(): void {
  const next = slotWaiters.shift();
  if (next) next();
  else slotsInFlight -= 1;
}

/** One physical attempt. The slot is released on success, failure and timeout. */
export async function withPhysicalSlot<T>(work: () => Promise<T>): Promise<T> {
  await acquirePhysicalSlot();
  try { return await work(); }
  finally { releasePhysicalSlot(); }
}
