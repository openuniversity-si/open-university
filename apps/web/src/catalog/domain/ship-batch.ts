import { z } from "zod";
import { canonicalJson, sha256Hex } from "../../kernel/canonical.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { bundleHash, type CourseBundleV1 } from "./bundle.ts";
import { EXTENT } from "../../kernel/extent.ts";

/** Identity of a whole ship: the sorted per-bundle hashes, so chunk order does not matter. */
export function batchContentHash(bundles: readonly CourseBundleV1[]): string {
  return sha256Hex(canonicalJson(bundles.map((bundle) => bundleHash(bundle)).sort()));
}

/**
 * Split a batch so each JSON array of bundles stays within `maxBytes`.
 * A single bundle larger than the limit is its own chunk; the server rejects it.
 */
export function chunkBundles(bundles: readonly CourseBundleV1[], maxBytes: number): CourseBundleV1[][] {
  const chunks: CourseBundleV1[][] = [];
  let current: CourseBundleV1[] = [];
  let size = 2;
  for (const bundle of bundles) {
    const bytes = new TextEncoder().encode(JSON.stringify(bundle)).byteLength;
    const next = size + (current.length > 0 ? 1 : 0) + bytes;
    if (current.length > 0 && next > maxBytes) {
      chunks.push(current);
      current = [bundle];
      size = 2 + bytes;
    } else {
      current.push(bundle);
      size = next;
    }
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

export const shipBatchBody = z.strictObject({
  batchHash: z.string().regex(/^[a-f0-9]{64}$/),
  chunk: z.number().int().nonnegative(),
  chunks: z.number().int().min(EXTENT.one).max(LIMITS.shipChunkCount),
  draft: z.boolean(),
  allowOrphan: z.boolean().optional(),
  note: z.string().trim().min(EXTENT.one).max(LIMITS.note).optional(),
  bundles: z.array(z.unknown()).min(EXTENT.one).max(LIMITS.shipBundleCount),
}).refine((body) => body.chunk < body.chunks, { message: "chunk must be less than chunks." });

export type ShipBatchBody = z.infer<typeof shipBatchBody>;

export interface ShipBatchRelease {
  readonly number: number;
  readonly sha: string;
  readonly created: boolean;
  readonly previous: number | null;
}

export interface ShipBatchPhases {
  readonly validateMs: number;
  readonly writeMs: number;
  readonly releaseMs: number;
  readonly totalMs: number;
}

export interface ShipBatchCommitted {
  readonly status: "committed";
  readonly batchHash: string;
  readonly draft: boolean;
  readonly courses: readonly string[];
  readonly release: ShipBatchRelease | null;
  readonly phases: ShipBatchPhases;
}

export interface ShipBatchPartial {
  readonly status: "partial";
  readonly batchHash: string;
  readonly received: number;
  readonly chunks: number;
}

export type ShipBatchData = ShipBatchCommitted | ShipBatchPartial;
