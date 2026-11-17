import "server-only";
import type { Queryable } from "../../platform/db/uow.ts";
import type { CatalogReleaseIndex } from "../domain/incremental-compile.ts";
import type { AdminCourseFilter, AdminCoursePage, AdminCourseSummary, CatalogQueriesPort, CourseDetailProjection, RedirectProjection } from "../ports/queries.ts";
import { readRedirects, readReleaseIndex } from "./projections-repo.ts";

async function indexOf(db: Queryable, releaseNumber: number, preview: boolean): Promise<CatalogReleaseIndex | null> {
  if (preview) return null;
  const stored = await readReleaseIndex(db, releaseNumber);
  return stored ? { formatVersion: 3, manifestSha256: stored.manifestSha256, globalFingerprint: stored.globalFingerprint, courses: stored.courses, authors: stored.authors } : null;
}

/** SQL adapter. Public pages read one release's stored frame and projections. Admin rows come from the course table. */
export function createCatalogQueries(db: Queryable): CatalogQueriesPort {
  return {
    getCatalogIndex(scope) {
      return indexOf(db, scope.releaseNumber, scope.preview);
    },
    async getUniversityPageProjection(slug, scope) {
      if (scope.preview) return null;
      const stored = await readReleaseIndex(db, scope.releaseNumber);
      const row = stored?.frame.home.rows.find((entry) => entry.id === slug);
      return row ? { slug, title: row.title, courseIds: [...row.courseIds] } : null;
    },
    async getUniversityAreaProjection(slug, area, scope) {
      const page = await createCatalogQueries(db).getUniversityPageProjection(slug, scope);
      return page ? { universitySlug: slug, area, courseIds: page.courseIds } : null;
    },
    async getCourseDetailProjection(slug, scope): Promise<CourseDetailProjection | null> {
      const index = await indexOf(db, scope.releaseNumber, scope.preview);
      if (!index || index.courses.length === 0) return null;
      const { rows } = await db.query(
        `SELECT p.course_id, p.detail_json #>> '{course,title}' AS title, p.summary_json->'lessonIds' AS lesson_ids
         FROM catalog_course_projections p
         JOIN unnest($1::text[], $2::text[]) AS w(course_id, sha)
           ON p.course_id = w.course_id AND p.projection_sha256 = w.sha
         WHERE p.detail_json #>> '{course,slug}' = $3
         LIMIT 1`,
        [index.courses.map((course) => course.courseId), index.courses.map((course) => course.sha256), slug],
      );
      const row = rows[0];
      if (!row) return null;
      const lessonIds = Array.isArray(row.lesson_ids) ? row.lesson_ids.map(String) : [];
      return { id: String(row.course_id), slug, title: String(row.title), lessonIds };
    },
    async getAuthorsDirectoryProjection(scope) {
      const index = await indexOf(db, scope.releaseNumber, scope.preview);
      return { authorIds: index?.authors.map((author) => author.id) ?? [] };
    },
    async resolveRedirect(path, scope): Promise<RedirectProjection | null> {
      if (scope.preview) return null;
      const found = (await readRedirects(db, scope.releaseNumber)).find((redirect) => redirect.from === path);
      return found && (found.statusCode === 301 || found.statusCode === 308) ? { from: found.from, to: found.to, statusCode: found.statusCode } : null;
    },
    async getAdminCourseSummary(id): Promise<AdminCourseSummary | null> {
      const { rows } = await db.query("SELECT id, slug, title, status, revision FROM courses WHERE id = $1", [id]);
      const row = rows[0];
      return row ? { id: String(row.id), slug: String(row.slug), title: String(row.title), status: String(row.status), revision: Number(row.revision) } : null;
    },
    async listAdminCourses(filter: AdminCourseFilter): Promise<AdminCoursePage> {
      const { rows } = await db.query(`SELECT id, slug, title, status, revision FROM courses
        WHERE ($1::text IS NULL OR status = $1) ORDER BY id OFFSET $2 LIMIT $3`, [filter.status ?? null, filter.offset, filter.limit]);
      const total = await db.query("SELECT count(*)::int AS n FROM courses WHERE ($1::text IS NULL OR status = $1)", [filter.status ?? null]);
      return {
        courses: rows.map((row) => ({ id: String(row.id), slug: String(row.slug), title: String(row.title), status: String(row.status), revision: Number(row.revision) })),
        total: Number(total.rows[0]?.n ?? 0),
      };
    },
  };
}
