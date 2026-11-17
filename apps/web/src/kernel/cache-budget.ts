import { CACHE } from "./cache.ts";
import { AppError } from "./errors.ts";

/** Next.js refuses a Data Cache entry over 2 MB. Public reads stay under this, with room to spare (D-037). */
export const CACHE_ENTRY_BUDGET_BYTES = CACHE.entryBudgetBytes;

/** First slice a chunked read tries. A slice that does not fit is halved. */
export const CACHE_CHUNK_ITEMS = CACHE.chunkItems;

/** Thrown inside an `unstable_cache` callback so the oversized value is not stored. */
export class CacheEntryOverBudget extends AppError {
  readonly bytes: number;
  constructor(bytes: number) {
    super("payload_too_large", `unstable_cache entry is ${String(bytes)} bytes, over ${String(CACHE_ENTRY_BUDGET_BYTES)}.`);
    this.name = "CacheEntryOverBudget";
    this.bytes = bytes;
  }
}

export function jsonBytes(value: unknown): number {
  return Buffer.byteLength(JSON.stringify(value), "utf8");
}

export function assertCacheEntry(value: unknown): void {
  const bytes = jsonBytes(value);
  if (bytes > CACHE_ENTRY_BUDGET_BYTES) throw new CacheEntryOverBudget(bytes);
}

/**
 * Loads `items` in slices. The loader throws `CacheEntryOverBudget` when a slice cannot be one cache entry;
 * this halves that slice and retries. A single item that does not fit still throws.
 */
export async function loadWithinBudget<T, R>(items: readonly T[], load: (slice: readonly T[]) => Promise<R>, size: number = CACHE_CHUNK_ITEMS): Promise<R[]> {
  const loaded: R[] = [];
  let index = 0;
  let width = Math.max(1, size);
  while (index < items.length) {
    const slice = items.slice(index, index + width);
    try {
      loaded.push(await load(slice));
      index += slice.length;
      width = Math.max(1, size);
    } catch (error) {
      if (!(error instanceof CacheEntryOverBudget)) throw error;
      if (slice.length <= 1) throw error;
      width = Math.max(1, Math.floor(slice.length / 2));
    }
  }
  return loaded;
}
