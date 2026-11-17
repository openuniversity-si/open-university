import type { Queryable } from "../../platform/db/uow.ts";
import type { CatalogRefs, CatalogRefsPort, RefKeys } from "../domain/rules/refs.ts";
import type { HomeRowRef } from "../domain/rules/home.ts";
import { catalogVideoProvider } from "../../playback/server/source-registry.ts";

const REFS_SQL = `SELECT json_build_object(
  'licenses', (SELECT coalesce(json_agg(code), '[]') FROM licenses WHERE code = ANY($1::text[])),
  'sources', (SELECT coalesce(json_agg(id), '[]') FROM content_sources WHERE id = ANY($2::text[])),
  'areas', (SELECT coalesce(json_agg(id), '[]') FROM subject_areas WHERE id = ANY($3::text[])),
  'subareas', (SELECT coalesce(json_agg(json_build_object('areaId', s.area_id, 'id', s.id)), '[]')
    FROM subject_subareas s JOIN unnest($4::text[], $5::text[]) AS w(area_id, id) ON s.area_id = w.area_id AND s.id = w.id),
  'authors', (SELECT coalesce(json_agg(json_build_object('id', id, 'slug', slug)), '[]') FROM authors WHERE slug = ANY($6::text[]) OR id = ANY($7::text[])),
  'courses', (SELECT coalesce(json_agg(json_build_object('id', id, 'slug', slug, 'institutionId', institution_id)), '[]') FROM courses WHERE slug = ANY($8::text[])),
  'editions', (SELECT coalesce(json_agg(json_build_object('id', id, 'courseId', course_id, 'slug', slug, 'position', position, 'year', year,
      'variant', CASE WHEN variant_kind IS NULL THEN NULL ELSE json_build_object('kind', variant_kind, 'label', variant_label) END)), '[]')
    FROM course_editions WHERE course_id = ANY($9::text[]) OR id = ANY($10::text[])),
  'videos', (SELECT coalesce(json_agg(json_build_object('lessonId', v.lesson_id, 'courseId', l.course_id, 'youtubeId', v.external_id)), '[]')
    FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id WHERE v.provider = $13 AND v.external_id = ANY($11::text[])),
  'shares', (SELECT coalesce(json_agg(json_build_object('id', id, 'sharedWith', shared_with)), '[]')
    FROM courses WHERE id = ANY($9::text[]) OR id IN (
      SELECT l.course_id FROM lesson_videos v JOIN lessons l ON l.id = v.lesson_id
      WHERE v.provider = $13 AND v.external_id = ANY($11::text[]))),
  'lessons', (SELECT coalesce(json_agg(json_build_object('id', id, 'courseId', course_id, 'slug', slug)), '[]') FROM lessons WHERE course_id = ANY($9::text[])),
  'homeRows', (SELECT coalesce(json_agg(json_build_object('id', r.id, 'kind', r.kind, 'visible', r.visible, 'hasCover', r.cover IS NOT NULL,
      'institutionId', r.institution_id, 'authorId', r.author_id, 'authorHasCover', CASE WHEN a.id IS NULL THEN NULL ELSE a.cover IS NOT NULL END)), '[]')
    FROM home_rows r LEFT JOIN authors a ON a.id = r.author_id WHERE r.id = ANY($12::text[]))
) AS refs`;

interface RefsJson {
  licenses: string[]; sources: string[]; areas: string[];
  subareas: CatalogRefs["subareas"]; authors: CatalogRefs["authors"]; courses: CatalogRefs["courses"];
  editions: CatalogRefs["editions"]; videos: CatalogRefs["videos"]; shares: CatalogRefs["shares"];
  lessons: CatalogRefs["lessons"]; homeRows: HomeRowRef[];
}

/** The rules' snapshot slice of a batch, in one query. */
export async function loadCatalogRefs(db: Queryable, keys: RefKeys): Promise<CatalogRefs> {
  const { rows } = await db.query(REFS_SQL, [
    keys.licenses, keys.sources, keys.areas, keys.subareas.map((pair) => pair[0]), keys.subareas.map((pair) => pair[1]),
    keys.authorSlugs, keys.authorIds, keys.courseSlugs, keys.courseIds, keys.editionIds, keys.youtubeIds, keys.homeRowIds,
    catalogVideoProvider(),
  ]);
  const refs = rows[0]?.refs as RefsJson;
  return { ...refs, licenses: new Set(refs.licenses), sources: new Set(refs.sources), areas: new Set(refs.areas) };
}

export function catalogRefsPort(db: Queryable): CatalogRefsPort {
  return { load: (keys) => loadCatalogRefs(db, keys) };
}
