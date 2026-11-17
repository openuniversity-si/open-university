import { z } from "zod";
import { canonicalJson, sha256Hex } from "../../kernel/canonical.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { catalogBatchV2Schema, type CatalogBatchV2 } from "./schema/batch-v2.ts";
import { EXTENT } from "../../kernel/extent.ts";

// Transport of a CatalogBatchV2 (S08): content identity, chunks ≤ maxBytes and their reassembly. Chunking is transport
// only (CONTRACT §5); the batch is open until every chunk arrives. The collections are every array key of the schema
// (D-035), so a new array cannot be dropped from the hash or the chunks.

interface ZodStep { readonly def: { readonly type?: string; readonly innerType?: ZodStep; readonly schema?: ZodStep; readonly in?: ZodStep } }

function isArraySchema(schema: z.ZodType): boolean {
  let current: ZodStep | undefined = schema;
  for (let depth = 0; depth < 8 && current; depth += 1) {
    if (current.def.type === "array") return true;
    current = current.def.innerType ?? current.def.schema ?? current.def.in;
  }
  return false;
}

/** Array keys of CatalogBatchV2, in schema order. `courses` is last and is the only key that is split across parts. */
export function batchCollectionKeys(schema: z.ZodType = catalogBatchV2Schema): readonly string[] {
  const shape = (schema as z.ZodObject).shape as Readonly<Record<string, z.ZodType>>;
  return Object.entries(shape).filter(([, value]) => isArraySchema(value)).map(([key]) => key);
}

type Part = { version?: number; updateRefs?: boolean; courses?: unknown[] } & Record<string, unknown>;

const keyOf = (item: unknown) => {
  const value = item as { id?: string; code?: string; course?: { id?: string } };
  return value.course?.id ?? value.id ?? value.code ?? "";
};

function collection(batch: CatalogBatchV2, name: string): readonly unknown[] {
  const value = batch[name as keyof CatalogBatchV2];
  return Array.isArray(value) ? value : [];
}

/** Identity of a batch: every collection in id order, so chunk and item order do not matter. */
export function batchV2Hash(batch: CatalogBatchV2): string {
  const sorted: Record<string, unknown> = { version: batch.version, updateRefs: batch.updateRefs };
  for (const name of batchCollectionKeys()) sorted[name] = [...collection(batch, name)].sort((a, b) => (keyOf(a) < keyOf(b) ? -1 : keyOf(a) > keyOf(b) ? 1 : 0));
  return sha256Hex(canonicalJson(sorted));
}

/** Parts of at most maxBytes each: the references travel in the first part, courses fill the rest in order. */
export function chunkBatchV2(batch: CatalogBatchV2, maxBytes: number): Part[] {
  const head: Part = { version: 2, updateRefs: batch.updateRefs };
  for (const name of batchCollectionKeys()) if (name !== "courses") head[name] = [...collection(batch, name)];
  const parts: Part[] = [];
  let current: Part = { ...head, courses: [] };
  for (const course of batch.courses) {
    const next = { ...current, courses: [...(current.courses ?? []), course] };
    if ((current.courses ?? []).length > 0 && new TextEncoder().encode(JSON.stringify(next)).byteLength > maxBytes) {
      parts.push(current);
      current = { courses: [course] };
    } else {
      current = next;
    }
  }
  parts.push(current);
  return parts;
}

/** The parts back into one unparsed batch document (validated by catalogBatchV2Schema afterwards). */
export function mergeBatchParts(parts: readonly unknown[]): Record<string, unknown> {
  const first = (parts[0] ?? {}) as Part;
  const merged: Record<string, unknown> = { version: first.version, updateRefs: first.updateRefs ?? false };
  for (const name of batchCollectionKeys()) merged[name] = parts.flatMap((part) => ((part as Part)[name] ?? []));
  return merged;
}

/** POST /batches/apply: one part of a CatalogBatchV2. `dryRun` is not an option of the batch: a dry run and its write share it. */
export const applyBatchBody = z.strictObject({
  batchHash: z.string().regex(/^[a-f0-9]{64}$/),
  chunk: z.number().int().nonnegative(),
  chunks: z.number().int().min(EXTENT.one).max(LIMITS.shipChunkCount),
  dryRun: z.boolean().default(false),
  draft: z.boolean().default(false),
  allowOrphan: z.boolean().optional(),
  note: z.string().trim().min(EXTENT.one).max(LIMITS.note).optional(),
  part: z.record(z.string(), z.unknown()),
}).refine((body) => body.chunk < body.chunks, { message: "chunk must be less than chunks." });
export type ApplyBatchBody = z.output<typeof applyBatchBody>;

export interface ApplyBatchReport {
  readonly status: "committed" | "dry-run";
  readonly batchHash: string;
  readonly draft: boolean;
  /** Operations by step and action, in the core's order (G-4). */
  readonly plan: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly courses: readonly string[];
  readonly release: { readonly number: number; readonly created: boolean } | null;
}
export type ApplyBatchData = ApplyBatchReport | { readonly status: "partial"; readonly batchHash: string; readonly received: number; readonly chunks: number };
