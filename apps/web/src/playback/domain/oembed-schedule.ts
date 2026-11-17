import { CACHE } from "../../kernel/cache.ts";

/** A metadata result is fresh only inside the last 24 hours. A future timestamp is not fresh. */
export const OEMBED_FRESH_MS = CACHE.oembedFreshMs;
export const OEMBED_CONCURRENCY = 16;

export function metadataIsFresh(verifiedAt: string, now: Date): boolean {
  const then = Date.parse(verifiedAt);
  if (Number.isNaN(then)) return false;
  const age = now.getTime() - then;
  return age >= 0 && age < OEMBED_FRESH_MS;
}

export async function mapLimited<T>(items: readonly T[], limit: number, run: (item: T) => Promise<void>): Promise<void> {
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const item = items[cursor];
      cursor += 1;
      if (item === undefined) return;
      await run(item);
    }
  });
  await Promise.all(workers);
}
