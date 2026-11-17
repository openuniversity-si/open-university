import { limitConcurrency, type ConcurrencyLimit } from "../../platform/db/limit.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { preconditionsFailed, unprocessable } from "../../kernel/errors.ts";
import { catalogVideoProvider } from "../../playback/server/source-registry.ts";
import type { TextEntityKind } from "../domain/fields.ts";
import type { CourseBundleV1 } from "../domain/bundle.ts";
import { bundleHash } from "../domain/bundle.ts";
import { defaultEdition } from "../domain/edition-variant.ts";
import { homePlacementFailures, homeRefCoverErrors } from "../domain/rules/home.ts";
import type { CatalogRefs } from "../domain/rules/refs.ts";
import { catalogTableColumns, catalogTables, catalogTablesSchema, sortTables, type CatalogTableName, type CatalogTables } from "../domain/tables.ts";
import { adoptRowInstitutions } from "./row-institution.ts";

const TIMESTAMPS = new Set(["rights_checked_at", "published_at", "checked_at", "approved_at"]);

/** Row filters per table (`$1`… bound to `values`); a table without one is read whole. */
export interface CatalogScope {
  readonly where: Partial<Record<CatalogTableName, string>>;
  readonly values: readonly unknown[];
}

/**
 * The rows the rules and the course detail read for these courses (rules.ts courseFacts): the courses, their editions,
 * lessons, videos, texts, authors and Home items, plus the small reference tables. Not the rest of the catalog.
 */
export function courseScope(courseIds: readonly string[]): CatalogScope {
  const lessons = "SELECT id FROM lessons WHERE course_id = ANY($1)";
  return {
    values: [courseIds],
    where: {
      authors: "id IN (SELECT author_id FROM courses WHERE id = ANY($1))",
      courses: "id = ANY($1)",
      course_editions: "course_id = ANY($1)",
      lessons: "course_id = ANY($1)",
      lesson_videos: `lesson_id IN (${lessons})`,
      catalog_texts: `(entity_kind = 'course' AND entity_id = ANY($1)) OR (entity_kind = 'lesson' AND entity_id IN (${lessons}))`,
      home_row_items: "course_id = ANY($1)",
      slug_redirects: "false",
    },
  };
}

/** These three dominate the jsonb. One runs at a time; the small PR compute rejected every table in one statement (SQLSTATE 53200). */
const HEAVY_CATALOG_TABLES = new Set<CatalogTableName>(["lessons", "lesson_videos", "catalog_texts"]);
const CATALOG_TABLE_READS = 3;

async function readCatalogTable(db: Queryable, name: CatalogTableName, scope: CatalogScope | undefined): Promise<Record<string, unknown>[]> {
  const where = scope?.where[name];
  const { rows } = await db.query(`SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) AS rows FROM "${name}" t${where ? ` WHERE ${where}` : ""}`, scope && where?.includes("$") ? [...scope.values] : []);
  const columns = catalogTableColumns(name);
  const raw = rows[EXTENT.first]?.rows;
  const records = Array.isArray(raw) ? raw.filter((row): row is Record<string, unknown> => typeof row === "object" && row !== null) : [];
  return records.map((row) => Object.fromEntries(columns.map((column) => {
    const value = row[column];
    return [column, TIMESTAMPS.has(column) && typeof value === "string" ? new Date(value).toISOString() : value];
  })));
}

/**
 * Every catalog table, normalized (see tables.ts) and in key order: what compileRelease, the admin API and the current API export read.
 * One statement per table. Aggregating every table in a single query exceeds the PR compute's memory (SQLSTATE 53200).
 * Light tables share three reads; a heavy table does not share its read with another heavy table.
 */
export async function readCatalogTables(db: Queryable, scope?: CatalogScope, occupy?: ConcurrencyLimit): Promise<CatalogTables> {
  const slots = occupy ?? limitConcurrency(CATALOG_TABLE_READS);
  const oneHeavy = limitConcurrency(1);
  const entries = await Promise.all(catalogTables.map(({ name }) => {
    const read = () => readCatalogTable(db, name, scope);
    return HEAVY_CATALOG_TABLES.has(name) ? oneHeavy(() => slots(read)) : slots(read);
  }));
  return sortTables(catalogTablesSchema.parse(Object.fromEntries(catalogTables.map(({ name }, index) => {
    const rows = entries[index];
    if (!rows) throw new Error(`missing catalog table ${name}`);
    return [name, rows];
  }))));
}

interface CourseWrite {
  author_id: string; author_slug: string; author_name: string; author_monogram: string; author_kind: CourseBundleV1["author"]["kind"];
  id: string; slug: string; title: string; lesson_noun: string; hash: string;
  language_label: string | null; set_language: boolean;
  area_id: string | null; set_area: boolean;
  subarea_id: string | null; set_subarea: boolean;
  license_code: string | null; set_license: boolean;
  source_id: string | null; set_source: boolean;
  attribution_text: string | null; set_attribution: boolean;
  canonical_url: string | null; set_canonical: boolean;
  rights_status: string | null; set_rights: boolean;
  cover_from: string;
  shared_with: string[];
}

interface LessonWrite { id: string; course_id: string; edition_id: string; slug: string; title: string; position: number; youtube_id: string; duration_seconds: number; part: string }
interface EditionWrite {
  id: string; course_id: string; slug: string; label: string; year: number | null; position: number;
  variant_kind: string | null; variant_label: string | null; language: string | null;
}
interface TextWrite { entity_kind: string; entity_id: string; field: string; text: string; approved: boolean; approved_by: string | null; approved_at: string | null }
interface HomeWrite { row_id: string; course_id: string; expected_revision: number }

const COURSE_SQL = `author_id text, author_slug text, author_name text, author_monogram text, author_kind text, id text, slug text, title text, lesson_noun text, hash text,
  language_label text, set_language boolean, area_id text, set_area boolean, subarea_id text, set_subarea boolean,
  license_code text, set_license boolean, source_id text, set_source boolean, attribution_text text, set_attribution boolean,
  canonical_url text, set_canonical boolean, rights_status text, set_rights boolean, cover_from text, shared_with text[]`;

function courseWrite(bundle: CourseBundleV1): CourseWrite {
  const course = bundle.course;
  const editionLanguage = defaultEdition(bundle.editions)?.language;
  const language = course.languageLabel ?? editionLanguage ?? null;
  return {
    author_id: bundle.author.id, author_slug: bundle.author.slug, author_name: bundle.author.name, author_monogram: bundle.author.monogram, author_kind: bundle.author.kind,
    id: course.id, slug: course.slug, title: course.title, lesson_noun: course.lessonNoun, hash: bundleHash(bundle),
    language_label: language, set_language: course.languageLabel !== undefined || editionLanguage !== undefined,
    area_id: course.areaId ?? null, set_area: course.areaId !== undefined,
    subarea_id: course.subareaId ?? null, set_subarea: course.subareaId !== undefined,
    license_code: course.licenseCode ?? null, set_license: course.licenseCode !== undefined,
    source_id: course.sourceId ?? null, set_source: course.sourceId !== undefined,
    attribution_text: course.attributionText ?? null, set_attribution: course.attributionText !== undefined,
    canonical_url: course.canonicalUrl ?? null, set_canonical: course.canonicalUrl !== undefined,
    rights_status: course.rightsStatus ?? null, set_rights: course.rightsStatus !== undefined,
    cover_from: course.coverFrom,
    shared_with: [...course.sharedWith],
  };
}

/** The batch's Home placements: rows exist and the revision is current (412), then every visible row has its cover (422). */
async function assertHomePlacements(db: Queryable, bundles: readonly CourseBundleV1[], refs: CatalogRefs): Promise<void> {
  const homes = bundles.flatMap((bundle) => (bundle.home ? [{ ...bundle.home, courseId: bundle.course.id }] : []));
  if (homes.length === EXTENT.empty) return;
  const locked = await db.query("SELECT revision FROM catalog_home FOR UPDATE");
  const failures = homePlacementFailures(homes, refs.homeRows, Number(locked.rows[EXTENT.first]?.revision ?? 0));
  if (failures.length > EXTENT.empty) throw preconditionsFailed(failures);
  const errors = homeRefCoverErrors(refs.homeRows);
  if (errors.length > EXTENT.empty) throw unprocessable(errors.join(" "), { errors });
}

export async function writeBundles(db: Queryable, bundles: readonly CourseBundleV1[], refs: CatalogRefs, checkedAt: string): Promise<void> {
  const courses = bundles.map(courseWrite);
  const editions: EditionWrite[] = bundles.flatMap((bundle) => bundle.editions.map((edition) => ({
    id: edition.id, course_id: bundle.course.id, slug: edition.slug, label: edition.label, year: edition.year, position: edition.position,
    variant_kind: edition.variant?.kind ?? null, variant_label: edition.variant?.label ?? null, language: edition.language ?? null,
  })));
  const lessons: LessonWrite[] = bundles.flatMap((bundle) => bundle.lessons.map((lesson) => ({
    id: lesson.id, course_id: bundle.course.id, edition_id: lesson.editionId, slug: lesson.slug, title: lesson.title,
    position: lesson.position, youtube_id: lesson.youtubeId, duration_seconds: Math.round(lesson.durationSeconds), part: lesson.part,
  })));
  const texts: TextWrite[] = bundles.flatMap((bundle) => bundle.texts.map((text) => ({
    entity_kind: text.entityKind, entity_id: text.entityId, field: text.field, text: text.text,
    approved: text.approved, approved_by: text.approvedBy, approved_at: text.approvedAt,
  })));
  const homes: HomeWrite[] = bundles.flatMap((bundle) => bundle.home ? [{ row_id: bundle.home.rowId, course_id: bundle.course.id, expected_revision: bundle.home.expectedRevision }] : []);
  await assertHomePlacements(db, bundles, refs);
  await db.query(`INSERT INTO authors (id, slug, name, monogram, kind)
    SELECT DISTINCT ON (author_id) author_id, author_slug, author_name, author_monogram, author_kind
    FROM jsonb_to_recordset($1::jsonb) AS a(author_id text, author_slug text, author_name text, author_monogram text, author_kind text)
    ORDER BY author_id
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, monogram = EXCLUDED.monogram, updated_at = now()`, [JSON.stringify(courses)]);
  await db.query(`WITH incoming AS (
      SELECT * FROM jsonb_to_recordset($1::jsonb) AS c(${COURSE_SQL})
    ), updated AS (
      UPDATE courses AS existing SET
        title = incoming.title, lesson_noun = incoming.lesson_noun, legacy = jsonb_build_object('bundleSha256', incoming.hash), updated_at = now(),
        language_label = CASE WHEN incoming.set_language THEN coalesce(incoming.language_label, existing.language_label) ELSE existing.language_label END,
        area_id = CASE WHEN incoming.set_area THEN incoming.area_id ELSE existing.area_id END,
        subarea_id = CASE WHEN incoming.set_subarea THEN incoming.subarea_id ELSE existing.subarea_id END,
        license_code = CASE WHEN incoming.set_license THEN incoming.license_code ELSE existing.license_code END,
        source_id = CASE WHEN incoming.set_source THEN incoming.source_id ELSE existing.source_id END,
        attribution_text = CASE WHEN incoming.set_attribution THEN incoming.attribution_text ELSE existing.attribution_text END,
        canonical_url = CASE WHEN incoming.set_canonical THEN incoming.canonical_url ELSE existing.canonical_url END,
        rights_status = CASE WHEN incoming.set_rights THEN coalesce(incoming.rights_status, existing.rights_status) ELSE existing.rights_status END,
        cover_from = incoming.cover_from,
        shared_with = incoming.shared_with
      FROM incoming WHERE existing.id = incoming.id
      RETURNING existing.id
    )
    INSERT INTO courses (id, slug, author_id, title, lesson_noun, language_label, status, legacy, area_id, subarea_id, license_code, source_id, attribution_text, canonical_url, rights_status, cover_from, shared_with)
    SELECT id, slug, author_id, title, lesson_noun, coalesce(language_label, 'English'), 'draft', jsonb_build_object('bundleSha256', hash),
      area_id, subarea_id, license_code, source_id, attribution_text, canonical_url, coalesce(rights_status, 'unverified'), cover_from, shared_with
    FROM incoming WHERE id NOT IN (SELECT id FROM updated)`, [JSON.stringify(courses)]);
  if (editions.length > EXTENT.empty) {
    await db.query(`INSERT INTO course_editions (id, course_id, slug, label, year, position, variant_kind, variant_label, language)
      SELECT id, course_id, slug, label, year, position, variant_kind, variant_label, language
      FROM jsonb_to_recordset($1::jsonb) AS e(id text, course_id text, slug text, label text, year int, position int, variant_kind text, variant_label text, language text)
      ON CONFLICT (id) DO NOTHING`, [JSON.stringify(editions)]);
  }
  if (lessons.length > EXTENT.empty) {
    await db.query(`WITH incoming AS (
        SELECT * FROM jsonb_to_recordset($1::jsonb) AS l(id text, course_id text, edition_id text, slug text, title text, position int, youtube_id text, duration_seconds int, part text)
      ), inserted AS (
        INSERT INTO lessons (id, course_id, edition_id, part, slug, position, kind, youtube_title, duration_seconds)
        SELECT id, course_id, edition_id, part, slug, position, 'lecture', title, duration_seconds FROM incoming
        ON CONFLICT (id) DO NOTHING
        RETURNING id
      )
      INSERT INTO lesson_videos (lesson_id, course_id, provider, external_id, status, checked_at, checked_by)
      SELECT i.id, incoming.course_id, $3, incoming.youtube_id, 'ok', $2::timestamptz, 'bundle'
      FROM inserted i JOIN incoming ON incoming.id = i.id`, [JSON.stringify(lessons), checkedAt, catalogVideoProvider()]);
  }
  if (texts.length > EXTENT.empty) {
    await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence, status, approved_by, approved_at, approved_sha256)
      SELECT entity_kind, entity_id, field, text, 'manual', 'bundle', 'high',
        CASE WHEN approved THEN 'approved' ELSE 'draft' END,
        CASE WHEN approved THEN approved_by ELSE NULL END,
        CASE WHEN approved THEN approved_at::timestamptz ELSE NULL END,
        CASE WHEN approved THEN catalog_text_sha256(text) ELSE NULL END
      FROM jsonb_to_recordset($1::jsonb) AS t(entity_kind text, entity_id text, field text, text text, approved boolean, approved_by text, approved_at text)
      ON CONFLICT (entity_kind, entity_id, field, locale) DO UPDATE SET
        text = EXCLUDED.text, status = EXCLUDED.status, approved_by = EXCLUDED.approved_by, approved_at = EXCLUDED.approved_at,
        approved_sha256 = EXCLUDED.approved_sha256, updated_at = now()`, [JSON.stringify(texts)]);
  }
  if (homes.length > EXTENT.empty) {
    await db.query(`INSERT INTO home_row_items (row_id, course_id, position)
      SELECT i.row_id, i.course_id, coalesce((SELECT max(h.position) FROM home_row_items h WHERE h.row_id = i.row_id), 0) + row_number() OVER (PARTITION BY i.row_id ORDER BY i.course_id)
      FROM jsonb_to_recordset($1::jsonb) AS i(row_id text, course_id text)
      ON CONFLICT (row_id, course_id) DO NOTHING`, [JSON.stringify(homes)]);
    await adoptRowInstitutions(db, [...new Set(homes.map((home) => home.row_id))]);
  }
}

export async function openShipBatch(db: Queryable, hash: string, draft: boolean, allowOrphan: boolean, note: string | null, chunks: number): Promise<void> {
  await db.query(`INSERT INTO catalog_ship_batches (content_hash, status, draft, allow_orphan, note, chunk_count)
    VALUES ($1, 'open', $2, $3, $4, $5) ON CONFLICT (content_hash) DO NOTHING`, [hash, draft, allowOrphan, note, chunks]);
}

export async function readShipBatchRow(db: Queryable, hash: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT status, draft, allow_orphan, note, chunk_count, result FROM catalog_ship_batches WHERE content_hash = $1 FOR UPDATE", [hash]);
  return rows[EXTENT.first];
}

export async function saveShipChunk(db: Queryable, hash: string, chunk: number, bundles: string): Promise<void> {
  await db.query(`INSERT INTO catalog_ship_chunks (content_hash, chunk_index, bundles) VALUES ($1, $2, $3::jsonb)
    ON CONFLICT (content_hash, chunk_index) DO UPDATE SET bundles = EXCLUDED.bundles`, [hash, chunk, bundles]);
}

export async function readShipChunks(db: Queryable, hash: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT chunk_index, bundles FROM catalog_ship_chunks WHERE content_hash = $1 ORDER BY chunk_index", [hash]);
  return rows;
}

export async function publishShipCourses(db: Queryable, ids: readonly string[]): Promise<void> {
  await db.query("UPDATE courses SET status = 'published', published_at = coalesce(published_at, now()), revision = revision + 1, updated_at = now() WHERE id = ANY($1::text[]) AND status IN ('draft', 'review')", [ids]);
}

export async function commitShipBatch(db: Queryable, hash: string, result: string): Promise<void> {
  await db.query("UPDATE catalog_ship_batches SET status = 'committed', result = $2::jsonb, updated_at = now() WHERE content_hash = $1", [hash, result]);
}

export async function courseIdForSlug(db: Queryable, slug: string, courseId: string | null): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM courses WHERE slug = $1 AND id IS DISTINCT FROM $2", [slug, courseId]);
  return rows[EXTENT.first];
}

export async function selectCourseRow(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT * FROM courses WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function subjectAreaExists(db: Queryable, area: string): Promise<boolean> {
  return Boolean((await db.query("SELECT 1 FROM subject_areas WHERE id = $1", [area])).rows[EXTENT.first]);
}

export async function selectSubareaArea(db: Queryable, subarea: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT area_id FROM subject_subareas WHERE id = $1", [subarea]);
  return rows[EXTENT.first];
}

export async function selectLessonSlugRows(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT slug, visible FROM lessons WHERE course_id = $1 ORDER BY edition_id, position", [courseId]);
  return rows;
}

export async function selectStaleYoutubeVideos(db: Queryable, courseId: string, threshold: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query(`SELECT v.lesson_id, v.external_id FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id
    WHERE l.course_id = $1 AND l.visible AND v.provider = $3 AND v.checked_at < $2 ORDER BY l.position`, [courseId, threshold, catalogVideoProvider()]);
  return rows;
}

export async function selectCourseStatus(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT status FROM courses WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function selectKnownCourseIds(db: Queryable, ids: readonly string[]): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM courses WHERE id = ANY($1::text[])", [ids]);
  return rows;
}

export async function lockCoursesForClassification(db: Queryable, ids: readonly string[]): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, area_id, subarea_id, status FROM courses WHERE id = ANY($1::text[]) ORDER BY id FOR UPDATE", [ids]);
  return rows;
}

export async function lockReplacementCourseStatus(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT status FROM courses WHERE id = $1 FOR UPDATE", [id]);
  return rows[EXTENT.first];
}

export async function insertCourseRow(db: Queryable, values: readonly unknown[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`INSERT INTO courses (slug, author_id, title, lesson_noun, language_label, source_id, license_code, canonical_url, attribution_text, cover_from, shared_with)
    VALUES ($1, $2, $3, coalesce($4, 'Lecture'), coalesce($5, 'English'), $6, $7, $8, $9, $10, '{}'::text[]) RETURNING *`, [...values]);
  return rows[EXTENT.first];
}

export async function updateCourseColumns(db: Queryable, id: string, columns: readonly string[], values: readonly unknown[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`UPDATE courses SET ${columns.map((column, index) => `${column} = $${String(index + 2)}`).join(", ")}, revision = revision + 1, updated_at = now()
      WHERE id = $1 RETURNING *`, [id, ...values]);
  return rows[EXTENT.first];
}

export async function retargetRedirectPrefix(db: Queryable, oldPrefix: string, newPrefix: string, oldLength: number): Promise<void> {
  await db.query("UPDATE slug_redirects SET to_path = $2 || substr(to_path, $3) WHERE to_path = $1 OR to_path LIKE $1 || '/%'", [oldPrefix, newPrefix, oldLength]);
}

export async function updateCourseStatusRow(db: Queryable, id: string, status: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("UPDATE courses SET status = $2, revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *", [id, status]);
  return rows[EXTENT.first];
}

export async function markLessonVideoChecked(db: Queryable, lessonId: string, youtubeId: string, checkedAt: string, checker: string): Promise<void> {
  await db.query("UPDATE lesson_videos SET status = 'ok', checked_at = $3, checked_by = $4 WHERE lesson_id = $1 AND provider = $5 AND external_id = $2", [lessonId, youtubeId, checkedAt, checker, catalogVideoProvider()]);
}

export async function publishOneCourse(db: Queryable, id: string): Promise<void> {
  await db.query("UPDATE courses SET status = 'published', published_at = coalesce(published_at, now()), revision = revision + 1, updated_at = now() WHERE id = $1", [id]);
}

export async function publishPromotedCourses(db: Queryable, ids: readonly string[]): Promise<void> {
  await db.query("UPDATE courses SET status = 'published', published_at = coalesce(published_at, now()), revision = revision + 1, updated_at = now() WHERE id = ANY($1::text[])", [ids]);
}

export async function updateCourseAreaColumns(db: Queryable, id: string, columns: readonly string[], values: readonly unknown[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`UPDATE courses SET ${columns.map((column, index) => `${column} = $${String(index + 2)}`).join(", ")}, revision = revision + 1, updated_at = now()
        WHERE id = $1 RETURNING area_id, subarea_id`, [id, ...values]);
  return rows[EXTENT.first];
}

export async function clearCourseFeatured(db: Queryable, id: string): Promise<void> {
  await db.query("UPDATE courses SET featured = false WHERE id = $1", [id]);
}

export async function setCourseFeatured(db: Queryable, id: string): Promise<void> {
  await db.query("UPDATE courses SET featured = true, revision = revision + 1, updated_at = now() WHERE id = $1", [id]);
}

export async function setCourseStatusClearFeatured(db: Queryable, id: string, status: string): Promise<void> {
  await db.query("UPDATE courses SET status = $2, featured = false, revision = revision + 1, updated_at = now() WHERE id = $1", [id, status]);
}

export async function selectVideoOwnerRow(db: Queryable, youtubeId: string, courseId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT v.lesson_id, l.course_id FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id WHERE v.provider = $3 AND v.external_id = $1 AND l.course_id = $2", [youtubeId, courseId, catalogVideoProvider()]);
  return rows[EXTENT.first];
}

export async function selectSharedVideoCourses(db: Queryable, youtubeId: string, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT l.course_id, c.shared_with FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id JOIN courses c ON c.id = l.course_id WHERE v.provider = $3 AND v.external_id = $1 AND l.course_id <> $2", [youtubeId, courseId, catalogVideoProvider()]);
  return rows;
}

export async function selectCourseSharedWith(db: Queryable, courseId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT shared_with FROM courses WHERE id = $1", [courseId]);
  return rows[EXTENT.first];
}

export async function selectCourseSlug(db: Queryable, courseId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT slug FROM courses WHERE id = $1", [courseId]);
  return rows[EXTENT.first];
}

/** Course, institution and edition facts the lesson address needs when a lesson is added without a slug. */
export async function selectLessonAddress(db: Queryable, courseId: string, editionId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`SELECT c.slug AS course_slug, c.title AS course_title, a.name AS institution,
    e.label AS edition_label, e.term AS edition_term, e.year AS edition_year
    FROM courses c
    LEFT JOIN authors a ON a.id = c.institution_id
    JOIN course_editions e ON e.id = $2 AND e.course_id = c.id
    WHERE c.id = $1`, [courseId, editionId]);
  return rows[EXTENT.first];
}

export async function selectLessonSlugs(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT slug FROM lessons WHERE course_id = $1", [courseId]);
  return rows;
}

export async function countLessonsInEdition(db: Queryable, editionId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM lessons WHERE edition_id = $1", [editionId]);
  return rows[EXTENT.first];
}

export async function selectLessonIdsInEdition(db: Queryable, editionId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM lessons WHERE edition_id = $1 ORDER BY position", [editionId]);
  return rows;
}

export async function selectCoursePresence(db: Queryable, courseId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM courses WHERE id = $1", [courseId]);
  return rows[EXTENT.first];
}

export async function selectEditionIds(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM course_editions WHERE course_id = $1 ORDER BY position", [courseId]);
  return rows;
}

export async function selectLessonCourseId(db: Queryable, lessonId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT course_id FROM lessons WHERE id = $1", [lessonId]);
  return rows[EXTENT.first];
}

export async function selectNextLessonPosition(db: Queryable, editionId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT coalesce(max(position), 0)::int + 1 AS next FROM lessons WHERE edition_id = $1", [editionId]);
  return rows[EXTENT.first];
}

export async function selectLessonSlugClash(db: Queryable, courseId: string, slug: string, lessonId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM lessons WHERE course_id = $1 AND slug = $2 AND id <> $3", [courseId, slug, lessonId]);
  return rows[EXTENT.first];
}

export async function selectRelatedRedirects(db: Queryable, fromPath: string, toPath: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT from_path, to_path FROM slug_redirects WHERE from_path = $1 OR to_path = $2 ORDER BY from_path FOR UPDATE", [fromPath, toPath]);
  return rows;
}

export async function shiftLessonPositions(db: Queryable, editionId: string, position: number): Promise<void> {
  await db.query("UPDATE lessons SET position = -(position + 1) WHERE edition_id = $1 AND position >= $2", [editionId, position]);
}

export async function restoreLessonPositions(db: Queryable, editionId: string): Promise<void> {
  await db.query("UPDATE lessons SET position = -position WHERE edition_id = $1 AND position < 0", [editionId]);
}

export async function insertLessonRow(db: Queryable, columns: readonly string[], values: unknown[]): Promise<Record<string, unknown> | undefined> {
  const placeholders = values.map((_, index) => (columns[index] === "kind" ? `coalesce($${String(index + 1)}, 'lecture')` : `$${String(index + 1)}`));
  const { rows } = await db.query(`INSERT INTO lessons (${columns.join(", ")}) VALUES (${placeholders.join(", ")}) RETURNING *`, values);
  return rows[EXTENT.first];
}

export async function insertLessonVideo(db: Queryable, lessonId: string, youtubeId: string, channelId: string | null, checkedAt: string, checkedBy: string): Promise<void> {
  await db.query(`INSERT INTO lesson_videos (lesson_id, provider, external_id, status, channel_id, checked_at, checked_by) VALUES ($1, $6, $2, 'ok', $3, $4, $5)`,
    [lessonId, youtubeId, channelId, checkedAt, checkedBy, catalogVideoProvider()]);
}

export async function insertLessonDisplayTitle(db: Queryable, lessonId: string, text: string, source: string, sourceRef: string, confidence: string): Promise<void> {
  await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence) VALUES ('lesson', $1, 'displayTitle', $2, $3, $4, $5)`,
    [lessonId, text, source, sourceRef, confidence]);
}

export async function deleteRedirectsByFrom(db: Queryable, fromPaths: readonly string[]): Promise<void> {
  await db.query("DELETE FROM slug_redirects WHERE from_path = ANY($1::text[])", [[...fromPaths]]);
}

export async function retargetRedirectTo(db: Queryable, fromPath: string, toPath: string): Promise<void> {
  await db.query("UPDATE slug_redirects SET to_path = $2 WHERE to_path = $1", [fromPath, toPath]);
}

export async function upsertRedirect(db: Queryable, fromPath: string, toPath: string): Promise<void> {
  await db.query("INSERT INTO slug_redirects (from_path, to_path) VALUES ($1, $2) ON CONFLICT (from_path) DO UPDATE SET to_path = EXCLUDED.to_path", [fromPath, toPath]);
}

export async function updateLessonColumns(db: Queryable, id: string, columns: readonly string[], values: readonly unknown[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`UPDATE lessons SET ${columns.map((column, index) => `${column} = $${String(index + 2)}`).join(", ")}, revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *`,
    [id, ...values]);
  return rows[EXTENT.first];
}

export async function selectAuthorList(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query(`SELECT a.*, (SELECT count(*)::int FROM courses c WHERE a.id IN (c.author_id, c.institution_id)) AS courses,
    (SELECT count(*)::int FROM home_rows r WHERE a.id IN (r.author_id, r.institution_id)) AS rows FROM authors a ORDER BY a.id`);
  return rows;
}

export async function selectAuthorIdForSlug(db: Queryable, slug: string, id: string | null): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM authors WHERE slug = $1 AND id IS DISTINCT FROM $2", [slug, id]);
  return rows[EXTENT.first];
}

export async function selectVisibleAuthorHomeRows(db: Queryable, id: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM home_rows WHERE kind = 'author' AND visible AND author_id = $1 ORDER BY position", [id]);
  return rows;
}

export async function selectAuthorCourseIds(db: Queryable, id: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM courses WHERE $1 IN (author_id, institution_id) ORDER BY id", [id]);
  return rows;
}

export async function selectAuthorHomeRowIds(db: Queryable, id: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM home_rows WHERE author_id = $1 OR institution_id = $1 ORDER BY id", [id]);
  return rows;
}

export async function selectAuthorRow(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT * FROM authors WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function countAuthorTexts(db: Queryable, id: string): Promise<unknown> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM catalog_texts WHERE entity_kind = 'author' AND entity_id = $1", [id]);
  return rows[EXTENT.first]?.n;
}

export async function insertAuthorRow(db: Queryable, slug: string, name: string, monogram: string, role: string | null, kind: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("INSERT INTO authors (slug, name, monogram, role, kind) VALUES ($1, $2, $3, coalesce($4, 'Lecturer'), $5) RETURNING *",
    [slug, name, monogram, role, kind]);
  return rows[EXTENT.first];
}

export async function updateAuthorColumns(db: Queryable, id: string, columns: readonly string[], values: readonly unknown[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`UPDATE authors SET ${columns.map((column, index) => `${column} = $${String(index + 2)}`).join(", ")}, revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *`,
    [id, ...values]);
  return rows[EXTENT.first];
}

export async function deleteAuthorTexts(db: Queryable, id: string): Promise<void> {
  await db.query("DELETE FROM catalog_texts WHERE entity_kind = 'author' AND entity_id = $1", [id]);
}

export async function deleteAuthorRow(db: Queryable, id: string): Promise<void> {
  await db.query("DELETE FROM authors WHERE id = $1", [id]);
}

const TEXT_ENTITY_TABLE: Readonly<Record<TextEntityKind, string>> = { course: "courses", lesson: "lessons", author: "authors" };

export async function selectTextEntityIds(db: Queryable, kind: TextEntityKind, ids: readonly string[]): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query(`SELECT id FROM ${TEXT_ENTITY_TABLE[kind]} WHERE id = ANY($1)`, [ids]);
  return rows;
}

export async function lockCatalogText(db: Queryable, kind: string, id: string, field: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT * FROM catalog_texts WHERE entity_kind = $1 AND entity_id = $2 AND field = $3 AND locale = 'en' FOR UPDATE", [kind, id, field]);
  return rows[EXTENT.first];
}

export async function selectCatalogTexts(db: Queryable, kind: string, id: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT * FROM catalog_texts WHERE entity_kind = $1 AND entity_id = $2 AND locale = 'en'", [kind, id]);
  return rows;
}

export async function updateCatalogTextProvenance(db: Queryable, kind: string, id: string, field: string, source: string, sourceRef: string, confidence: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("UPDATE catalog_texts SET source = $4, source_ref = $5, confidence = $6, updated_at = now() WHERE entity_kind = $1 AND entity_id = $2 AND field = $3 AND locale = 'en' RETURNING text_sha256, status", [kind, id, field, source, sourceRef, confidence]);
  return rows[EXTENT.first];
}

export async function upsertCatalogTextDraft(db: Queryable, kind: string, id: string, field: string, source: string, sourceRef: string, confidence: string, text: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence) VALUES ($1, $2, $3, $7, $4, $5, $6)
          ON CONFLICT (entity_kind, entity_id, field, locale) DO UPDATE SET text = EXCLUDED.text, source = EXCLUDED.source, source_ref = EXCLUDED.source_ref,
          confidence = EXCLUDED.confidence, status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL, updated_at = now() RETURNING text_sha256, status`,
  [kind, id, field, source, sourceRef, confidence, text]);
  return rows[EXTENT.first];
}

export async function approveCatalogText(db: Queryable, kind: string, id: string, field: string, approvedBy: string): Promise<void> {
  await db.query(`UPDATE catalog_texts SET status = 'approved', approved_by = $4, approved_at = now(), approved_sha256 = text_sha256, updated_at = now()
        WHERE entity_kind = $1 AND entity_id = $2 AND field = $3 AND locale = 'en'`, [kind, id, field, approvedBy]);
}

export async function revokeCatalogText(db: Queryable, kind: string, id: string, field: string): Promise<void> {
  await db.query(`UPDATE catalog_texts SET status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL, updated_at = now()
        WHERE entity_kind = $1 AND entity_id = $2 AND field = $3 AND locale = 'en'`, [kind, id, field]);
}

export async function selectHomeRevision(db: Queryable): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT revision FROM catalog_home");
  return rows[EXTENT.first];
}

export async function selectFeaturedPublishedCourse(db: Queryable): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM courses WHERE featured AND status = 'published'");
  return rows[EXTENT.first];
}

export async function selectHomeRows(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, kind, title, author_id, institution_id, visible, position, cover, full_name, place FROM home_rows ORDER BY position");
  return rows;
}

export async function selectHomeRowItems(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT row_id, course_id FROM home_row_items ORDER BY row_id, position");
  return rows;
}

export async function lockHomeRevision(db: Queryable): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT revision FROM catalog_home FOR UPDATE");
  return rows[EXTENT.first];
}

export async function selectCourseInstitutionRows(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, status, institution_id FROM courses");
  return rows;
}

export async function selectAuthorKindRows(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, kind FROM authors");
  return rows;
}

export async function selectAuthorCoverFlags(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, cover IS NOT NULL AS has_cover FROM authors");
  return rows;
}

export async function openHomeDryRun(db: Queryable): Promise<void> {
  await db.query("SAVEPOINT home_dry_run");
}

export async function deleteHomeRows(db: Queryable): Promise<void> {
  await db.query("DELETE FROM home_rows");
}

export async function insertHomeRow(db: Queryable, values: readonly unknown[]): Promise<void> {
  await db.query("INSERT INTO home_rows (id, kind, author_id, institution_id, title, position, visible, cover, full_name, place) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)", [...values]);
}

export async function insertHomeRowItem(db: Queryable, rowId: string, courseId: string, position: number): Promise<void> {
  await db.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ($1, $2, $3)", [rowId, courseId, position]);
}

export async function clearFeaturedExcept(db: Queryable, id: string | null): Promise<void> {
  await db.query("UPDATE courses SET featured = false, revision = revision + 1, updated_at = now() WHERE featured AND id IS DISTINCT FROM $1", [id]);
}

export async function bumpHomeRevision(db: Queryable): Promise<void> {
  await db.query("UPDATE catalog_home SET revision = revision + 1, updated_at = now()");
}

export async function setConstraintsImmediate(db: Queryable): Promise<void> {
  await db.query("SET CONSTRAINTS ALL IMMEDIATE");
}

export async function rollbackHomeDryRun(db: Queryable): Promise<void> {
  await db.query("ROLLBACK TO SAVEPOINT home_dry_run");
}

export async function setConstraintsDeferred(db: Queryable): Promise<void> {
  await db.query("SET CONSTRAINTS ALL DEFERRED");
}

async function counted(db: Queryable, sql: string, values: unknown[]): Promise<number> {
  const { rows } = await db.query(sql, values);
  return Number(rows[EXTENT.first]?.n ?? 0);
}

export async function selectCatalogCoverReferences(db: Queryable, keys: readonly string[]): Promise<string[]> {
  if (keys.length === EXTENT.empty) return [];
  const { rows } = await db.query(`SELECT candidate AS pathname FROM unnest($1::text[]) candidate
      WHERE EXISTS (SELECT 1 FROM authors WHERE strpos(cover::text, candidate) > 0)
        OR EXISTS (SELECT 1 FROM home_rows WHERE strpos(cover::text, candidate) > 0)
    ORDER BY 1`, [keys]);
  return rows.map((row) => String(row.pathname));
}

export async function selectLessonIdsByCourse(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM lessons WHERE course_id = $1 ORDER BY position", [courseId]);
  return rows;
}

export function countCourseEditions(db: Queryable, courseId: string): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM course_editions WHERE course_id = $1", [courseId]);
}

export function countVideosForLessons(db: Queryable, lessonIds: readonly string[]): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM lesson_videos WHERE lesson_id = ANY($1)", [lessonIds]);
}

export function countCourseAndLessonTexts(db: Queryable, courseId: string, lessonIds: readonly string[]): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM catalog_texts WHERE (entity_kind = 'course' AND entity_id = $1) OR (entity_kind = 'lesson' AND entity_id = ANY($2))", [courseId, lessonIds]);
}

export function countHomeItemsForCourse(db: Queryable, courseId: string): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM home_row_items WHERE course_id = $1", [courseId]);
}

export async function selectCoursePurgeOwners(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT c.subarea_id, l.id AS lesson_id FROM courses c LEFT JOIN lessons l ON l.course_id = c.id WHERE c.id = $1", [courseId]);
  return rows;
}

export async function selectLessonIdsOfCourse(db: Queryable, courseId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id FROM lessons WHERE course_id = $1", [courseId]);
  return rows;
}

export async function selectCourseSlugStatus(db: Queryable, courseId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT slug, status FROM courses WHERE id = $1", [courseId]);
  return rows[EXTENT.first];
}

export function countOtherVisibleLessons(db: Queryable, courseId: string, lessonId: string): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM lessons WHERE course_id = $1 AND visible AND id <> $2", [courseId, lessonId]);
}

export function countLessonTexts(db: Queryable, lessonId: string): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM catalog_texts WHERE entity_kind = 'lesson' AND entity_id = $1", [lessonId]);
}

export async function selectLessonRow(db: Queryable, lessonId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT * FROM lessons WHERE id = $1", [lessonId]);
  return rows[EXTENT.first];
}

export async function selectEditionLessonRows(db: Queryable, editionId: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, slug, visible FROM lessons WHERE edition_id = $1 ORDER BY position", [editionId]);
  return rows;
}

export function countVisibleLessonsOutsideEdition(db: Queryable, courseId: string, editionId: string): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM lessons WHERE course_id = $1 AND visible AND edition_id <> $2", [courseId, editionId]);
}

export function countTextsForLessons(db: Queryable, lessonIds: readonly string[]): Promise<number> {
  return counted(db, "SELECT count(*)::int AS n FROM catalog_texts WHERE entity_kind = 'lesson' AND entity_id = ANY($1)", [lessonIds]);
}

export async function selectEditionRow(db: Queryable, editionId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT * FROM course_editions WHERE id = $1", [editionId]);
  return rows[EXTENT.first];
}

export async function archiveCourseRow(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("UPDATE courses SET status = 'archived', revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *", [id]);
  return rows[EXTENT.first];
}

export async function deleteHomeItemsForCourse(db: Queryable, courseId: string): Promise<void> {
  await db.query("DELETE FROM home_row_items WHERE course_id = $1", [courseId]);
}

export async function deleteCourseAndLessonTextRows(db: Queryable, courseId: string, lessonIds: readonly string[]): Promise<void> {
  await db.query("DELETE FROM catalog_texts WHERE (entity_kind = 'course' AND entity_id = $1) OR (entity_kind = 'lesson' AND entity_id = ANY($2))", [courseId, lessonIds]);
}

export async function deleteVideosForLessons(db: Queryable, lessonIds: readonly string[]): Promise<void> {
  await db.query("DELETE FROM lesson_videos WHERE lesson_id = ANY($1)", [lessonIds]);
}

export async function deleteLessonsByCourse(db: Queryable, courseId: string): Promise<void> {
  await db.query("DELETE FROM lessons WHERE course_id = $1", [courseId]);
}

export async function deleteEditionsByCourse(db: Queryable, courseId: string): Promise<void> {
  await db.query("DELETE FROM course_editions WHERE course_id = $1", [courseId]);
}

export async function deleteRedirectsUnder(db: Queryable, path: string): Promise<void> {
  await db.query("DELETE FROM slug_redirects WHERE to_path = $1 OR to_path LIKE $1 || '/%'", [path]);
}

export async function deleteCourseById(db: Queryable, id: string): Promise<void> {
  await db.query("DELETE FROM courses WHERE id = $1", [id]);
}

export async function deleteLessonTextRows(db: Queryable, lessonId: string): Promise<void> {
  await db.query("DELETE FROM catalog_texts WHERE entity_kind = 'lesson' AND entity_id = $1", [lessonId]);
}

export async function deleteVideoForLesson(db: Queryable, lessonId: string): Promise<void> {
  await db.query("DELETE FROM lesson_videos WHERE lesson_id = $1", [lessonId]);
}

export async function deleteLessonById(db: Queryable, lessonId: string): Promise<void> {
  await db.query("DELETE FROM lessons WHERE id = $1", [lessonId]);
}

export async function deleteTextsForLessonIds(db: Queryable, lessonIds: readonly string[]): Promise<void> {
  await db.query("DELETE FROM catalog_texts WHERE entity_kind = 'lesson' AND entity_id = ANY($1)", [lessonIds]);
}

export async function deleteLessonsByEdition(db: Queryable, editionId: string): Promise<void> {
  await db.query("DELETE FROM lessons WHERE edition_id = $1", [editionId]);
}

export async function deleteEditionById(db: Queryable, editionId: string): Promise<void> {
  await db.query("DELETE FROM course_editions WHERE id = $1", [editionId]);
}

export async function selectBundleHomeRow(db: Queryable, rowId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT r.id, r.kind, r.visible, r.cover, r.author_id, a.id AS author, a.cover IS NOT NULL AS author_cover FROM home_rows r LEFT JOIN authors a ON a.id = r.author_id WHERE r.id = $1", [rowId]);
  return rows[EXTENT.first];
}

export async function selectCourseLegacyStatus(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT legacy, status FROM courses WHERE id = $1 FOR UPDATE", [id]);
  return rows[EXTENT.first];
}

export async function selectLessonId(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM lessons WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function selectHomeRowId(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT id FROM home_rows WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function selectNextHomeItemPosition(db: Queryable, rowId: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT coalesce(max(position), 0) + 1 AS n FROM home_row_items WHERE row_id = $1", [rowId]);
  return rows[EXTENT.first];
}

function isAuthorSlugRace(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const pg = error as { code?: unknown; constraint?: unknown };
  return pg.code === "23505" && pg.constraint === "authors_slug_unique";
}

export async function insertBundleAudit(db: Queryable, actor: string, requestId: string, courseId: string, after: string): Promise<void> {
  await db.query(`INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, after)
    VALUES ($1, $2, 'course.bundle', 'course', $3, $4::jsonb)`, [actor, requestId, courseId, after]);
}

/** Two bundle applies can insert the same author at once (`ship --batch` uses two workers).
 * `ON CONFLICT (id)` does not absorb a speculative collision on `authors_slug_unique`.
 * The loser retries after a savepoint: the other transaction already holds the row, so
 * the second insert waits and then updates that id.
 */
export async function upsertBundleAuthor(db: Queryable, id: string, slug: string, name: string, monogram: string, kind: string): Promise<void> {
  const values = [id, slug, name, monogram, kind];
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await db.query("SAVEPOINT author_upsert");
    try {
      await db.query(`INSERT INTO authors (id, slug, name, monogram, kind) VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, monogram = EXCLUDED.monogram`, values);
      await db.query("RELEASE SAVEPOINT author_upsert");
      return;
    } catch (error) {
      if (!isAuthorSlugRace(error) || attempt === 2) throw error;
      await db.query("ROLLBACK TO SAVEPOINT author_upsert");
    }
  }
}

export async function upsertBundleCourse(db: Queryable, columns: readonly string[], values: unknown[], metaColumns: readonly string[]): Promise<void> {
  const placeholders = values.map((_, index) => {
    const column = columns[index];
    if (column === "legacy") return `$${String(index + 1)}::jsonb`;
    if (column === "shared_with") return `$${String(index + 1)}::text[]`;
    return `$${String(index + 1)}`;
  });
  const updates = ["title = EXCLUDED.title", "lesson_noun = EXCLUDED.lesson_noun", "legacy = EXCLUDED.legacy", "updated_at = now()", ...metaColumns.map((column) => `${column} = EXCLUDED.${column}`)];
  await db.query(`INSERT INTO courses (${columns.join(", ")}) VALUES (${placeholders.join(", ")}) ON CONFLICT (id) DO UPDATE SET ${updates.join(", ")}`, values);
}

export async function insertBundleEdition(db: Queryable, values: readonly unknown[]): Promise<void> {
  await db.query(`INSERT INTO course_editions (id, course_id, slug, label, year, position, variant_kind, variant_label, language)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      ON CONFLICT (id) DO NOTHING`, [...values]);
}

export async function insertApprovedBundleText(db: Queryable, kind: string, id: string, field: string, text: string, approvedBy: string, approvedAt: string): Promise<void> {
  await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence, status, approved_by, approved_at, approved_sha256)
        VALUES ($1, $2, $3, $4, 'manual', 'bundle', 'high', 'approved', $5, $6, catalog_text_sha256($4))
        ON CONFLICT (entity_kind, entity_id, field, locale) DO UPDATE SET text = EXCLUDED.text, status = EXCLUDED.status, approved_by = EXCLUDED.approved_by, approved_at = EXCLUDED.approved_at, approved_sha256 = catalog_text_sha256(EXCLUDED.text), updated_at = now()`,
  [kind, id, field, text, approvedBy, approvedAt]);
}

export async function insertDraftBundleText(db: Queryable, kind: string, id: string, field: string, text: string): Promise<void> {
  await db.query(`INSERT INTO catalog_texts (entity_kind, entity_id, field, text, source, source_ref, confidence, status)
        VALUES ($1, $2, $3, $4, 'manual', 'bundle', 'high', 'draft')
        ON CONFLICT (entity_kind, entity_id, field, locale) DO UPDATE SET text = EXCLUDED.text, status = 'draft', approved_by = NULL, approved_at = NULL, approved_sha256 = NULL, updated_at = now()`,
  [kind, id, field, text]);
}

export async function insertHomeItemIgnore(db: Queryable, rowId: string, courseId: string, position: number): Promise<void> {
  await db.query(`INSERT INTO home_row_items (row_id, course_id, position) VALUES ($1, $2, $3) ON CONFLICT (row_id, course_id) DO NOTHING`, [rowId, courseId, position]);
}

const BATCH_REFS_SQL = `SELECT json_build_object(
  'sources', (SELECT coalesce(json_object_agg(id, json_build_object('id', id, 'kind', kind, 'title', title, 'url', url, 'publisher', publisher, 'youtubeChannelId', youtube_channel_id)), '{}') FROM content_sources WHERE id = ANY($1::text[])),
  'authors', (SELECT coalesce(json_object_agg(id, json_build_object('slug', slug, 'name', name, 'monogram', monogram, 'kind', kind)), '{}') FROM authors WHERE id = ANY($2::text[]) OR slug = ANY($3::text[])),
  'areas', (SELECT coalesce(json_object_agg(id, json_build_object('title', title)), '{}') FROM subject_areas),
  'subareas', (SELECT coalesce(json_object_agg(id, json_build_object('areaId', area_id, 'title', title)), '{}') FROM subject_subareas),
  'homeRows', (SELECT coalesce(json_object_agg(id, json_build_object('institutionId', institution_id, 'title', title)), '{}') FROM home_rows),
  'courses', (SELECT coalesce(json_object_agg(id, json_build_object('slug', slug, 'institutionId', institution_id)), '{}') FROM courses WHERE id = ANY($4::text[]) OR slug = ANY($5::text[])),
  'licenses', (SELECT coalesce(json_agg(code), '[]') FROM licenses)
) AS refs`;

export async function selectBatchRefs(db: Queryable, sourceIds: readonly string[], authorIds: readonly string[], authorSlugs: readonly string[], courseIds: readonly string[], courseSlugs: readonly string[]): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query(BATCH_REFS_SQL, [sourceIds, authorIds, authorSlugs, courseIds, courseSlugs]);
  return rows[EXTENT.first];
}

export async function selectHomeRowPosition(db: Queryable, id: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT position FROM home_rows WHERE id = $1", [id]);
  return rows[EXTENT.first];
}

export async function selectMaxHomePosition(db: Queryable): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT coalesce(max(position), 0) AS p FROM home_rows");
  return rows[EXTENT.first];
}

export async function lockCatalogV2Batch(db: Queryable, hash: string): Promise<Record<string, unknown> | undefined> {
  const { rows } = await db.query("SELECT status, draft, allow_orphan, note, chunk_count, format, result FROM catalog_ship_batches WHERE content_hash = $1 FOR UPDATE", [hash]);
  return rows[EXTENT.first];
}

export async function selectShipChunkBundles(db: Queryable, hash: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT bundles FROM catalog_ship_chunks WHERE content_hash = $1 ORDER BY chunk_index", [hash]);
  return rows;
}

async function writeJson(db: Queryable, sql: string, rows: readonly unknown[]): Promise<void> {
  if (rows.length === EXTENT.empty) return;
  await db.query(sql, [JSON.stringify(rows)]);
}

export function upsertContentSources(db: Queryable, rows: readonly unknown[]): Promise<void> {
  return writeJson(db, `INSERT INTO content_sources (id, kind, title, publisher, url, youtube_channel_id)
    SELECT id, kind, title, publisher, url, youtube_channel_id
    FROM jsonb_to_recordset($1::jsonb) AS s(id text, kind text, title text, publisher text, url text, youtube_channel_id text)
    ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, title = EXCLUDED.title, publisher = EXCLUDED.publisher, url = EXCLUDED.url,
      youtube_channel_id = EXCLUDED.youtube_channel_id, revision = content_sources.revision + 1, updated_at = now()`, rows);
}

export function upsertBatchAuthors(db: Queryable, rows: readonly unknown[]): Promise<void> {
  return writeJson(db, `INSERT INTO authors (id, slug, name, monogram, kind)
    SELECT id, slug, name, monogram, kind FROM jsonb_to_recordset($1::jsonb) AS a(id text, slug text, name text, monogram text, kind text)
    ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name, monogram = EXCLUDED.monogram, revision = authors.revision + 1, updated_at = now()`, rows);
}

export function insertBatchLicenses(db: Queryable, rows: readonly unknown[]): Promise<void> {
  return writeJson(db, `INSERT INTO licenses (code, name, url, requires_attribution, non_commercial, share_alike, embed_only, attribution_template)
    SELECT code, name, url, requires_attribution, non_commercial, share_alike, embed_only, attribution_template
    FROM jsonb_to_recordset($1::jsonb) AS l(code text, name text, url text, requires_attribution boolean, non_commercial boolean, share_alike boolean, embed_only boolean, attribution_template text)
    ON CONFLICT (code) DO NOTHING`, rows);
}

export function upsertSubjectAreas(db: Queryable, rows: readonly unknown[]): Promise<void> {
  return writeJson(db, `INSERT INTO subject_areas (id, title, position)
    SELECT id, title, (SELECT coalesce(max(position), 0) FROM subject_areas) + row_number() OVER (ORDER BY id)
    FROM jsonb_to_recordset($1::jsonb) AS a(id text, title text)
    ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title`, rows);
}

export function upsertSubjectSubareas(db: Queryable, rows: readonly unknown[]): Promise<void> {
  return writeJson(db, `INSERT INTO subject_subareas (id, area_id, title, position)
    SELECT i.id, i.area_id, i.title, coalesce(m.position, 0) + row_number() OVER (PARTITION BY i.area_id ORDER BY i.id)
    FROM jsonb_to_recordset($1::jsonb) AS i(id text, area_id text, title text)
    LEFT JOIN (SELECT area_id, max(position) AS position FROM subject_subareas GROUP BY area_id) m ON m.area_id = i.area_id
    ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title`, rows);
}

export async function updateBatchHomeRow(db: Queryable, id: string, title: string, fullName: string | null, place: string | null, visible: boolean, cover: string): Promise<void> {
  await db.query(`UPDATE home_rows SET title = $2, full_name = $3, place = $4, visible = $5, cover = $6::jsonb,
        revision = revision + 1, updated_at = now() WHERE id = $1`, [id, title, fullName, place, visible, cover]);
}

export async function shiftHomePositions(db: Queryable, position: number): Promise<void> {
  await db.query("UPDATE home_rows SET position = position + 1000000 WHERE position > $1", [position]);
}

export async function restoreHomePositions(db: Queryable): Promise<void> {
  await db.query("UPDATE home_rows SET position = position - 999999 WHERE position > 1000000", []);
}

export async function insertCuratedHomeRow(db: Queryable, values: readonly unknown[]): Promise<void> {
  await db.query(`INSERT INTO home_rows (id, kind, institution_id, title, full_name, place, position, visible, cover)
      VALUES ($1, 'curated', $2, $3, $4, $5, $6, $7, $8::jsonb)`, [...values]);
}

export async function assignCourseInstitutions(db: Queryable, rows: string): Promise<void> {
  await db.query(`UPDATE courses c SET institution_id = i.institution_id FROM jsonb_to_recordset($1::jsonb) AS i(id text, institution_id text)
    WHERE c.id = i.id AND c.institution_id IS DISTINCT FROM i.institution_id`, [rows]);
}

export async function insertBatchPlacements(db: Queryable, rows: string): Promise<void> {
  await db.query(`INSERT INTO home_row_items (row_id, course_id, position)
      SELECT p.row_id, p.course_id, coalesce((SELECT max(h.position) FROM home_row_items h WHERE h.row_id = p.row_id), 0) + row_number() OVER (PARTITION BY p.row_id ORDER BY p.course_id)
      FROM jsonb_to_recordset($1::jsonb) AS p(row_id text, course_id text)
      ON CONFLICT (row_id, course_id) DO NOTHING`, [rows]);
}

export async function openCatalogV2Batch(db: Queryable, hash: string, draft: boolean, allowOrphan: boolean, note: string | null, chunks: number): Promise<void> {
  await db.query(`INSERT INTO catalog_ship_batches (content_hash, status, draft, allow_orphan, note, chunk_count, format)
      VALUES ($1, 'open', $2, $3, $4, $5, 'catalog-v2') ON CONFLICT (content_hash) DO NOTHING`, [hash, draft, allowOrphan, note, chunks]);
}

export async function openBatchApplySavepoint(db: Queryable): Promise<void> {
  await db.query("SAVEPOINT batch_apply");
}

export async function rollbackBatchApply(db: Queryable): Promise<void> {
  await db.query("ROLLBACK TO SAVEPOINT batch_apply");
}

export async function releaseBatchApply(db: Queryable): Promise<void> {
  await db.query("RELEASE SAVEPOINT batch_apply");
}

async function doctorRows(db: Queryable, sql: string, params?: unknown[]): Promise<Record<string, unknown>[]> {
  const { rows } = params ? await db.query(sql, params) : await db.query(sql);
  return rows;
}

export async function selectRows(db: Queryable, sql: string): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query(sql);
  return rows;
}

export async function selectCoverCourseRows(db: Queryable): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, area_id, subarea_id, cover_from FROM courses");
  return rows;
}

export async function selectCoverCourseRowsByIds(db: Queryable, ids: readonly string[]): Promise<Record<string, unknown>[]> {
  const { rows } = await db.query("SELECT id, area_id, subarea_id, cover_from FROM courses WHERE id = ANY($1)", [ids]);
  return rows;
}

export function selectOrphanTextRefs(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT t.entity_kind || ':' || t.entity_id || '.' || t.field AS ref FROM catalog_texts t
    WHERE (t.entity_kind = 'course' AND NOT EXISTS (SELECT 1 FROM courses c WHERE c.id = t.entity_id))
       OR (t.entity_kind = 'lesson' AND NOT EXISTS (SELECT 1 FROM lessons l WHERE l.id = t.entity_id))
       OR (t.entity_kind = 'author' AND NOT EXISTS (SELECT 1 FROM authors a WHERE a.id = t.entity_id)) ORDER BY 1`);
}

export function selectAllCourseIds(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, "SELECT id FROM courses");
}

export function selectAllLessonIds(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, "SELECT id FROM lessons");
}

export function selectAuthorCoverShapes(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, "SELECT id, cover->>'sha256' AS sha256, cover->>'url' AS url, (cover->>'width')::int AS width, (cover->>'height')::int AS height FROM authors WHERE cover IS NOT NULL");
}

export function selectHomeCoverShapes(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, "SELECT id, cover->>'sha256' AS sha256, cover->>'url' AS url, (cover->>'width')::int AS width, (cover->>'height')::int AS height FROM home_rows WHERE cover IS NOT NULL");
}

export function selectVideosNotOk(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT l.id || ':' || coalesce(v.status, 'missing') AS ref FROM lessons l
    JOIN courses c ON c.id = l.course_id AND c.status = 'published' LEFT JOIN lesson_videos v ON v.lesson_id = l.id AND v.provider = $1
    WHERE l.visible AND (v.status IS NULL OR v.status <> 'ok') ORDER BY 1`, [catalogVideoProvider()]);
}

export function selectOrphanEditions(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT e.course_id || '/' || e.slug AS ref FROM course_editions e
    WHERE NOT EXISTS (SELECT 1 FROM lessons l WHERE l.edition_id = e.id) ORDER BY 1`);
}

export function selectCrossCourseLessons(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT l.id || ':' || l.edition_id AS ref FROM lessons l
    JOIN course_editions e ON e.id = l.edition_id WHERE e.course_id <> l.course_id ORDER BY 1`);
}

export function selectEditionPositionGaps(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT course_id || ': ' || string_agg(position::text, ',' ORDER BY position) AS ref FROM course_editions
    GROUP BY course_id HAVING min(position) <> 1 OR max(position) <> count(*) OR count(DISTINCT position) <> count(*) ORDER BY 1`);
}

export function selectLessonPositionGaps(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT edition_id || ': ' || count(*) || ' lesson(s)' AS ref FROM lessons
    GROUP BY edition_id HAVING min(position) <> 1 OR max(position) <> count(*) OR count(DISTINCT position) <> count(*) ORDER BY 1`);
}

export function selectAmbiguousEditions(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT DISTINCT e.course_id || '/' || e.year::text AS ref FROM course_editions e
    WHERE EXISTS (SELECT 1 FROM course_editions o WHERE o.course_id = e.course_id AND o.id <> e.id AND o.year = e.year
      AND o.variant_kind IS NOT DISTINCT FROM e.variant_kind AND o.variant_label IS NOT DISTINCT FROM e.variant_label) ORDER BY 1`);
}

export function selectEditionPrefixedTitles(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT jsonb_build_object('id', t.entity_id, 'title', t.text) AS ref FROM catalog_texts t
    WHERE t.entity_kind = 'lesson' AND t.field = 'displayTitle' AND t.locale = 'en'
      AND t.text ~* '(\\[(fa|sp|su|wi)[0-9]{2}\\]|\\m(fall|spring|summer|winter) (19|20)[0-9]{2}\\M)' ORDER BY t.entity_id`);
}

export function selectBehindSequences(db: Queryable): Promise<Record<string, unknown>[]> {
  const next = (sequence: string) => `(SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END FROM ${sequence})`;
  return doctorRows(db, `SELECT s.name FROM (VALUES
      ('author_seq', (SELECT max(substring(id FROM '^author-(\\d+)$')::bigint) FROM authors), ${next("author_seq")}),
      ('course_seq', (SELECT max(substring(id FROM '^course-(\\d+)$')::bigint) FROM courses), ${next("course_seq")}),
      ('edition_seq', (SELECT max(substring(id FROM '^edition-(\\d+)$')::bigint) FROM course_editions), ${next("edition_seq")}),
      ('lesson_seq', (SELECT max(substring(id FROM '^lesson-(\\d+)$')::bigint) FROM lessons), ${next("lesson_seq")})) AS s(name, top, next)
    WHERE s.top IS NOT NULL AND s.next <= s.top ORDER BY 1`);
}

export function selectSubareaAreaMismatches(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT c.id || ':' || c.subarea_id AS ref FROM courses c
    LEFT JOIN subject_subareas s ON s.id = c.subarea_id WHERE c.subarea_id IS NOT NULL AND (c.area_id IS NULL OR s.area_id IS DISTINCT FROM c.area_id) ORDER BY 1`);
}

export function selectCoursesMissingSubarea(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT c.area_id || ': ' || count(*) AS ref FROM courses c
    WHERE c.status = 'published' AND c.subarea_id IS NULL AND EXISTS (SELECT 1 FROM subject_subareas s WHERE s.area_id = c.area_id) GROUP BY c.area_id ORDER BY count(*) DESC, 1`);
}

export function selectHomeRowsMissingCover(db: Queryable): Promise<Record<string, unknown>[]> {
  return doctorRows(db, `SELECT r.id, r.kind, r.author_id AS "authorId" FROM home_rows r LEFT JOIN authors a ON a.id = r.author_id WHERE r.visible AND ((r.kind = 'curated' AND r.cover IS NULL) OR (r.kind = 'author' AND r.author_id IS NOT NULL AND a.cover IS NULL)) ORDER BY r.position`);
}

export async function countCourseProjections(db: Queryable): Promise<number> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM catalog_course_projections");
  return Number(rows[EXTENT.first]?.n ?? 0);
}

export async function countProjectionDrift(db: Queryable): Promise<number> {
  const { rows } = await db.query(`SELECT count(*)::int AS n FROM catalog_release_index i
    JOIN catalog_releases r ON r.number = i.release_number AND r.is_active
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(i.index_json->'index'->'courses', '[]'::jsonb)) course
    WHERE NOT EXISTS (SELECT 1 FROM catalog_course_projections p WHERE p.course_id = course->>'courseId' AND p.projection_sha256 = course->>'sha256')`);
  return Number(rows[EXTENT.first]?.n ?? 0);
}

export async function countRetainedReleases(db: Queryable): Promise<number> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM catalog_releases WHERE NOT is_active");
  return Number(rows[EXTENT.first]?.n ?? 0);
}
