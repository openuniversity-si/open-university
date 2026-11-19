import { describe, expect, it } from "vitest";
import { z } from "zod";
import { batchCollectionKeys, batchV2Hash, chunkBatchV2, mergeBatchParts } from "./batch-v2.ts";
import { catalogBatchV2Schema, type CatalogBatchV2 } from "./schema/batch-v2.ts";

// Verifies: D-035
interface ZodStep { readonly def: { readonly type?: string; readonly innerType?: ZodStep; readonly schema?: ZodStep; readonly in?: ZodStep } }
function arrayKeys(schema: z.ZodObject): string[] {
  const isArray = (value: z.ZodType) => {
    let current: ZodStep | undefined = value;
    for (let depth = 0; depth < 8 && current; depth += 1) {
      if (current.def.type === "array") return true;
      current = current.def.innerType ?? current.def.schema ?? current.def.in;
    }
    return false;
  };
  const shape = schema.shape as Readonly<Record<string, z.ZodType>>;
  return Object.entries(shape).filter(([, value]) => isArray(value)).map(([key]) => key);
}

const sha = "a".repeat(64);
const course = (id: string) => ({
  institutionId: "usp", course: { id, slug: id, title: `Course ${id} ${"x".repeat(200).slice(0, 150)}`, authorId: "ana", coverFrom: "own", sharedWith: [] },
  editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }], covers: [{ kind: "poster_9x16", sha }],
});
const batch = catalogBatchV2Schema.parse({
  version: 2,
  institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster: sha } }],
  lecturers: [{ id: "ana", slug: "ana", name: "Ana", monogram: "A", kind: "person" }],
  courses: Array.from({ length: 30 }, (_, index) => course(`c${String(index).padStart(2, "0")}`)),
});

describe("CatalogBatchV2 transport (S08)", () => {
  it("chunks stay under the limit, carry the references first and merge back to the same batch and hash", () => {
    const parts = chunkBatchV2(batch, 4000);
    expect(parts.length).toBeGreaterThan(2);
    for (const part of parts) expect(new TextEncoder().encode(JSON.stringify(part)).byteLength).toBeLessThanOrEqual(4000);
    expect(parts[0]?.institutions).toHaveLength(1);
    expect(parts[1]?.institutions).toBeUndefined();
    const merged = catalogBatchV2Schema.parse(mergeBatchParts(parts));
    expect(batchV2Hash(merged)).toBe(batchV2Hash(batch));
  });

  it("D-035: chunk and hash keep every schema array key", () => {
    const license = { code: "cc-by", name: "CC BY 3.0", url: "https://creativecommons.org/licenses/by/3.0/", requiresAttribution: true, embedOnly: true };
    const withLicense = catalogBatchV2Schema.parse({ ...batch, licenses: [license, { code: "cc-by-sa", name: "CC BY-SA", requiresAttribution: true, shareAlike: true }] });
    const keys = arrayKeys(catalogBatchV2Schema);
    expect(keys).toContain("licenses");
    expect([...batchCollectionKeys()]).toEqual(keys);
    const reversed = catalogBatchV2Schema.parse({ ...withLicense, licenses: [...withLicense.licenses].reverse() });
    expect(batchV2Hash(reversed)).toBe(batchV2Hash(withLicense));
    const parts = chunkBatchV2(withLicense, 8000);
    const merged = catalogBatchV2Schema.parse(mergeBatchParts(parts));
    expect(merged.licenses.map((item) => item.code)).toEqual(["cc-by", "cc-by-sa"]);
    for (const key of keys) {
      expect(merged[key as keyof CatalogBatchV2]).toEqual(withLicense[key as keyof CatalogBatchV2]);
    }
    expect(batchV2Hash(merged)).toBe(batchV2Hash(withLicense));
    expect(batchV2Hash(catalogBatchV2Schema.parse({ ...withLicense, licenses: [] }))).not.toBe(batchV2Hash(withLicense));
  });

  it("G-2 identity: the hash ignores item order but not content", () => {
    const reversed = catalogBatchV2Schema.parse({ ...batch, courses: [...batch.courses].reverse() });
    expect(batchV2Hash(reversed)).toBe(batchV2Hash(batch));
    const renamed = catalogBatchV2Schema.parse({ ...batch, lecturers: [{ id: "ana", slug: "ana", name: "Ana Lima", monogram: "A", kind: "person" }] });
    expect(batchV2Hash(renamed)).not.toBe(batchV2Hash(batch));
  });
});
