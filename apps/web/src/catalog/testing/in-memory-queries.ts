import type { CatalogReleaseIndex } from "../domain/incremental-compile.ts";
import type {
  AdminCourseFilter, AdminCoursePage, AdminCourseSummary, AuthorsDirectoryProjection, CatalogQueriesPort, CourseDetailProjection,
  ReadScope, RedirectProjection, UniversityAreaProjection, UniversityPageProjection,
} from "../ports/queries.ts";

export interface QueryFixtureRelease {
  readonly number: number;
  readonly index: CatalogReleaseIndex;
  readonly universities: readonly UniversityPageProjection[];
  readonly areas: readonly UniversityAreaProjection[];
  readonly courses: readonly CourseDetailProjection[];
  readonly authors: AuthorsDirectoryProjection;
  readonly redirects: readonly RedirectProjection[];
}

export interface QueryFixture {
  readonly releases: readonly QueryFixtureRelease[];
  readonly drafts: readonly AdminCourseSummary[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** Isolated published releases and admin drafts. Returned objects are copies. */
export function createInMemoryCatalogQueries(fixture: QueryFixture): CatalogQueriesPort {
  const releases = new Map(fixture.releases.map((release) => [release.number, clone(release)]));
  const drafts = clone(fixture.drafts);
  const releaseOf = (scope: ReadScope) => scope.preview ? null : releases.get(scope.releaseNumber) ?? null;
  return {
    getCatalogIndex(scope) {
      return Promise.resolve(clone(releaseOf(scope)?.index ?? null));
    },
    getUniversityPageProjection(slug, scope) {
      return Promise.resolve(clone(releaseOf(scope)?.universities.find((page) => page.slug === slug) ?? null));
    },
    getUniversityAreaProjection(slug, area, scope) {
      return Promise.resolve(clone(releaseOf(scope)?.areas.find((page) => page.universitySlug === slug && page.area === area) ?? null));
    },
    getCourseDetailProjection(slug, scope) {
      return Promise.resolve(clone(releaseOf(scope)?.courses.find((course) => course.slug === slug) ?? null));
    },
    getAuthorsDirectoryProjection(scope) {
      return Promise.resolve(clone(releaseOf(scope)?.authors ?? { authorIds: [] }));
    },
    resolveRedirect(path, scope) {
      return Promise.resolve(clone(releaseOf(scope)?.redirects.find((redirect) => redirect.from === path) ?? null));
    },
    getAdminCourseSummary(id) {
      const published = [...releases.values()].flatMap((release) => release.courses).find((course) => course.id === id);
      const draft = drafts.find((course) => course.id === id);
      const summary = draft ?? (published ? { id: published.id, slug: published.slug, title: published.title, status: "published", revision: 1 } : null);
      return Promise.resolve(clone(summary));
    },
    listAdminCourses(filter: AdminCourseFilter): Promise<AdminCoursePage> {
      const rows = [...drafts, ...[...releases.values()].flatMap((release) => release.courses.map((course) => ({ id: course.id, slug: course.slug, title: course.title, status: "published", revision: 1 })))];
      const filtered = rows.filter((course) => filter.status === undefined || course.status === filter.status).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
      return Promise.resolve({ courses: clone(filtered.slice(filter.offset, filter.offset + filter.limit)), total: filtered.length });
    },
  };
}
