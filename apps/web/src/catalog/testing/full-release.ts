import type { PublicCatalog } from "../domain/release.ts";
import { FULL_CATALOG_COURSES } from "../../site/domain/site-health.ts";
import { releaseFixture } from "../../../test/fixtures/release.ts";

/** Release 133's course count, the size in the site-health definition. Tests build this in memory; it is not catalog data in git. */
export const FULL_RELEASE_COURSES = FULL_CATALOG_COURSES;

/** Marker planted in every course body. A view model that still carries courses contains it. */
export const COURSE_BODY_MARKER = "COURSE_BODY_";

const PLACES = ["Cambridge, MA", "Oxford, United Kingdom", "Chennai, India", "São Paulo, Brazil"] as const;

function youtubeId(index: number): string {
  return index.toString(36).padStart(11, "a");
}

/**
 * A release the size of production after release 133: one lesson per course, spread across universities and authors.
 * Course bodies carry `COURSE_BODY_MARKER` so a payload test can see a leak.
 */
export function fullSizeRelease(courses = FULL_RELEASE_COURSES): PublicCatalog {
  const base = releaseFixture();
  const template = base.courses[0];
  const lesson = base.lessons[0];
  const author = base.authors[0];
  if (!template || !lesson || !author) throw new Error("release fixture is empty");
  const authorCount = 40;
  const universityCount = 48;
  const authors = Array.from({ length: authorCount }, (_, index) => ({
    ...author, id: `author-${String(index)}`, slug: `lecturer-${String(index)}`, name: `Lecturer ${String(index)}`, monogram: "LL",
  }));
  const builtCourses = Array.from({ length: courses }, (_, index) => {
    const id = `course-${String(index)}`;
    return {
      ...template,
      id, slug: id, authorId: `author-${String(index % authorCount)}`, areaId: "letters", featured: index === 0,
      title: `Title ${id}`, displayTitle: `Display ${id}`, shelfTitle: `Shelf ${id}`,
      billboardDescription: `${COURSE_BODY_MARKER}${id} billboard text that a card must not carry`,
      billboardDescriptionMobile: `${COURSE_BODY_MARKER}${id} mobile`,
      description: `${COURSE_BODY_MARKER}${id} description`,
      descriptionMobile: `${COURSE_BODY_MARKER}${id} description mobile`,
      editions: template.editions.map((edition) => ({ ...edition, id: `${id}-e1`, lessonCount: 1, durationSeconds: 3600, parts: { lectures: 1, labs: 0 } })),
    };
  });
  const lessons = builtCourses.map((course, index) => ({
    ...lesson, id: `lesson-${String(index)}`, courseId: course.id, editionId: `${course.id}-e1`, slug: "intro", order: 1, youtubeId: youtubeId(index),
  }));
  const byAuthor = new Map<string, string[]>();
  const byUniversity = new Map<number, string[]>();
  for (const [index, course] of builtCourses.entries()) {
    const list = byAuthor.get(course.authorId) ?? [];
    list.push(course.id);
    byAuthor.set(course.authorId, list);
    const university = index % universityCount;
    const members = byUniversity.get(university) ?? [];
    members.push(course.id);
    byUniversity.set(university, members);
  }
  return {
    ...base,
    authors,
    courses: builtCourses,
    lessons,
    redirects: [],
    areas: [{ id: "letters", title: "Letters" }],
    home: {
      featuredCourseId: "course-0",
      rows: [
        { id: "continue-watching", kind: "continue", title: "Continue Watching", courseIds: [] },
        ...authors.map((entry) => ({ id: entry.slug, kind: "author" as const, title: entry.name, authorId: entry.id, courseIds: byAuthor.get(entry.id) ?? [] })),
        ...Array.from({ length: universityCount }, (_, index) => ({
          id: `university-${String(index)}`, kind: "curated" as const, title: `University ${String(index)}`,
          fullName: `University ${String(index)} Full`, place: PLACES[index % PLACES.length] ?? PLACES[0],
          courseIds: byUniversity.get(index) ?? [],
        })),
      ],
    },
  };
}
