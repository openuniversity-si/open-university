import { authorCourses, homeCourses, type HomeCourse } from "@/catalog/domain/home.ts";
import { editionCount, lessonLabel, lessonsForEdition, type Course, type Edition } from "@/catalog/domain/queries.ts";
import type { PublicCatalog } from "@/catalog/domain/release.ts";
import { cardView, type CardView } from "@/catalog/domain/view-model.ts";
import type { MediaAsset } from "@/media/domain/types.ts";
import { watchedAmong, type CourseProgressView } from "@/progress/domain/view.ts";
import { fill, labsPartTemplate, metaDot, metaGap, moreFromTemplate, nounPluralTemplate, resumeLabel } from "@/site/domain/reader-copy.ts";
import { chosenLessonCover } from "@/ui/lesson-figure.ts";

/** One lesson row. The same fields `CoursePlaylist` paints, with the duration already written. */
export interface CourseOpeningRow {
  readonly id: string;
  readonly href: string;
  readonly title: string;
  readonly label: string;
  readonly duration: string;
  readonly status?: "watched" | "current";
  readonly currentMeta?: string;
}

/** A part header in an edition list ("Lectures · 12"): its label and the index of its first row. */
export interface CourseOpeningPart {
  readonly label: string;
  readonly from: number;
}

/** One edition, as the course page paints it. Meta hours are rounded. The summary keeps one decimal. */
export interface CourseOpeningEdition {
  readonly slug: string;
  readonly label: string;
  readonly rows: readonly CourseOpeningRow[];
  /** Lesson covers already chosen, one per row, in the same order. */
  readonly covers: readonly (MediaAsset | undefined)[];
  readonly count: string;
  /** Rounded hours. The About length reads this number. */
  readonly hours: number;
  readonly labs: number;
  readonly parts?: readonly CourseOpeningPart[];
  readonly meta: string;
  readonly metaMobile: string;
  /** One decimal hour, the characters the edition summary shows. */
  readonly summary: string;
  readonly watched?: CourseProgressView["watched"];
}

/** The course page paints this. It does not recompute hours, rows, or the author's other cards. */
export interface CourseOpening {
  readonly projection: HomeCourse | undefined;
  readonly moreTitle: string;
  readonly more: readonly CardView[];
  readonly editions: readonly CourseOpeningEdition[];
}

export interface CourseOpeningInput {
  readonly catalog: PublicCatalog;
  readonly course: Course;
  /** Covers the page already read: lesson figures for the list, course figures for the author's cards. */
  readonly figures: {
    readonly lessons: ReadonlyMap<string, readonly MediaAsset[]>;
    readonly courses: ReadonlyMap<string, readonly MediaAsset[]>;
  };
  readonly author: PublicCatalog["authors"][number];
  readonly editions: readonly Edition[];
  readonly progress?: CourseProgressView;
}

/** "30m", or "1h 05m" once an hour is reached. The course list's own expression, not the player's. */
function rowDuration(durationSeconds: number): string {
  const minutes = Math.floor(durationSeconds / 60);
  if (minutes >= 60) return `${String(Math.floor(minutes / 60))}h ${String(minutes % 60).padStart(2, "0")}m`;
  return `${String(minutes)}m`;
}

function editionView(input: CourseOpeningInput, edition: Edition): CourseOpeningEdition {
  const { catalog, course, progress } = input;
  const own = lessonsForEdition(catalog, edition.id);
  const rawHours = own.reduce((sum, lesson) => sum + lesson.durationSeconds, 0) / 3600;
  const hours = Math.round(rawHours);
  const count = editionCount(course, edition);
  const rows = own.map((lesson): CourseOpeningRow => {
    const current = progress?.current?.lessonId === lesson.id ? progress.current : undefined;
    const status = current ? "current" as const : progress?.watchedIds.includes(lesson.id) ? "watched" as const : undefined;
    return {
      id: lesson.id,
      href: current && progress ? progress.cta.href : `/c/${course.slug}/${lesson.slug}`,
      title: lesson.displayTitle,
      label: lessonLabel(course, lesson),
      duration: rowDuration(lesson.durationSeconds),
      ...(status ? { status } : {}),
      ...(current ? { currentMeta: `${resumeLabel}${metaDot}${current.remaining}` } : {}),
    };
  });
  const firstLab = own.findIndex((lesson) => lesson.part === "labs");
  const parts = edition.parts.labs > 0 && edition.parts.lectures > 0
    ? [
        { label: `${fill(nounPluralTemplate, { noun: course.lessonNoun })}${metaDot}${String(edition.parts.lectures)}`, from: own.findIndex((lesson) => lesson.part === "lectures") },
        { label: fill(labsPartTemplate, { dot: metaDot, count: String(edition.parts.labs) }), from: firstLab },
      ].sort((left, right) => left.from - right.from)
    : undefined;
  const several = input.editions.length > 1;
  return {
    slug: edition.slug,
    label: edition.label,
    rows,
    covers: own.map((lesson) => chosenLessonCover(input.figures.lessons.get(lesson.id))),
    count,
    hours,
    labs: edition.parts.labs,
    ...(parts ? { parts } : {}),
    meta: `${count}${metaGap}${String(hours)}h${metaGap}${course.level}${metaGap}${course.languageLabel}`,
    metaMobile: `${count}${metaGap}${String(hours)}h${metaGap}${course.level}`,
    summary: `${edition.label}${metaGap}${count}${metaGap}${rawHours.toFixed(1)} h`,
    ...(progress ? { watched: several ? watchedAmong(progress, own.map((lesson) => lesson.id)) : progress.watched } : {}),
  };
}

/** The opening `CourseView` paints. Meta hours and summary hours stay two different strings. */
export function courseOpening(input: CourseOpeningInput): CourseOpening {
  const projections = homeCourses(input.catalog, input.figures.courses);
  const more = authorCourses(input.catalog, input.course.id, projections).filter((entry) => entry.id !== input.course.id).map((entry) => cardView(entry));
  return {
    projection: projections.get(input.course.id),
    moreTitle: fill(moreFromTemplate, { name: input.author.name }),
    more,
    editions: input.editions.map((edition) => editionView(input, edition)),
  };
}
