import "server-only";
import { groupByOwner } from "../domain/group.ts";
import { resolveCover } from "../../catalog/domain/cover-resolve.ts";
import type { MediaAsset } from "../domain/types.ts";

export interface FakeCatalogEntry {
  readonly courses: readonly { readonly id: string; readonly areaId?: string; readonly subareaId?: string }[];
  readonly lessons: readonly { readonly id: string; readonly courseId: string }[];
}

/** Only local, gitignored bytes; this module imports no database, catalog or Blob transport. */
export class FakeMedia {
  private readonly assets: readonly MediaAsset[];
  private readonly catalog: FakeCatalogEntry;
  constructor(assets: readonly MediaAsset[] = [], catalog: FakeCatalogEntry = { courses: [], lessons: [] }) {
    this.catalog = catalog;
    this.assets = assets.map((asset) => ({ ...asset, url: asset.url.startsWith("/") ? asset.url : `/api/media/fixture/${asset.sha256}` }));
  }
  courses() { return groupByOwner(this.assets.filter((asset) => asset.ownerId.startsWith("course-"))); }
  lessons(courseId: string) {
    const course = this.catalog.courses.find((item) => item.id === courseId);
    const rows = groupByOwner(this.assets);
    const resolved: MediaAsset[] = [];
    for (const lesson of this.catalog.lessons.filter((item) => item.courseId === courseId)) {
      const own = rows.get(lesson.id) ?? [];
      resolved.push(...own);
      const asset = resolveCover({ lesson: own, area: course?.areaId ? rows.get(course.areaId) : undefined, course: rows.get(courseId), subarea: course?.subareaId ? rows.get(course.subareaId) : undefined }, { target: "lesson" });
      if (asset && !own.includes(asset)) resolved.push({ ...asset, ownerId: lesson.id, kind: "cover_16x9", variant: "default" });
    }
    return groupByOwner(resolved);
  }
}
