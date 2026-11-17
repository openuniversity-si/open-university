export type MediaOwner = "institution" | "area" | "subarea" | "course" | "lesson";
export interface MediaCourse {
  readonly courseId: string;
  readonly published: boolean;
  readonly subareaId?: string;
  readonly courses?: readonly MediaCourse[];
}
export interface OwnerGraph {
  readonly courses: readonly { readonly id: string; readonly area_id?: string | null; readonly subarea_id: string | null; readonly cover_from: string; readonly status: string }[];
  readonly lessons: readonly { readonly id: string; readonly course_id: string }[];
}
export interface CatalogCoverRef { readonly ownerId: string; readonly kind: string; readonly cover: unknown }
export interface CatalogOwnersPort {
  courseOf(owner: MediaOwner, id: string): Promise<MediaCourse | undefined>;
  graph(): Promise<OwnerGraph>;
  /** courses, lessons — before media locks the asset tables. */
  lockGraph(): Promise<void>;
  /** Draft authors and home rows, plus covers of the active release, including OG. */
  inventory(): Promise<readonly CatalogCoverRef[]>;
}
