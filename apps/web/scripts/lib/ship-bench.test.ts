import { describe, expect, it } from "vitest";
import { writeMedia, writeRefs } from "../../src/catalog/server/batch-apply.ts";
import type { BatchPlan } from "../../src/catalog/domain/batch-plan.ts";
import { catalogBatchV2Schema, type CatalogBatchV2 } from "../../src/catalog/domain/schema/batch-v2.ts";
import { ccByLicense } from "../../src/catalog/domain/schema/fields.ts";
import type { Tx } from "../../src/catalog/server/mutation.ts";

// Verifies: D-035
const sha = (seed: string) => seed.repeat(64).slice(0, 64);

function batch(): CatalogBatchV2 {
  const poster = sha("a");
  return catalogBatchV2Schema.parse({
    version: 2,
    sources: [1, 2, 3].map((n) => ({ id: `src-${String(n)}`, kind: "institution-site", title: `Source ${String(n)}`, url: `https://example.org/${String(n)}` })),
    licenses: [ccByLicense, { ...ccByLicense, code: "cc-by-sa", name: "CC BY-SA 3.0" }],
    institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster } }],
    lecturers: [1, 2, 3, 4].map((n) => ({ id: `lecturer-${String(n)}`, slug: `lecturer-${String(n)}`, name: `Lecturer ${String(n)}`, monogram: "L", kind: "person" })),
    areas: [{ id: "physics", title: "Physics", cover: { poster, heroDesktop: sha("b"), heroPresent: sha("c"), heroMobile: sha("d") } }],
    subareas: [{ id: "mechanics", areaId: "physics", title: "Mechanics" }],
    courses: [{
      institutionId: "usp",
      course: { id: "course-1", slug: "mechanics", title: "Mechanics", authorId: "lecturer-1", coverFrom: "own", sharedWith: [] },
      editions: [{ id: "edition-1", slug: "2021", label: "2021", position: 1, year: 2021 }],
      lessons: [{ id: "lesson-1", editionId: "edition-1", slug: "aula-1", title: "Aula 1", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
      covers: [{ kind: "poster_9x16", sha: poster }, { kind: "hero_desktop_16x9", sha: sha("b") }, { kind: "still_16x9", sha: sha("e") }],
    }],
  });
}

function planFor(value: CatalogBatchV2): BatchPlan {
  const op = (step: BatchPlan["ops"][number]["step"], id: string) => ({ step, action: "create" as const, id });
  return {
    failures: [],
    ops: [
      ...value.sources.map((source) => op("source", source.id)),
      ...value.licenses.map((license) => op("license", license.code)),
      ...value.institutions.map((item) => op("institution", item.id)),
      ...value.lecturers.map((item) => op("lecturer", item.id)),
      ...value.areas.map((item) => op("area", item.id)),
      ...value.subareas.map((item) => op("subarea", item.id)),
    ],
  };
}

function recorder(): { tx: Tx; sql: string[] } {
  const sql: string[] = [];
  const tx = {
    query: (text: string, values?: unknown[]) => {
      sql.push(text);
      if (text.includes("FROM media_objects")) {
        const hashes = values?.[0] as string[];
        return Promise.resolve({ rows: hashes.map((hash) => ({ sha256: hash, ext: "jpg", contentType: "image/jpeg", bytes: 120, width: 540, height: 960 })) });
      }
      return Promise.resolve({ rows: [] });
    },
  } as unknown as Tx;
  return { tx, sql };
}

const tableInserts = (sql: readonly string[], table: string) => sql.filter((text) => text.includes(`INSERT INTO ${table}`) && text.includes("jsonb_to_recordset"));

describe("bulk ship writes", () => {
  it("D-035: a bulk ship writes set-based statements", async () => {
    const value = batch();
    const recorded = recorder();
    await writeRefs(recorded.tx, value, planFor(value));
    await writeMedia(recorded.tx, value);
    expect(tableInserts(recorded.sql, "content_sources")).toHaveLength(1);
    expect(tableInserts(recorded.sql, "authors")).toHaveLength(1);
    expect(tableInserts(recorded.sql, "licenses")).toHaveLength(1);
    expect(tableInserts(recorded.sql, "subject_areas")).toHaveLength(1);
    expect(tableInserts(recorded.sql, "subject_subareas")).toHaveLength(1);
    expect(recorded.sql.filter((text) => text.includes("UPDATE catalog_media"))).toHaveLength(1);
    expect(tableInserts(recorded.sql, "catalog_media")).toHaveLength(1);
    expect(recorded.sql.filter((text) => text.includes("UPDATE media_objects SET orphaned_at = NULL"))).toHaveLength(1);
    expect(recorded.sql.some((text) => text.includes("pg_advisory"))).toBe(false);
    const covers = 1 + 4 + 3;
    expect(covers).toBeGreaterThan(1);
    expect(recorded.sql.filter((text) => text.includes("INSERT INTO catalog_media"))).toHaveLength(1);

    const again = recorder();
    await writeRefs(again.tx, value, { failures: [], ops: planFor(value).ops.map((op) => ({ ...op, action: "noop" as const })) });
    expect(again.sql).toEqual([]);
  });
});
