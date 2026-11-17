import type { Queryable } from "../../platform/db/uow.ts";
import { resolveCover } from "../domain/cover-resolve.ts";
import { activeAssetRows, activePageAssets } from "./media-gateway.ts";
import { REQUIRED_COVERS } from "../domain/rules/status.ts";
import { selectCoverCourseRows, selectCoverCourseRowsByIds } from "./table-io.ts";

/** The same cover rule used by the render: only the course's declared owner (D-031). Asset rows come from media. */
export async function activeCoverKinds(db: Queryable, courseIds?: readonly string[]): Promise<Map<string, Set<string>>> {
  const courses = courseIds === undefined ? await selectCoverCourseRows(db) : await selectCoverCourseRowsByIds(db, courseIds);
  const subareaIds = [...new Set(courses.flatMap((course) => (typeof course.subarea_id === "string" ? [course.subarea_id] : [])))];
  const areaIds = [...new Set(courses.flatMap((course) => typeof course.area_id === "string" ? [course.area_id] : []))];
  const assets = await activeAssetRows(db, courseIds === undefined ? undefined : { courseIds, subareaIds, areaIds });
  const group = (rows: Record<string, unknown>[]) => {
    const groups = new Map<string, { kind: string; variant: string }[]>();
    for (const row of rows) {
      const id = String(row.owner_id);
      const list = groups.get(id) ?? [];
      list.push({ kind: String(row.kind), variant: String(row.variant) });
      groups.set(id, list);
    }
    return groups;
  };
  const byCourse = group(assets.own);
  const bySubarea = group(assets.shared);
  const byArea = group(assets.areas);
  const kinds = new Map<string, Set<string>>();
  for (const course of courses) {
    const sources = { area: byArea.get(String(course.area_id)), course: byCourse.get(String(course.id)), subarea: bySubarea.get(String(course.subarea_id)), coverFrom: String(course.cover_from), courseId: String(course.id) };
    kinds.set(String(course.id), new Set(REQUIRED_COVERS.filter((kind) => resolveCover(sources, { target: "course", kind }))));
  }
  return kinds;
}

/** Cover kinds for courses the caller already loaded, in one media read. `resolveCover` still decides. */
export async function pageCoverKinds(db: Queryable, courses: readonly { readonly id: string; readonly areaId: string | null; readonly subareaId: string | null; readonly coverFrom: string }[]): Promise<Map<string, Set<string>>> {
  const courseIds = courses.map((course) => course.id);
  const subareaIds = [...new Set(courses.flatMap((course) => (course.subareaId === null ? [] : [course.subareaId])))];
  const areaIds = [...new Set(courses.flatMap((course) => (course.areaId === null ? [] : [course.areaId])))];
  const { rows } = await activePageAssets(db, { courseIds, subareaIds, areaIds });
  if (rows.length === 0) return new Map();
  const groups = new Map<string, { kind: string; variant: string }[]>();
  for (const row of rows) {
    const key = `${String(row.owner_kind)}:${String(row.owner_id)}`;
    const list = groups.get(key) ?? [];
    list.push({ kind: String(row.kind), variant: String(row.variant) });
    groups.set(key, list);
  }
  const kinds = new Map<string, Set<string>>();
  for (const course of courses) {
    const sources = {
      area: groups.get(`area:${course.areaId ?? ""}`),
      course: groups.get(`course:${course.id}`),
      subarea: groups.get(`subarea:${course.subareaId ?? ""}`),
      coverFrom: course.coverFrom,
      courseId: course.id,
    };
    kinds.set(course.id, new Set(REQUIRED_COVERS.filter((kind) => resolveCover(sources, { target: "course", kind }))));
  }
  return kinds;
}
