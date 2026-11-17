import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { compileRelease } from "../domain/compile.ts";
import { TEXT_FIELDS } from "../domain/fields.ts";
import { compileSingleCourseProjection, releaseContentSha, scopeCourseTables } from "../domain/incremental-compile.ts";
import { releaseSha } from "../../kernel/sha.ts";
import { readCatalogTables } from "./table-io.ts";
import { compileNext, publishRelease, readActive } from "./releases.ts";
import { readProjectedRelease, readRedirects, writeProjection } from "./projections-repo.ts";
import { runMutation, type AdminPool } from "./mutation.ts";
import { withUnitOfWork, type DbPool } from "../../platform/db/uow.ts";
import { approvedText, NOW, seedLesson, testDatabaseUrl } from "../../../test/fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../../../test/fixtures/catalog-reset.ts";
import { runMigrations } from "../../../scripts/lib/migrations.ts";

async function seedTwoCourses(pool: pg.Pool): Promise<{ alpha: string; beta: string; alphaLesson: string; betaAuthor: string }> {
  const client = await pool.connect();
  try {
    await client.query("INSERT INTO licenses (code, name, url, requires_attribution) VALUES ('youtube-standard', 'Standard YouTube License', 'https://www.youtube.com/t/terms', false)");
    await client.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('src-test', 'institution-site', 'Test courses', 'Test University', 'https://example.org/courses')");
    const authors = (await client.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ('ann-one', 'Ann One', 'AO', 'person'), ('bob-two', 'Bob Two', 'BT', 'person') RETURNING id")).rows.map((row) => row.id);
    const insertCourse = async (slug: string, authorId: string, featured: boolean) => (await client.query<{ id: string }>(`INSERT INTO courses (slug, author_id, title, status, featured, source_id, license_code, canonical_url, rights_status, published_at, area_id, cover_from, shared_with)
      VALUES ($1, $2, $3, 'published', $4, 'src-test', 'youtube-standard', $5, 'accepted-risk', $6, (SELECT a.id FROM subject_areas a WHERE NOT EXISTS (SELECT 1 FROM subject_subareas s WHERE s.area_id = a.id) ORDER BY a.position LIMIT 1), 'own', '{}') RETURNING id`, [slug, authorId, slug, featured, `https://example.org/${slug}`, NOW.toISOString()])).rows[0]?.id ?? "";
    const alpha = await insertCourse("alpha", authors[0] ?? "", true);
    const beta = await insertCourse("beta", authors[1] ?? "", false);
    const alphaLesson = (await seedLesson(client, alpha)).id;
    await seedLesson(client, beta);
    for (const [id, tag] of [[alpha, "alpha"], [beta, "beta"]] as const) {
      for (const field of Object.keys(TEXT_FIELDS.course)) await approvedText(client, "course", id, field, `${tag} ${field}`);
    }
    await client.query("INSERT INTO home_rows (id, kind, title, position) VALUES ('continue', 'continue', NULL, 1)");
    await client.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ('/c/old-alpha', '/c/alpha')");
    const tables = await readCatalogTables(client);
    const payload = compileRelease(tables, { number: 1, publishedAt: NOW.toISOString() }, { fresh: new Set([alpha, beta]) });
    await client.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by, is_active, activated_at)
      VALUES (1, $1, $2::jsonb, $3, '{}'::jsonb, 'seed', 'test', true, now())`, [payload.schemaVersion, JSON.stringify(payload), releaseSha(payload)]);
    return { alpha, beta, alphaLesson, betaAuthor: authors[1] ?? "" };
  } finally { client.release(); }
}

describe("incremental projections", () => {
  let pool: pg.Pool;
  const counts = async () => {
    const releases = Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_releases")).rows[0]?.n);
    const projections = Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_course_projections")).rows[0]?.n);
    const indexes = Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_release_index")).rows[0]?.n);
    return { releases, projections, indexes };
  };

  beforeAll(async () => {
    const connectionString = testDatabaseUrl();
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    pool = new pg.Pool({ connectionString });
  });
  afterAll(async () => { await pool.end(); });

  it("compiles dirty courses only, keeps a repeat publish empty, and rebuilds v2 from the same release", async () => {
    const seed = await seedTwoCourses(pool);
    const compiled: string[] = [];
    const db = pool as unknown as AdminPool;
    const first = await runMutation(db, { requestId: "projection-bootstrap", actor: "test" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "bootstrap", actor: "test", fresh: new Set([seed.alpha, seed.beta]), now: NOW, onCourseCompiled: (id) => { compiled.push(id); } });
      return { data: publication, noop: !publication.release.created };
    });
    expect(first.data.release.created).toBe(false);
    expect(compiled.sort()).toEqual([seed.alpha, seed.beta].sort());
    const afterBootstrap = await counts();
    expect(afterBootstrap.releases).toBe(1);
    expect(afterBootstrap.indexes).toBe(1);
    expect(afterBootstrap.projections).toBe(2);
    const active = (await pool.query<{ payload: { number: number } }>("SELECT payload FROM catalog_releases WHERE is_active")).rows[0]?.payload;
    const projected = await readProjectedRelease(pool, 1);
    expect(releaseContentSha(projected)).toBe(releaseContentSha(active as never));
    const redirects = await readRedirects(pool, 1);
    expect(redirects).toEqual([{ from: "/c/old-alpha", to: "/c/alpha", statusCode: 308 }]);

    compiled.length = 0;
    const repeatStarted = Date.now();
    const repeat = await runMutation(db, { requestId: "projection-noop", actor: "test" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "repeat", actor: "test", fresh: new Set([seed.alpha]), now: NOW, onCourseCompiled: (id) => { compiled.push(id); } });
      return { data: publication, noop: !publication.release.created, entity: "release:1" };
    });
    expect(repeat.data.release.created).toBe(false);
    expect(repeat.data.release.number).toBe(1);
    expect(compiled).toEqual([]);
    expect(await counts()).toEqual(afterBootstrap);
    expect(Date.now() - repeatStarted).toBeLessThan(2000);
    const idle = await compileNext(pool, await readActive(pool), new Set([seed.alpha]), NOW);
    expect(idle.unchanged).toBe(true);
    expect(idle.compiledCourseIds).toEqual([]);

    await pool.query("UPDATE catalog_texts SET text = 'Renamed lesson', approved_sha256 = catalog_text_sha256('Renamed lesson') WHERE entity_id = $1 AND field = 'displayTitle'", [seed.alphaLesson]);
    const preview = await compileNext(pool, await readActive(pool), new Set([seed.alpha]), new Date("2026-10-12T00:00:00.000Z"));
    expect(preview.compiledCourseIds).toEqual([seed.alpha]);
    expect(preview.unchanged).toBe(false);
    compiled.length = 0;
    const edited = await runMutation(db, { requestId: "projection-lesson", actor: "test" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "lesson", actor: "test", fresh: new Set([seed.alpha]), now: new Date("2026-10-12T00:00:00.000Z"), onCourseCompiled: (id) => { compiled.push(id); } });
      return { data: publication, entity: `course:${seed.alpha}` };
    });
    expect(compiled).toEqual([seed.alpha]);
    expect(edited.data.release.created).toBe(true);
    expect(edited.data.release.number).toBe(2);
    const reference = compileRelease(await readCatalogTables(pool), { number: 2, publishedAt: "2026-10-12T00:00:00.000Z" }, { fresh: new Set([seed.alpha]), previous: active as never });
    const stored = (await pool.query<{ payload: unknown }>("SELECT payload FROM catalog_releases WHERE number = 2")).rows[0]?.payload;
    expect(releaseContentSha(stored as never)).toBe(releaseContentSha(reference));

    await pool.query("UPDATE authors SET name = 'Bob Renamed' WHERE id = $1", [seed.betaAuthor]);
    compiled.length = 0;
    await runMutation(db, { requestId: "projection-author", actor: "test" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "author", actor: "test", fresh: new Set([seed.beta]), now: new Date("2026-10-13T00:00:00.000Z"), onCourseCompiled: (id) => { compiled.push(id); } });
      return { data: publication, entity: `author:${seed.betaAuthor}` };
    });
    expect(compiled).toEqual([seed.beta]);

    const beforeDelete = Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_course_projections WHERE course_id = $1", [seed.beta])).rows[0]?.n);
    await pool.query("UPDATE courses SET status = 'archived', featured = false WHERE id = $1", [seed.beta]);
    await runMutation(db, { requestId: "projection-delete", actor: "test" }, null, async (tx) => {
      const publication = await publishRelease(tx, { note: "archive", actor: "test", fresh: new Set(), now: new Date("2026-10-14T00:00:00.000Z") });
      return { data: publication, entity: `course:${seed.beta}` };
    });
    const activeNumber = Number((await pool.query<{ number: number }>("SELECT number FROM catalog_releases WHERE is_active")).rows[0]?.number);
    const index = (await pool.query<{ index_json: { index: { courses: { courseId: string }[] } } }>("SELECT index_json FROM catalog_release_index WHERE release_number = $1", [activeNumber])).rows[0]?.index_json;
    expect(index?.index.courses.map((course) => course.courseId)).toEqual([seed.alpha]);
    expect(Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_course_projections WHERE course_id = $1", [seed.beta])).rows[0]?.n)).toBeGreaterThanOrEqual(beforeDelete);
    expect(Number((await pool.query<{ n: number }>("SELECT count(*)::int AS n FROM catalog_release_index WHERE release_number = 2")).rows[0]?.n)).toBe(1);
  });

  it("rolls back a projection when the index write does not commit", async () => {
    const tables = await readCatalogTables(pool);
    const courseId = tables.courses.find((course) => course.status === "published")?.id ?? "";
    const projection = compileSingleCourseProjection({ courseId, sourceRevision: 1, tables: scopeCourseTables(tables, courseId), previous: null, fresh: true });
    const before = await counts();
    await expect(withUnitOfWork(pool as unknown as DbPool, async (tx) => {
      await writeProjection(tx, projection);
      throw new Error("between projection and index");
    })).rejects.toThrow("between projection and index");
    expect(await counts()).toEqual(before);
  });
});
