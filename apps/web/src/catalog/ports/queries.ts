import type { CatalogReleaseIndex } from "../domain/incremental-compile.ts";

/** Public reads name a release. Preview is an authenticated scope and never shares the public cache key. */
export type ReadScope = Readonly<{ releaseNumber: number; preview: boolean }>;

export interface UniversityPageProjection {
  readonly slug: string;
  readonly title: string;
  readonly courseIds: string[];
}
export interface UniversityAreaProjection {
  readonly universitySlug: string;
  readonly area: string;
  readonly courseIds: readonly string[];
}
export interface CourseDetailProjection {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly lessonIds: readonly string[];
}
export interface AuthorsDirectoryProjection {
  readonly authorIds: readonly string[];
}
export interface RedirectProjection {
  readonly from: string;
  readonly to: string;
  readonly statusCode: 301 | 308;
}
export interface AdminCourseSummary {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly status: string;
  readonly revision: number;
}
export interface AdminCourseFilter {
  readonly status?: string;
  readonly offset: number;
  readonly limit: number;
}
export interface AdminCoursePage {
  readonly courses: readonly AdminCourseSummary[];
  readonly total: number;
}

export interface CatalogQueriesPort {
  getCatalogIndex(scope: ReadScope): Promise<CatalogReleaseIndex | null>;
  getUniversityPageProjection(slug: string, scope: ReadScope): Promise<UniversityPageProjection | null>;
  getUniversityAreaProjection(slug: string, area: string, scope: ReadScope): Promise<UniversityAreaProjection | null>;
  getCourseDetailProjection(slug: string, scope: ReadScope): Promise<CourseDetailProjection | null>;
  getAuthorsDirectoryProjection(scope: ReadScope): Promise<AuthorsDirectoryProjection>;
  resolveRedirect(path: string, scope: ReadScope): Promise<RedirectProjection | null>;
  getAdminCourseSummary(id: string): Promise<AdminCourseSummary | null>;
  listAdminCourses(filter: AdminCourseFilter): Promise<AdminCoursePage>;
}
