import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { QueryFixtureRelease } from "../testing/in-memory-queries.ts";
import { queriesContract, queryFixture } from "../testing/queries-contract.ts";
import { NOW, testDatabaseUrl } from "../../../test/fixtures/admin-catalog.ts";
import { resetCatalogTables } from "../../../test/fixtures/catalog-reset.ts";
import { runMigrations } from "../../../scripts/lib/migrations.ts";
import { createCatalogQueries } from "./queries.ts";

function indexDocument(release: QueryFixtureRelease) {
  return {
    index: release.index,
    publishedAt: "2020-01-01T00:00:00.000Z",
    frame: {
      authors: [],
      home: {
        featuredCourseId: null,
        rows: release.universities.map((page: QueryFixtureRelease["universities"][number]) => ({ id: page.slug, kind: "curated", title: page.title, courseIds: [...page.courseIds] })),
      },
      redirects: [],
    },
  };
}

async function seed(pool: pg.Pool): Promise<void> {
  const fixture = queryFixture();
  const client = await pool.connect();
  try {
    await client.query("INSERT INTO licenses (code, name, url, requires_attribution) VALUES ('youtube-standard', 'Standard YouTube License', 'https://www.youtube.com/t/terms', false)");
    await client.query("INSERT INTO content_sources (id, kind, title, publisher, url) VALUES ('src-test', 'institution-site', 'Test courses', 'Test University', 'https://example.org/courses')");
    const authorId = (await client.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ('author-a', 'Author A', 'AA', 'person') RETURNING id")).rows[0]?.id;
    if (!authorId) throw new Error("author seed failed");
    const published = new Map(fixture.releases.flatMap((release) => release.courses.map((course) => [course.id, course] as const)));
    for (const course of published.values()) {
      await client.query(`INSERT INTO courses (id, slug, author_id, title, status, revision, featured, source_id, license_code, canonical_url, rights_status, published_at, area_id, cover_from, shared_with)
        VALUES ($1, $2, $3, $4, 'published', 1, false, 'src-test', 'youtube-standard', $5, 'accepted-risk', $6, (SELECT a.id FROM subject_areas a WHERE NOT EXISTS (SELECT 1 FROM subject_subareas s WHERE s.area_id = a.id) ORDER BY a.position LIMIT 1), 'own', '{}')`,
      [course.id, course.slug, authorId, course.title, `https://example.org/${course.slug}`, NOW.toISOString()]);
    }
    for (const draft of fixture.drafts) {
      await client.query("INSERT INTO courses (id, slug, author_id, title, status, revision, cover_from, shared_with) VALUES ($1, $2, $3, $4, $5, $6, 'own', '{}')",
        [draft.id, draft.slug, authorId, draft.title, draft.status, draft.revision]);
    }
    const seen = new Set<string>();
    for (const release of fixture.releases) {
      await client.query(`INSERT INTO catalog_releases (number, schema_version, payload, payload_sha256, counts, note, created_by, is_active)
        VALUES ($1, 2, '{}'::jsonb, $2, '{}'::jsonb, 'queries', 'test', $3)`,
      [release.number, release.number === 2 ? "ee".repeat(32) : "ff".repeat(32), release.number === 2]);
      await client.query("INSERT INTO catalog_release_index (release_number, manifest_sha256, index_json, format_version) VALUES ($1, $2, $3::jsonb, $4)",
        [release.number, release.index.manifestSha256, JSON.stringify(indexDocument(release)), release.index.formatVersion]);
      for (const redirect of release.redirects) {
        await client.query("INSERT INTO catalog_redirects (release_number, from_path, to_path, status_code) VALUES ($1, $2, $3, $4)",
          [release.number, redirect.from, redirect.to, redirect.statusCode]);
      }
      for (const course of release.index.courses) {
        const key = `${course.courseId}:${course.sha256}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const detail = published.get(course.courseId);
        if (!detail) throw new Error(`missing detail for ${course.courseId}`);
        await client.query(`INSERT INTO catalog_course_projections (course_id, projection_sha256, source_revision, summary_json, detail_json)
          VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)`, [
          course.courseId, course.sha256, course.sourceRevision,
          JSON.stringify({ authorId, lessonIds: detail.lessonIds, fingerprint: course.fingerprint }),
          JSON.stringify({ course: { slug: detail.slug, title: detail.title }, lessons: [], author: { id: authorId } }),
        ]);
      }
    }
  } finally { client.release(); }
}

describe("catalog queries", () => {
  let pool: pg.Pool;
  beforeAll(async () => {
    const connectionString = testDatabaseUrl();
    await runMigrations(connectionString, false);
    await resetCatalogTables(connectionString);
    pool = new pg.Pool({ connectionString });
    await seed(pool);
  });
  afterAll(async () => { await pool.end(); });

  it.each(queriesContract())("$id", async (entry) => {
    await entry.run({ queries: () => createCatalogQueries(pool) });
  });

  it("keeps the seeded admin page at three rows", async () => {
    const page = await createCatalogQueries(pool).listAdminCourses({ offset: 0, limit: 10 });
    expect(page.courses.map((course) => course.id)).toEqual(["course-draft", "course-live", "course-old"]);
    expect(page.total).toBe(3);
  });
});
