import type { PublicCatalog } from "../../src/catalog/domain/release.ts";

const omit = (value: object, keys: readonly string[]) => Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));

/** A version 2 release as version 1 wrote it: no editions, no editionId/part (old releases stay as stored, ADR-21). */
export function asReleaseV1(release: PublicCatalog): Record<string, unknown> {
  return { ...release, schemaVersion: 1, courses: release.courses.map((course) => omit(course, ["editions"])), lessons: release.lessons.map((lesson) => omit(lesson, ["editionId", "part"])) };
}

// Synthetic two-course release (no real catalog copy) for releaseSchema and catalog_releases tests.
export function releaseFixture(): PublicCatalog {
  const rights = {
    licenseCode: "cc-by-nc-sa-3.0", licenseName: "CC BY-NC-SA 3.0", licenseUrl: "https://creativecommons.org/licenses/by-nc-sa/3.0/",
    attribution: "Test Lecturer, Test Course (Test University). License: CC BY-NC-SA", canonicalUrl: "https://example.org/course",
    sourceTitle: "Test Channel", sourceUrl: "https://www.youtube.com/@test",
  };
  const edition = (courseId: string, lessons: number) => ({
    id: `${courseId}-e1`, slug: "fall-2025", label: "Fall 2025", term: "fall" as const, year: 2025, position: 1, resolution: null,
    lessonCount: lessons, durationSeconds: lessons * 3600, parts: { lectures: lessons, labs: 0 },
  });
  const course = (id: string, slug: string, featured: boolean, lessons: number) => ({
    id, slug, authorId: "author-1", title: `Original ${slug}`, displayTitle: `Display ${slug}`, shelfTitle: `Shelf ${slug}`,
    subtitle: "Subtitle", billboardDescription: "Billboard.", billboardDescriptionMobile: "Billboard mobile.",
    description: "Description.", descriptionMobile: "Description mobile.", about: null, level: "Introductory", format: "Lectures",
    languageLabel: "English", lessonNoun: "Lecture" as const, featured, rights, editions: [edition(id, lessons)],
  });
  const lesson = (id: string, courseId: string, slug: string, order: number, youtubeId: string) => ({
    id, slug, courseId, editionId: `${courseId}-e1`, part: "lectures" as const, order, kind: "lecture" as const, youtubeTitle: `Lecture ${String(order)}`, displayTitle: `Lecture ${String(order)}`,
    about: null, youtubeId, durationSeconds: 3600,
  });
  return {
    schemaVersion: 2, number: 1, publishedAt: "2026-10-10T12:00:00.000Z",
    authors: [{ id: "author-1", slug: "test-lecturer", name: "Test Lecturer", monogram: "TL", role: "Lecturer", kind: "person" }],
    courses: [course("course-1", "first-course", true, 2), course("course-2", "second-course", false, 1)],
    lessons: [
      lesson("lesson-1", "course-1", "intro", 1, "AAAAAAAAAA1"),
      lesson("lesson-2", "course-1", "next", 2, "AAAAAAAAAA2"),
      lesson("lesson-3", "course-2", "intro", 1, "AAAAAAAAAA3"),
    ],
    home: {
      featuredCourseId: "course-1",
      rows: [
        { id: "continue-watching", kind: "continue", title: "Continue Watching", courseIds: [] },
        { id: "test-lecturer", kind: "author", title: "Test Lecturer", authorId: "author-1", courseIds: ["course-1", "course-2"] },
      ],
    },
    redirects: [{ from: "/c/old-first-course", to: "/c/first-course" }],
  };
}
