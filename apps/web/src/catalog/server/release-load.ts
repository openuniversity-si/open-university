import type { Queryable } from "../../platform/db/uow.ts";
import {
  coursesToReuse, fingerprintAuthor, fingerprintLicense, fingerprintSource, type StoredReleaseIndex,
} from "../domain/incremental-compile.ts";
import type { CatalogTables } from "../domain/tables.ts";
import { readCatalogTables, type CatalogScope } from "./table-io.ts";

/** Shared tables only. Lesson, edition, video and text rows stay out until a course has to be compiled. */
const LIGHT: CatalogScope = {
  values: [],
  where: {
    course_editions: "false",
    lessons: "false",
    lesson_videos: "false",
    catalog_texts: "false",
  },
};

function heavyScope(courseIds: readonly string[]): CatalogScope {
  const lessons = "SELECT id FROM lessons WHERE course_id = ANY($1)";
  return {
    values: [courseIds],
    where: {
      licenses: "false",
      content_sources: "false",
      authors: "false",
      subject_areas: "false",
      subject_subareas: "false",
      courses: "false",
      home_rows: "false",
      home_row_items: "false",
      slug_redirects: "false",
      course_editions: "course_id = ANY($1)",
      lessons: "course_id = ANY($1)",
      lesson_videos: `lesson_id IN (${lessons})`,
      catalog_texts: `(entity_kind = 'course' AND entity_id = ANY($1)) OR (entity_kind = 'lesson' AND entity_id IN (${lessons}))`,
    },
  };
}

const CHANGED_SQL = `SELECT DISTINCT course_id FROM (
  SELECT entity_id AS course_id FROM catalog_texts WHERE entity_kind = 'course' AND updated_at > $1
  UNION
  SELECT l.course_id FROM catalog_texts t JOIN lessons l ON l.id = t.entity_id WHERE t.entity_kind = 'lesson' AND t.updated_at > $1
  UNION
  SELECT course_id FROM lessons WHERE updated_at > $1
  UNION
  SELECT course_id FROM course_editions WHERE updated_at > $1
  UNION
  SELECT l.course_id FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id WHERE v.checked_at > $1
) changed`;

export interface LoadedRelease {
  readonly tables: CatalogTables;
  readonly revisions: ReadonlyMap<string, number>;
  readonly reuse: ReadonlySet<string>;
}

/**
 * Tables for one release cut (D-033). Untouched courses contribute their row and their stored projection,
 * not their lessons. `since` is the active release's write time; rows newer than it are loaded.
 */
export async function loadReleaseTables(db: Queryable, fresh: ReadonlySet<string>, stored: StoredReleaseIndex | null, since: Date | null): Promise<LoadedRelease> {
  const light = await readCatalogTables(db, LIGHT);
  const { rows: revisionRows } = await db.query("SELECT id, revision FROM courses");
  const revisions = new Map(revisionRows.map((row) => [String(row.id), Number(row.revision)]));
  const stamps = stored?.licenses !== undefined && stored.sources !== undefined;
  const changed = new Set<string>();
  if (stamps && since) {
    const { rows } = await db.query(CHANGED_SQL, [since]);
    for (const row of rows) changed.add(String(row.course_id));
  }
  const storedAuthors = new Map((stored?.authors ?? []).map((author) => [author.id, author.fingerprint]));
  const dirtyAuthorIds = new Set(light.authors.filter((author) => storedAuthors.get(author.id) !== fingerprintAuthor(author)).map((author) => author.id));
  const storedLicenses = new Map((stored?.licenses ?? []).map((license) => [license.code, license.fingerprint]));
  const dirtyLicenseCodes = new Set(light.licenses.filter((license) => storedLicenses.get(license.code) !== fingerprintLicense(license)).map((license) => license.code));
  const storedSources = new Map((stored?.sources ?? []).map((source) => [source.id, source.fingerprint]));
  const dirtySourceIds = new Set(light.content_sources.filter((source) => storedSources.get(source.id) !== fingerprintSource(source)).map((source) => source.id));
  const published = light.courses.filter((course) => course.status === "published").map((course) => ({
    id: course.id, revision: revisions.get(course.id) ?? 0, authorId: course.author_id, licenseCode: course.license_code, sourceId: course.source_id,
  }));
  const reuse = coursesToReuse({ published, stored, fresh, changed, dirtyAuthorIds, dirtyLicenseCodes, dirtySourceIds });
  const loadIds = published.flatMap((course) => reuse.has(course.id) ? [] : [course.id]);
  const heavy = loadIds.length === 0 ? null : await readCatalogTables(db, heavyScope(loadIds));
  const tables: CatalogTables = heavy
    ? { ...light, course_editions: heavy.course_editions, lessons: heavy.lessons, lesson_videos: heavy.lesson_videos, catalog_texts: heavy.catalog_texts }
    : light;
  return { tables, revisions, reuse };
}
