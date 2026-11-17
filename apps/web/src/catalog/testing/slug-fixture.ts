// The real-catalog fixture of the lesson slug rule (slug.fixtures.json): its shape and the slugs the rule gives it.
import { cleanLessonSlug } from "../domain/lesson-address.ts";

export interface SlugFixture {
  readonly source: string;
  readonly legacyLessonIds: readonly string[];
  readonly courses: Readonly<Record<string, { readonly title: string; readonly institution: string | null }>>;
  readonly lessons: readonly {
    readonly courseSlug: string; readonly lessonId: string; readonly edition: { readonly label: string; readonly term: string | null; readonly year: number };
    readonly part: string; readonly position: number; readonly kind: string; readonly youtubeTitle: string; readonly displayTitle: string | null;
    readonly currentSlug: string; readonly expectedSlug: string;
  }[];
}

/** lessonId → slug, generated in the fixture's order with each course's slugs taken so far (as a fresh import would). */
export function fixtureSlugs(fixture: SlugFixture): Map<string, string> {
  const taken = new Map<string, Set<string>>();
  const slugs = new Map<string, string>();
  for (const row of fixture.lessons) {
    const course = fixture.courses[row.courseSlug];
    const courseTaken = taken.get(row.courseSlug) ?? new Set<string>();
    taken.set(row.courseSlug, courseTaken);
    const slug = cleanLessonSlug({ ...row, courseTitle: course?.title ?? "", institution: course?.institution ?? null }, courseTaken);
    courseTaken.add(slug);
    slugs.set(row.lessonId, slug);
  }
  return slugs;
}
