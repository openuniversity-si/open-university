import { beforeAll, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => {
  const holder: {
    queries: string[];
    entries: { key: readonly string[]; bytes: number }[];
    rows: (sql: string, params: readonly unknown[] | undefined) => { rows: Record<string, unknown>[] };
  } = { queries: [], entries: [], rows: () => ({ rows: [] }) };
  return holder;
});

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }) }));
vi.mock("next/cache", () => ({
  unstable_cache: (fn: () => Promise<unknown>, key: readonly string[]) => async () => {
    const value = await fn();
    state.entries.push({ key, bytes: Buffer.byteLength(JSON.stringify(value), "utf8") });
    return value;
  },
}));
vi.mock("../../platform/db/pool.ts", () => ({
  appPool: () => ({
    query: (sql: string, params?: readonly unknown[]) => {
      state.queries.push(sql);
      return Promise.resolve(state.rows(sql, params));
    },
  }),
}));

import { sha256Hex } from "../../kernel/canonical.ts";
import { CACHE_ENTRY_BUDGET_BYTES } from "../../kernel/cache-budget.ts";
import { routeBudget } from "../../site/domain/site-health.ts";
import type { CompiledCourseProjection } from "../domain/incremental-compile.ts";
import { fullSizeRelease } from "../testing/full-release.ts";
import { readPageCatalog } from "./page-reads.ts";

// Verifies: D-037
const detailRead = (sql: string) => sql.includes("detail_json") && sql.includes("unnest") && !sql.includes("#>>");

describe("readPageCatalog batches projections (D-037)", () => {
  const byId = new Map<string, CompiledCourseProjection>();
  let manifest = "";

  beforeAll(() => {
    const catalog = fullSizeRelease();
    const pad = "x".repeat(700);
    manifest = "m".repeat(64);
    for (const course of catalog.courses) {
      const author = catalog.authors.find((entry) => entry.id === course.authorId);
      const lessons = catalog.lessons.filter((lesson) => lesson.courseId === course.id);
      if (!author || lessons.length === 0) throw new Error(course.id);
      const detailCourse = { ...course, billboardDescription: `${pad}${course.billboardDescription}`, description: `${pad}${course.description}` };
      byId.set(course.id, {
        courseId: course.id, sha256: sha256Hex(course.id), sourceRevision: 1, fingerprint: "fp",
        summary: { authorId: course.authorId, lessonIds: lessons.map((lesson) => lesson.id) },
        detail: { author, course: detailCourse, lessons },
      });
    }
    const projections = [...byId.values()];
    const document = {
      index: {
        formatVersion: 3, manifestSha256: manifest, globalFingerprint: "g",
        courses: projections.map((projection) => ({ courseId: projection.courseId, sha256: projection.sha256, fingerprint: projection.fingerprint, sourceRevision: projection.sourceRevision })),
        authors: catalog.authors.map((author) => ({ id: author.id, fingerprint: "a" })),
      },
      frame: { authors: catalog.authors, home: catalog.home, redirects: catalog.redirects, ...(catalog.areas ? { areas: catalog.areas } : {}) },
      publishedAt: catalog.publishedAt,
    };
    state.rows = (sql, params) => {
      if (sql.includes("WHERE is_active")) return { rows: [{ number: 133 }] };
      if (sql.includes("catalog_release_index")) return { rows: [{ manifest_sha256: manifest, index_json: document }] };
      if (sql.includes("#>> '{course,slug}'")) {
        const slugParam = params?.[2];
        const slug = typeof slugParam === "string" ? slugParam : "";
        const found = projections.find((projection) => projection.detail.course.slug === slug);
        return { rows: found ? [{ course_id: found.courseId, title: found.detail.course.title, lesson_ids: [...found.summary.lessonIds] }] : [] };
      }
      if (sql.includes("summary_json->>'authorId'")) {
        return { rows: projections.map((projection) => ({ course_id: projection.courseId, author_id: projection.summary.authorId })) };
      }
      if (detailRead(sql)) {
        const ids = params?.[0];
        const wanted = new Set(Array.isArray(ids) ? ids.map(String) : []);
        return { rows: projections.filter((projection) => wanted.has(projection.courseId)).map((projection) => ({
          course_id: projection.courseId, projection_sha256: projection.sha256, source_revision: projection.sourceRevision,
          summary_json: { ...projection.summary, fingerprint: projection.fingerprint }, detail_json: projection.detail,
        })) };
      }
      throw new Error(`unexpected sql: ${sql}`);
    };
  });

  it("reads a full release with one projection query and every cache entry under 1.5 MB", async () => {
    state.queries.length = 0;
    state.entries.length = 0;
    const catalog = await readPageCatalog({ kind: "release" });
    expect(catalog.courses).toHaveLength(2363);
    expect(state.queries.length).toBe(4);
    expect(state.queries.length).toBeLessThanOrEqual(routeBudget("/universities").queries);
    expect(state.queries.filter(detailRead)).toHaveLength(1);
    expect(state.queries.some((sql) => sql.includes("projection_sha256 = $2"))).toBe(false);
    const chunks = state.entries.filter((entry) => entry.key[0] === "catalog" && entry.key[1] === "projections");
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((entry) => entry.bytes <= CACHE_ENTRY_BUDGET_BYTES && entry.key[2] === "133" && entry.key[3] === manifest)).toBe(true);
  }, 30_000);

  it("resolves a course slug in one query, then batches that author's projections", async () => {
    state.queries.length = 0;
    state.entries.length = 0;
    const catalog = await readPageCatalog({ kind: "course", slug: "course-10" });
    expect(catalog.courses.some((course) => course.slug === "course-10")).toBe(true);
    expect(state.queries.length).toBe(7);
    expect(state.queries.length).toBeLessThanOrEqual(routeBudget("/c/[courseSlug]").queries);
    expect(state.queries.filter((sql) => sql.includes("#>> '{course,slug}'"))).toHaveLength(1);
    expect(state.queries.filter(detailRead)).toHaveLength(1);
    expect(catalog.courses.length).toBeLessThan(100);
  }, 30_000);
});
