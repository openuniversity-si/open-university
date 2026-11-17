import { assertR2Budget, DEFAULT_R2_BUDGET, type R2Budget } from "./r2-slot.ts";

export { assertR2Budget, DEFAULT_R2_BUDGET, physicalSlotsInFlight, setPhysicalSlotLimit, withPhysicalSlot, type R2Budget } from "./r2-slot.ts";
export { createS3Bucket, hasR2Credentials, r2Config, type R2Access, type S3Bucket, type S3Config, type StorageClock } from "./r2.ts";

/** Logical fan-out. It does not take a physical slot; the transport does, once per attempt. */
export async function mapLimited<T, R>(items: readonly T[], work: (item: T) => Promise<R>, budget: R2Budget = DEFAULT_R2_BUDGET): Promise<R[]> {
  assertR2Budget(budget);
  const output: R[] = new Array<R>(items.length);
  let next = 0;
  let failure: { error: unknown } | undefined;
  const worker = async () => {
    while (!failure && next < items.length) {
      const index = next;
      next += 1;
      const item = items[index];
      if (item === undefined) continue;
      try { output[index] = await work(item); } catch (error) { failure ??= { error }; }
    }
  };
  const workers = Math.min(budget.concurrency, items.length);
  await Promise.all(Array.from({ length: workers }, () => worker()));
  if (failure) throw failure.error;
  return output;
}
