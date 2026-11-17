import type { Queryable, UnitOfWork } from "../../platform/db/uow.ts";
import type { CatalogCoverRef, CatalogOwnersPort, MediaCourse, MediaOwner } from "../../media/ports/owner.ts";

/** Catalog rows that media must not read itself. SQL stays on the caller's client. */
export function catalogOwners(tx: Queryable): CatalogOwnersPort {
  return {
    async courseOf(owner, ownerId) {
      if (owner === "area") {
        const { rows } = await tx.query("SELECT a.id, c.id AS course_id, c.status FROM subject_areas a LEFT JOIN courses c ON c.area_id = a.id WHERE a.id = $1 ORDER BY c.id", [ownerId]);
        if (!rows.length) return undefined;
        return { courseId: ownerId, published: true, courses: rows.flatMap((row) => typeof row.course_id === "string" ? [{ courseId: row.course_id, published: row.status === "published" }] : []) };
      }
      if (owner === "institution") {
        const { rows } = await tx.query("SELECT id FROM authors WHERE id = $1", [ownerId]);
        return rows.length ? { courseId: ownerId, published: false } : undefined;
      }
      if (owner === "subarea") {
        const { rows } = await tx.query("SELECT s.id, c.id AS course_id, c.status FROM subject_subareas s LEFT JOIN courses c ON c.subarea_id = s.id WHERE s.id = $1 ORDER BY c.id", [ownerId]);
        if (!rows.length) return undefined;
        return { courseId: ownerId, published: true, subareaId: ownerId, courses: rows.flatMap((row) => typeof row.course_id === "string" ? [{ courseId: row.course_id, published: row.status === "published" }] : []) };
      }
      const sql = owner === "course" ? "SELECT id AS course_id, status FROM courses WHERE id = $1"
        : "SELECT l.course_id, c.status FROM lessons l JOIN courses c ON c.id = l.course_id WHERE l.id = $1";
      const { rows } = await tx.query(sql, [ownerId]);
      const courseId = rows[0]?.course_id;
      return typeof courseId === "string" ? { courseId, published: rows[0]?.status === "published" } : undefined;
    },
    async graph() {
      const [courses, lessons] = await Promise.all([
        tx.query("SELECT id, area_id, subarea_id, cover_from, status FROM courses ORDER BY id"),
        tx.query("SELECT id, course_id FROM lessons ORDER BY id"),
      ]);
      return {
        courses: courses.rows.map((row) => ({ id: String(row.id), area_id: typeof row.area_id === "string" ? row.area_id : null, subarea_id: typeof row.subarea_id === "string" ? row.subarea_id : null, cover_from: String(row.cover_from), status: String(row.status) })),
        lessons: lessons.rows.map((row) => ({ id: String(row.id), course_id: String(row.course_id) })),
      };
    },
    async lockGraph() {
      if ("acquireLock" in tx) await (tx as UnitOfWork).acquireLock({ scope: "media-maintenance", mode: "exclusive" });
    },
    async inventory() {
      const covers: CatalogCoverRef[] = [];
      const add = (ownerId: string, kind: string, cover: unknown) => { covers.push({ ownerId, kind, cover }); };
      for (const table of ["authors", "home_rows"] as const) {
        for (const row of (await tx.query(`SELECT id, cover FROM ${table} WHERE cover IS NOT NULL`)).rows) add(String(row.id), table === "authors" ? "author_cover_9x16" : "university_cover_9x16", row.cover);
      }
      for (const release of (await tx.query("SELECT payload->'authors' AS authors, payload->'home'->'rows' AS home_rows FROM catalog_releases WHERE is_active")).rows) {
        for (const author of (release.authors ?? []) as { id: string; cover?: unknown }[]) if (author.cover) add(author.id, "author_cover_9x16", author.cover);
        for (const row of (release.home_rows ?? []) as { id: string; cover?: unknown }[]) if (row.cover) add(row.id, "university_cover_9x16", row.cover);
      }
      return covers;
    },
  };
}

/** Existing call shape: a pool factory, one owner lookup. */
export function catalogCourseOf(db: () => Queryable) {
  return (owner: MediaOwner, ownerId: string): Promise<MediaCourse | undefined> => catalogOwners(db()).courseOf(owner, ownerId);
}
