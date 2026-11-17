import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { catalogContract, type CatalogBench } from "../../src/catalog/testing/catalog-contract.ts";
import { emptyCatalogFixture, readyCatalogFixture, type CatalogFixture } from "../../src/catalog/testing/catalog-fixture.ts";
import { readCatalogTables } from "../../src/catalog/server/table-io.ts";
import { catalogCourseState } from "../../src/catalog/server/courses.ts";
import { catalogOwners } from "../../src/catalog/server/media-owners.ts";
import { createTransition } from "../../src/catalog/domain/transition.ts";
import { executeContract } from "../../src/platform/db/testing/uow-contract.ts";
import { withUnitOfWork, type DbPool, type UnitOfWork } from "../../src/platform/db/uow.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";
import { resetCatalogTables } from "../fixtures/catalog-reset.ts";

// Integration-only cases, proved here or by the existing database suites:
// uow.lock.exclusion, media.object.remote, progress.clock.sql, media.image.bytes.
// Memory does not emulate SQL, remote buckets, the database clock or image decoding.

const jsonb = new Set(["cover", "legacy"]);

describe("executable contracts on the database", () => {
  let pool: pg.Pool;
  let harness: CatalogBench;

  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required; no database mocks.");
    validateDatabaseUrl(connectionString, "container");
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    pool = new pg.Pool({ connectionString });
    harness = databaseHarness(pool);
  });

  afterAll(async () => { await pool.end(); });

  it("runs the shared catalog cases on the database adapter", async () => {
    await executeContract(catalogContract(), harness);
  });

  it("uow.lock.exclusion", async () => {
    const db = pool as unknown as DbPool;
    await withUnitOfWork(db, async (tx) => {
      await tx.acquireLock({ scope: "xact", key: "contract:probe" });
      const other = await pool.connect();
      try {
        await other.query("BEGIN");
        await other.query("SET LOCAL lock_timeout = '200ms'");
        await expect(other.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", ["contract:probe"])).rejects.toMatchObject({ code: "55P03" });
        await other.query("ROLLBACK");
      } finally { other.release(); }
    });
  });
});

function databaseHarness(pool: pg.Pool): CatalogBench {
  const db = pool as unknown as DbPool;
  let pending: string | null = null;
  let ran = false;
  return {
    port: {
      transition(change, options) {
        return withUnitOfWork(db, async (tx) => {
          const result = await createTransition(change, options, {
            state: catalogCourseState(tx),
            audit: async (entry) => {
              await tx.query(`INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, before, after)
                VALUES ('contract', 'contract', $1, $2, $3, $4::jsonb, $5::jsonb)`, [
                entry.action, entry.entityKind, entry.entityId,
                entry.before === undefined ? null : JSON.stringify(entry.before),
                entry.after === undefined ? null : JSON.stringify(entry.after),
              ]);
            },
          });
          if (pending) {
            const message = pending;
            pending = null;
            tx.onAfterCommit(() => { ran = true; throw new Error(message); });
          }
          return result;
        });
      },
    },
    ownersIn(tx) { return catalogOwners(tx); },
    lessons: {
      async resolvePublishedLesson(courseSlug, lessonSlug) {
        const { rows } = await pool.query<{ course_id: string; lesson_id: string; duration_seconds: number }>("SELECT c.id AS course_id, l.id AS lesson_id, l.duration_seconds FROM courses c JOIN lessons l ON l.course_id = c.id WHERE c.slug = $1 AND c.status = 'published' AND l.slug = $2 AND l.visible", [courseSlug, lessonSlug]);
        const row = rows[0];
        return row ? { courseId: row.course_id, lessonId: row.lesson_id, durationSeconds: row.duration_seconds } : null;
      },
    },
    async reset() { pending = null; ran = false; await clearFixture(pool); },
    dispose() { return Promise.resolve(); },
    async seed(kind) {
      await clearFixture(pool);
      await insertFixture(pool, kind === "ready" ? readyCatalogFixture() : emptyCatalogFixture());
      return { courseId: kind === "ready" ? "course-ready" : "course-empty", revision: 1 };
    },
    async course(courseId) {
      const { rows } = await pool.query<{ status: string; revision: number }>("SELECT status, revision FROM courses WHERE id = $1", [courseId]);
      const row = rows[0];
      if (!row) throw new Error(`Course ${courseId} is missing.`);
      return { status: row.status, revision: row.revision };
    },
    async journalCount(courseId) {
      const { rows } = await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_audit WHERE entity_id = $1 AND action = 'course.status'", [courseId]);
      return rows[0]?.n ?? 0;
    },
    async tables() { return readCatalogTables(pool); },
    failNextEffect(message) { ran = false; pending = message; },
    effectRan: () => ran,
    transaction<T>(work: (tx: UnitOfWork) => Promise<T>) { return withUnitOfWork(db, work); },
  };
}

async function clearFixture(pool: pg.Pool): Promise<void> {
  await pool.query("DELETE FROM catalog_media WHERE owner_kind = 'course' AND owner_id IN ('course-ready', 'course-live', 'course-empty')");
  await pool.query("DELETE FROM catalog_texts WHERE entity_id IN ('course-ready', 'course-live', 'course-empty', 'lesson-ready', 'lesson-live')");
  await pool.query("DELETE FROM lesson_videos WHERE lesson_id IN ('lesson-ready', 'lesson-live')");
  await pool.query("DELETE FROM lessons WHERE id IN ('lesson-ready', 'lesson-live')");
  await pool.query("DELETE FROM course_editions WHERE id IN ('edition-ready', 'edition-live')");
  await pool.query("DELETE FROM catalog_audit WHERE entity_id IN ('course-ready', 'course-live', 'course-empty')");
  await pool.query("DELETE FROM courses WHERE id IN ('course-ready', 'course-live', 'course-empty')");
  await pool.query("DELETE FROM authors WHERE id = 'author-a'");
  await pool.query("DELETE FROM content_sources WHERE id = 'source-a'");
  await pool.query("DELETE FROM licenses WHERE code = 'cc-by'");
}

async function insertFixture(pool: pg.Pool, fixture: CatalogFixture): Promise<void> {
  const tables = fixture.tables;
  await insertRows(pool, "licenses", tables.licenses);
  await insertRows(pool, "content_sources", tables.content_sources);
  for (const area of tables.subject_areas) await pool.query("INSERT INTO subject_areas (id, title, position) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING", [area.id, area.title, area.position]);
  await insertRows(pool, "authors", tables.authors);
  await insertRows(pool, "courses", tables.courses);
  await insertRows(pool, "course_editions", tables.course_editions);
  await insertRows(pool, "lessons", tables.lessons);
  await insertRows(pool, "lesson_videos", tables.lesson_videos);
  await insertRows(pool, "catalog_texts", tables.catalog_texts);
  const sha = "a".repeat(64);
  for (const [courseId, kinds] of Object.entries(fixture.covers)) {
    for (const kind of kinds) {
      await pool.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, url, pathname, width, height, sha256, alt, design_status, version, is_active)
        VALUES ($1, 'course', $2, $3, 'default', $4, $5, 16, 9, $6, 'Cover', 'approved', 1, true)`, [
        `${courseId}-${kind}`, courseId, kind, `https://media.test/m/${sha}.jpg`, `m/${sha}.jpg`, sha,
      ]);
    }
  }
}

async function insertRows(pool: pg.Pool, table: string, rows: readonly object[]): Promise<void> {
  for (const row of rows) {
    const record = row as Record<string, unknown>;
    const keys = Object.keys(record).filter((key) => record[key] !== undefined);
    if (keys.length === 0) continue;
    const values = keys.map((key) => jsonb.has(key) && record[key] !== null ? JSON.stringify(record[key]) : record[key]);
    const params = keys.map((key, index) => jsonb.has(key) && record[key] !== null ? `$${String(index + 1)}::jsonb` : `$${String(index + 1)}`);
    await pool.query(`INSERT INTO "${table}" (${keys.map((key) => `"${key}"`).join(", ")}) VALUES (${params.join(", ")})`, values);
  }
}
