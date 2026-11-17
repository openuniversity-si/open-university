import type { MediaAsset } from "./types.ts";

/** Snapshot the server builds. The domain never calls `coverGraph`. */
export interface CoverInheritanceGraph {
  readonly courses: readonly { readonly id: string; readonly area_id?: string | null; readonly subarea_id: string | null; readonly cover_from: string }[];
  readonly lessons: readonly { readonly id: string; readonly course_id: string }[];
  readonly courseAssets: ReadonlyMap<string, readonly MediaAsset[]>;
  readonly subareaAssets: ReadonlyMap<string, readonly MediaAsset[]>;
  readonly areaAssets?: ReadonlyMap<string, readonly MediaAsset[]>;
  readonly lessonAssets: readonly MediaAsset[];
}

export function inheritedSources(graph: CoverInheritanceGraph, course: { readonly id: unknown; readonly area_id?: unknown; readonly subarea_id: unknown; readonly cover_from: unknown }) {
  return {
    area: graph.areaAssets?.get(String(course.area_id)), course: graph.courseAssets.get(String(course.id)), subarea: graph.subareaAssets.get(String(course.subarea_id)),
    coverFrom: typeof course.cover_from === "string" ? course.cover_from : undefined, courseId: String(course.id),
  };
}

