/** Runs a task when a slot is free. */
export type ConcurrencyLimit = <T>(task: () => Promise<T>) => Promise<T>;

/** At most `max` tasks run at once. The count increments before the first await, so one thread cannot overshoot. */
export function limitConcurrency(max: number): ConcurrencyLimit {
  if (!Number.isInteger(max) || max < 1) throw new Error("concurrency limit must be a positive integer");
  let active = 0;
  const waiting: Array<() => void> = [];
  return function occupy<T>(task: () => Promise<T>): Promise<T> {
    const run = (): Promise<T> => {
      active += 1;
      let pending: Promise<T>;
      try {
        pending = task();
      } catch (error) {
        active -= 1;
        waiting.shift()?.();
        return Promise.reject(error instanceof Error ? error : new Error("concurrency task failed"));
      }
      return pending.finally(() => {
        active -= 1;
        waiting.shift()?.();
      });
    };
    if (active < max) return run();
    return new Promise<T>((resolve, reject) => {
      waiting.push(() => { run().then(resolve, reject); });
    });
  };
}
