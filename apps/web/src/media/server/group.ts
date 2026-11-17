import { logStructured } from "../../platform/observability/logger.ts";
import type { MediaAsset } from "../domain/types.ts";

/**
 * Dynamic pages (course, player) keep rendering with placeholders when the media read fails on a cache miss; the
 * catalog has its own fallback (ADR-17). The ISR Home does not use this: a failed render keeps its last good page.
 */
export async function mediaOrPlaceholders(read: Promise<ReadonlyMap<string, readonly MediaAsset[]>>): Promise<ReadonlyMap<string, readonly MediaAsset[]>> {
  try {
    return await read;
  } catch {
    logStructured("error", "MEDIA_READ_FAILED");
    return new Map();
  }
}
