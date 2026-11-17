import type { Queryable } from "../../platform/db/uow.ts";
import { notFound } from "../../kernel/errors.ts";
import { catalogVideoProvider } from "../../playback/server/source-registry.ts";
import type { PublicCatalog } from "../domain/release.ts";
import {
  scopeCourseTables, stitchRelease, type CatalogReleaseIndex, type CompiledCourseProjection, type ReleaseFrame, type ScopedCourseState, type StoredReleaseIndex,
} from "../domain/incremental-compile.ts";
import { courseScope, readCatalogTables } from "./table-io.ts";

interface IndexDocument {
  readonly index: CatalogReleaseIndex;
  readonly frame: ReleaseFrame;
  readonly publishedAt: string;
}

function asProjection(row: Record<string, unknown>): CompiledCourseProjection {
  const summary = row.summary_json as { authorId: string; lessonIds: string[]; fingerprint: string };
  const detail = row.detail_json as CompiledCourseProjection["detail"];
  return {
    courseId: String(row.course_id),
    sha256: String(row.projection_sha256),
    sourceRevision: Number(row.source_revision),
    fingerprint: summary.fingerprint,
    summary: { authorId: summary.authorId, lessonIds: summary.lessonIds },
    detail,
  };
}

/** Course revision plus the scoped tables the incremental compiler accepts. */
export async function readScopedCourseState(db: Queryable, courseId: string, previous: PublicCatalog | null, fresh: boolean): Promise<ScopedCourseState> {
  const tables = await readCatalogTables(db, courseScope([courseId]));
  const { rows } = await db.query("SELECT revision FROM courses WHERE id = $1", [courseId]);
  const row = rows[0];
  if (!row) throw notFound(`Course ${courseId}`);
  return { courseId, sourceRevision: Number(row.revision), tables: scopeCourseTables(tables, courseId), previous, fresh };
}

export async function readCourseRevisions(db: Queryable): Promise<Map<string, number>> {
  const { rows } = await db.query("SELECT id, revision FROM courses");
  return new Map(rows.map((row) => [String(row.id), Number(row.revision)]));
}

/** The projections a release already stored, one query. Missing hashes are absent from the map. */
export async function readProjections(db: Queryable, refs: readonly { readonly courseId: string; readonly sha256: string }[]): Promise<Map<string, CompiledCourseProjection>> {
  if (refs.length === 0) return new Map();
  const { rows } = await db.query(`SELECT p.course_id, p.projection_sha256, p.source_revision, p.summary_json, p.detail_json
    FROM catalog_course_projections p
    JOIN unnest($1::text[], $2::text[]) AS w(course_id, sha) ON p.course_id = w.course_id AND p.projection_sha256 = w.sha`,
  [refs.map((ref) => ref.courseId), refs.map((ref) => ref.sha256)]);
  return new Map(rows.map((row) => [String(row.course_id), asProjection(row)]));
}

/** Inserts new hashes. The same course+hash is immutable, so a repeat is a no-op and older hashes stay. */
export async function writeProjections(db: Queryable, projections: readonly CompiledCourseProjection[]): Promise<void> {
  if (projections.length === 0) return;
  await db.query(`INSERT INTO catalog_course_projections (course_id, projection_sha256, source_revision, summary_json, detail_json)
    SELECT course_id, projection_sha256, source_revision, summary_json, detail_json
    FROM jsonb_to_recordset($1::jsonb) AS r(course_id text, projection_sha256 text, source_revision int, summary_json jsonb, detail_json jsonb)
    ON CONFLICT (course_id, projection_sha256) DO NOTHING`, [JSON.stringify(projections.map((projection) => ({
    course_id: projection.courseId, projection_sha256: projection.sha256, source_revision: projection.sourceRevision,
    summary_json: { ...projection.summary, fingerprint: projection.fingerprint }, detail_json: projection.detail,
  })))]);
}

/** Inserts a new hash. The same course+hash is immutable, so a repeat is a no-op and older hashes stay. */
export async function writeProjection(db: Queryable, projection: CompiledCourseProjection): Promise<void> {
  await db.query(`INSERT INTO catalog_course_projections (course_id, projection_sha256, source_revision, summary_json, detail_json)
    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
    ON CONFLICT (course_id, projection_sha256) DO NOTHING`, [
    projection.courseId, projection.sha256, projection.sourceRevision,
    JSON.stringify({ ...projection.summary, fingerprint: projection.fingerprint }),
    JSON.stringify(projection.detail),
  ]);
}

export async function writeReleaseIndex(db: Queryable, releaseNumber: number, index: CatalogReleaseIndex, frame: ReleaseFrame, publishedAt: string): Promise<void> {
  const document: IndexDocument = { index, frame, publishedAt };
  await db.query(`INSERT INTO catalog_release_index (release_number, manifest_sha256, index_json, format_version)
    VALUES ($1, $2, $3::jsonb, $4)
    ON CONFLICT (release_number) DO NOTHING`, [releaseNumber, index.manifestSha256, JSON.stringify(document), index.formatVersion]);
}

export async function readReleaseIndex(db: Queryable, releaseNumber: number): Promise<(StoredReleaseIndex & { readonly frame: ReleaseFrame; readonly publishedAt: string; readonly manifestSha256: string }) | null> {
  const { rows } = await db.query("SELECT manifest_sha256, index_json FROM catalog_release_index WHERE release_number = $1", [releaseNumber]);
  const row = rows[0];
  if (!row) return null;
  const document = row.index_json as IndexDocument;
  return {
    courses: document.index.courses, authors: document.index.authors, globalFingerprint: document.index.globalFingerprint,
    ...(document.index.licenses === undefined ? {} : { licenses: document.index.licenses }),
    ...(document.index.sources === undefined ? {} : { sources: document.index.sources }),
    frame: document.frame, publishedAt: document.publishedAt, manifestSha256: String(row.manifest_sha256),
  };
}

export async function writeRedirects(db: Queryable, releaseNumber: number, redirects: readonly { readonly from: string; readonly to: string }[], statusCode = 308): Promise<void> {
  if (redirects.length === 0) return;
  await db.query(`INSERT INTO catalog_redirects (release_number, from_path, to_path, status_code)
    SELECT $1, r.from_path, r.to_path, $2
    FROM jsonb_to_recordset($3::jsonb) AS r(from_path text, to_path text)
    ON CONFLICT (release_number, from_path) DO NOTHING`, [releaseNumber, statusCode, JSON.stringify(redirects.map((redirect) => ({ from_path: redirect.from, to_path: redirect.to })))]);
}

export async function readRedirects(db: Queryable, releaseNumber: number): Promise<{ from: string; to: string; statusCode: number }[]> {
  const { rows } = await db.query("SELECT from_path, to_path, status_code FROM catalog_redirects WHERE release_number = $1 ORDER BY from_path", [releaseNumber]);
  return rows.map((row) => ({ from: String(row.from_path), to: String(row.to_path), statusCode: Number(row.status_code) }));
}

/** The active release's SHA only. The payload never enters the Data Cache. */
export async function readActivePayloadSha(db: Queryable): Promise<string> {
  const row = (await db.query("SELECT payload_sha256 FROM catalog_releases WHERE is_active")).rows[0];
  if (!row) throw new Error("No active catalog release.");
  return String(row.payload_sha256);
}

/** One stored release payload by SHA, newest number first. */
export async function readReleasePayloadBySha(db: Queryable, sha: string): Promise<{ payload: unknown; sha: string }> {
  const row = (await db.query("SELECT payload, payload_sha256 FROM catalog_releases WHERE payload_sha256 = $1 ORDER BY number DESC LIMIT 1", [sha])).rows[0];
  if (!row) throw new Error("No catalog release with that SHA.");
  return { payload: row.payload, sha: String(row.payload_sha256) };
}

/** The active release payload and its stored SHA. */
export async function readActiveReleasePayload(db: Queryable): Promise<{ payload: unknown; sha: string }> {
  const row = (await db.query("SELECT payload, payload_sha256 FROM catalog_releases WHERE is_active")).rows[0];
  if (!row) throw new Error("No active catalog release.");
  return { payload: row.payload, sha: String(row.payload_sha256) };
}

/** The active release number. Page reads key the Data Cache with it. */
export async function readActiveReleaseNumber(db: Queryable): Promise<number> {
  const { rows } = await db.query("SELECT number FROM catalog_releases WHERE is_active");
  const row = rows[0];
  if (!row) throw new Error("No active catalog release.");
  return Number(row.number);
}

/** Author ids for the indexed course projections, matched by course id and projection sha. */
export async function authorIdsOfProjections(db: Queryable, courses: readonly { readonly courseId: string; readonly sha256: string }[]): Promise<Map<string, string>> {
  if (courses.length === 0) return new Map();
  const { rows } = await db.query(
    `SELECT p.course_id, p.summary_json->>'authorId' AS author_id
     FROM catalog_course_projections p
     JOIN unnest($1::text[], $2::text[]) AS wanted(course_id, sha)
       ON p.course_id = wanted.course_id AND p.projection_sha256 = wanted.sha`,
    [courses.map((course) => course.courseId), courses.map((course) => course.sha256)],
  );
  return new Map(rows.map((row) => [String(row.course_id), String(row.author_id)]));
}

/** Rebuilds one release from its own index and projections. Throws when a referenced projection is missing. */
export async function readProjectedRelease(db: Queryable, releaseNumber: number): Promise<PublicCatalog> {
  const index = await readReleaseIndex(db, releaseNumber);
  if (!index) throw new Error(`Release ${String(releaseNumber)} has no projection index.`);
  const loaded = await readProjections(db, index.courses);
  const projections: CompiledCourseProjection[] = [];
  for (const course of index.courses) {
    const projection = loaded.get(course.courseId);
    if (!projection) throw new Error(`Projection ${course.courseId} ${course.sha256} is missing.`);
    projections.push(projection);
  }
  return stitchRelease({ number: releaseNumber, publishedAt: index.publishedAt, projections, frame: index.frame });
}


/** Keyset page of courses for the admin list. The unfiltered form is a primary-key range. */
export async function selectCoursePage(db: Queryable, status: string | null, cursor: string, limit: number): Promise<Record<string, unknown>[]> {
  const filtered = status !== null;
  const provider = catalogVideoProvider();
  const { rows } = await db.query(coursePageSql(filtered), filtered ? [status, cursor, limit, provider] : [cursor, limit, provider]);
  return rows;
}

/** Keyset page. The unfiltered form is a primary-key range: `($1 IS NULL OR status = $1)` makes Postgres read every course. */
function coursePageSql(filtered: boolean): string {
  const where = filtered ? "WHERE c.status = $1 AND c.id > $2" : "WHERE c.id > $1";
  const limit = filtered ? "$3" : "$2";
  const provider = filtered ? "$4" : "$3";
  return `WITH page AS (
  SELECT c.id, c.slug, c.title, c.author_id, c.status, c.featured, c.revision, c.published_at,
    c.area_id, c.subarea_id, c.license_code, c.source_id, c.canonical_url, c.rights_status,
    c.attribution_text, c.rights_notes, c.rights_checked_by, c.rights_checked_at, c.legacy,
    c.language_label, c.lesson_noun, c.cover_from, c.shared_with,
    EXISTS (SELECT 1 FROM authors a WHERE a.id = c.author_id) AS author_exists,
    EXISTS (SELECT 1 FROM home_row_items i JOIN home_rows r ON r.id = i.row_id AND r.visible WHERE i.course_id = c.id) AS in_home
  FROM courses c
  ${where}
  ORDER BY c.id
  LIMIT ${limit}
),
edition_json AS (
  SELECT e.course_id, jsonb_agg(jsonb_build_object('id', e.id, 'slug', e.slug, 'position', e.position, 'year', e.year, 'term', e.term, 'variant_kind', e.variant_kind, 'variant_label', e.variant_label, 'language', e.language) ORDER BY e.position) AS editions
  FROM course_editions e WHERE e.course_id IN (SELECT id FROM page) GROUP BY e.course_id
),
lesson_json AS (
  SELECT l.course_id, jsonb_agg(jsonb_build_object('id', l.id, 'edition_id', l.edition_id, 'position', l.position, 'visible', l.visible)) AS lessons
  FROM lessons l WHERE l.course_id IN (SELECT id FROM page) GROUP BY l.course_id
),
video_json AS (
  SELECT l.course_id, jsonb_agg(jsonb_build_object('lesson_id', v.lesson_id, 'status', v.status)) AS videos
  FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id
  WHERE l.course_id IN (SELECT id FROM page) AND v.provider = ${provider}
  GROUP BY l.course_id
),
text_json AS (
  SELECT src.course_id, jsonb_agg(jsonb_build_object(
    'entity_kind', src.entity_kind, 'entity_id', src.entity_id, 'field', src.field, 'locale', src.locale,
    'text', src.text, 'status', src.status, 'approved_sha256', src.approved_sha256)) AS texts
  FROM (
    SELECT p.id AS course_id, t.entity_kind, t.entity_id, t.field, t.locale, t.text, t.status, t.approved_sha256
    FROM page p JOIN catalog_texts t ON t.entity_kind = 'course' AND t.entity_id = p.id
    UNION ALL
    SELECT l.course_id, t.entity_kind, t.entity_id, t.field, t.locale, t.text, t.status, t.approved_sha256
    FROM lessons l JOIN page p ON p.id = l.course_id JOIN catalog_texts t ON t.entity_kind = 'lesson' AND t.entity_id = l.id
  ) src
  GROUP BY src.course_id
)
SELECT p.id, p.slug, p.title, p.author_id, p.status, p.featured, p.revision, p.published_at,
  p.area_id, p.subarea_id, p.license_code, p.source_id, p.canonical_url, p.rights_status,
  p.attribution_text, p.rights_notes, p.rights_checked_by, p.rights_checked_at, p.legacy,
  p.language_label, p.lesson_noun, p.cover_from, p.shared_with, p.author_exists, p.in_home,
  e.editions, l.lessons, v.videos, t.texts
FROM page p
LEFT JOIN edition_json e ON e.course_id = p.id
LEFT JOIN lesson_json l ON l.course_id = p.id
LEFT JOIN video_json v ON v.course_id = p.id
LEFT JOIN text_json t ON t.course_id = p.id
ORDER BY p.id`;
}

