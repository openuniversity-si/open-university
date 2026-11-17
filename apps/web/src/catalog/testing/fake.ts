import { syntheticCatalog } from "./synthetic.ts";
import { releaseSha } from "../../kernel/sha.ts";
import { releaseSchema, type PublicCatalog } from "../domain/release.ts";

/** Synthetic current-schema catalog for unit tests and e2e. */
export const snapshotCatalog: PublicCatalog = syntheticCatalog;

const genesis = snapshotCatalog.courses[0];
const firstLesson = snapshotCatalog.lessons.find((lesson) => lesson.courseId === genesis?.id && lesson.order === 1);
if (!genesis || !firstLesson) throw new Error("The snapshot needs a first course with a first lesson.");
/** Old paths the test build answers with a 308 (e2e), one per guard level. */
export const TEST_REDIRECTS = [
  { from: "/c/moved-course", to: `/c/${genesis.slug}` },
  { from: `/c/${genesis.slug}/moved-lesson`, to: `/c/${genesis.slug}/${firstLesson.slug}` },
] as const;

/**
 * A two-edition course for the test build (e2e of the edition selector, ADR-21), on synthetic lessons: Spring 2025 (two
 * lectures and a lab) opens first, Fall 2024 (two lectures) second. Not on any Home row; the snapshot's courses are untouched.
 */
export const TEST_EDITIONS_COURSE = { id: "course-test-editions", slug: "test-two-editions" } as const;
function testEditionsCourse(): Pick<PublicCatalog, "courses" | "lessons"> {
  const base = snapshotCatalog.courses.at(-1);
  if (!base) throw new Error("The snapshot needs a course to copy.");
  const { id: courseId } = TEST_EDITIONS_COURSE;
  const plan = [["spring-2025", "lectures"], ["spring-2025", "lectures"], ["spring-2025", "labs"], ["fall-2024", "lectures"], ["fall-2024", "lectures"]] as const;
  const order = new Map<string, number>();
  const lessons = plan.map(([edition, part], index) => {
    const position = (order.get(edition) ?? 0) + 1;
    order.set(edition, position);
    const n = String(index + 1);
    return {
      id: `lesson-test-${n}`, slug: `edition-test-${n}`, courseId, order: position, kind: "lecture" as const, youtubeTitle: `Edition test ${n}`,
      displayTitle: part === "labs" ? `Lab ${String(position)}: Practice` : `Lecture ${String(position)}: ${edition === "fall-2024" ? "Fall" : "Spring"} test`,
      about: null, youtubeId: `edTest${n.padStart(5, "0")}`, durationSeconds: 1800, editionId: `${courseId}-${edition}`, part,
    };
  });
  const edition = (slug: "spring-2025" | "fall-2024", position: number) => {
    const own = lessons.filter((lesson) => lesson.editionId === `${courseId}-${slug}`);
    const [term, year] = slug.split("-") as ["spring" | "fall", string];
    return {
      id: `${courseId}-${slug}`, slug, label: `${term === "spring" ? "Spring" : "Fall"} ${year}`, term, year: Number(year), position, resolution: null,
      lessonCount: own.length, durationSeconds: own.length * 1800,
      parts: { lectures: own.filter((lesson) => lesson.part === "lectures").length, labs: own.filter((lesson) => lesson.part === "labs").length },
    };
  };
  return {
    courses: [{ ...base, ...TEST_EDITIONS_COURSE, featured: false, lessonNoun: "Lecture" as const, displayTitle: "Two Editions", shelfTitle: "Two Editions", editions: [edition("spring-2025", 1), edition("fall-2024", 2)] }],
    lessons,
  };
}

/** `@tower/catalog` in the test build (`TOWER_BUILD_TARGET=test`): the snapshot plus the test redirects and course, no database. */
export const fakeCatalog: PublicCatalog = releaseSchema.parse({
  ...snapshotCatalog, courses: [...snapshotCatalog.courses, ...testEditionsCourse().courses], lessons: [...snapshotCatalog.lessons, ...testEditionsCourse().lessons],
  redirects: [...snapshotCatalog.redirects, ...TEST_REDIRECTS],
});

export function getCatalogState() {
  return Promise.resolve({ catalog: fakeCatalog, sha: releaseSha(syntheticCatalog), source: "fake" as const });
}

export function getCatalog(): Promise<PublicCatalog> {
  return Promise.resolve(fakeCatalog);
}
