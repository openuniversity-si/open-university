import pg from "pg";
import { performance } from "node:perf_hooks";
import { writeCourses, writeMedia, writeRefs } from "../src/catalog/server/batch-apply.ts";
import type { BatchPlan, BatchRefs } from "../src/catalog/domain/batch-plan.ts";
import type { CatalogBatchV2 } from "../src/catalog/domain/schema/batch-v2.ts";
import { ccByLicense } from "../src/catalog/domain/schema/fields.ts";
import type { Tx } from "../src/catalog/server/mutation.ts";
import { runMigrations } from "./lib/migrations.ts";

// D-035. Times the ship writes for a rehearsal-sized batch and rolls them back.
// Run from apps/web: source ../../scripts/cloud/env.sh && pnpm exec tsx scripts/ship-bench.ts

const COURSES = 1117;
const LECTURERS = 282;
const COURSE_COVERS = 283;
const SHA = "ab".repeat(32);

function batch(): CatalogBatchV2 {
  const lecturers = Array.from({ length: LECTURERS }, (_, index) => {
    const n = String(index);
    return { id: `bench-l-${n}`, slug: `bench-l-${n}`, name: `Lecturer ${n}`, monogram: "L", kind: "person" as const };
  });
  return {
    version: 2,
    updateRefs: false,
    sources: [{ id: "bench-src", kind: "institution-site", title: "Bench", url: "https://example.org/bench" }],
    licenses: [ccByLicense],
    institutions: [{ id: "bench-inst", slug: "bench-inst", name: "Bench University", monogram: "BU", kind: "institution", cover: { poster: SHA } }],
    lecturers,
    areas: [],
    subareas: [],
    homeRows: [],
    courses: Array.from({ length: COURSES }, (_, index) => {
      const n = String(index);
      const id = `bench-c-${n}`;
      return {
        institutionId: "bench-inst",
        course: { id, slug: id, title: `Course ${n}`, authorId: lecturers[index % LECTURERS]?.id ?? "bench-l-0", lessonNoun: "Lecture", coverFrom: "own", sharedWith: [] },
        editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }],
        lessons: [{ id: `${id}-l`, editionId: `${id}-e`, slug: "intro", title: "Intro", position: 1, youtubeId: `b${n.padStart(10, "0")}`, durationSeconds: 60, part: "lectures" }],
        texts: [],
        covers: index < COURSE_COVERS ? [{ kind: "poster_9x16" as const, sha: SHA }] : [],
        homeRowId: null,
      };
    }),
  };
}

function plan(value: CatalogBatchV2): BatchPlan {
  const op = (step: BatchPlan["ops"][number]["step"], id: string) => ({ step, action: "create" as const, id });
  return {
    failures: [],
    ops: [
      ...value.sources.map((source) => op("source", source.id)),
      ...value.licenses.map((license) => op("license", license.code)),
      ...value.institutions.map((item) => op("institution", item.id)),
      ...value.lecturers.map((item) => op("lecturer", item.id)),
    ],
  };
}

const emptyRefs: BatchRefs = {
  sources: new Map(), authors: new Map(), areas: new Map(), subareas: new Map(), homeRows: new Map(),
  courses: new Map(), licenses: new Set(), covers: new Map(), media: new Set(),
};

async function main(): Promise<void> {
  const url = process.env.TEST_DATABASE_URL;
  if (!url) throw new Error("TEST_DATABASE_URL is required.");
  await runMigrations(url, false);
  const client = new pg.Client({ connectionString: url, statement_timeout: 180_000 });
  await client.connect();
  const tx = { query: (sql: string, values?: unknown[]) => client.query(sql, values) } as unknown as Tx;
  const value = batch();
  const attaches = 1 + value.courses.filter((course) => course.covers.length > 0).length;
  try {
    await client.query("BEGIN");
    await client.query(`INSERT INTO media_objects (sha256, ext, content_type, bytes, width, height)
      VALUES ($1, 'jpg', 'image/jpeg', 120, 540, 960) ON CONFLICT (sha256) DO NOTHING`, [SHA]);
    const start = performance.now();
    await writeRefs(tx, value, plan(value));
    await writeMedia(tx, value);
    await writeCourses(tx, value, emptyRefs, "2026-10-23T00:00:00.000Z");
    const milliseconds = Math.round(performance.now() - start);
    await client.query("ROLLBACK");
    console.log(`ship-bench courses=${String(COURSES)} lecturers=${String(LECTURERS)} attaches=${String(attaches)} milliseconds=${String(milliseconds)}`);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    await client.end();
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "ship-bench failed");
  process.exitCode = 1;
});
