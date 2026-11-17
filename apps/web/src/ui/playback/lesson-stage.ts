import { editionCount, lessonAbout, lessonLabel, lessonNeighbors, lessonsForEdition, type Course, type Edition, type Lesson } from "@/catalog/domain/queries.ts";
import type { PublicCatalog } from "@/catalog/domain/release.ts";
import type { MediaAsset } from "@/media/domain/types.ts";
import { lessonPlaybackSource } from "@/playback/ports/lesson-source.ts";
import type { PlaybackSource } from "@/playback/domain/types.ts";
import { lessonStartSecond, type ProgressRow } from "@/progress/domain/rules.ts";
import { watchedAmong, type CourseProgressView } from "@/progress/domain/view.ts";
import { backToCourse, lectureNavigation, lectureWord, metaDot, nextLecture, previousLecture } from "@/site/domain/reader-copy.ts";
import { chosenLessonCover } from "@/ui/lesson-figure.ts";
import { lessonDuration, requestedSecond } from "@/ui/playback/time.ts";

/** One rail row. The duration is already written. The page does not mark a current lesson here. */
export interface LessonStageRow {
  readonly id: string;
  readonly href: string;
  readonly title: string;
  readonly label: string;
  readonly duration: string;
  readonly status?: "watched";
}

export interface LessonStageLink {
  readonly href: string;
  readonly label: string;
}

/** The lesson page paints this. Neighbors, the start second, and the poster are already chosen. */
export interface LessonStage {
  readonly lessonId: string;
  readonly courseSlug: string;
  readonly lessonSlug: string;
  readonly route: string;
  readonly courseHref: string;
  readonly poster: MediaAsset | undefined;
  readonly source: PlaybackSource;
  /** The `?t=` second the frame still receives. Signed out, playback starts at `startAt` zero. */
  readonly second: number;
  readonly startAt: number;
  readonly completed: boolean;
  readonly kicker: string;
  readonly title: string;
  readonly author: string;
  readonly duration: string;
  readonly language: string;
  readonly editionLabel: string | null;
  readonly navigationLabel: string;
  readonly lectureSuffix: string;
  readonly backLabel: string;
  readonly previous?: LessonStageLink;
  readonly next?: LessonStageLink;
  readonly about: string | null;
  readonly rows: readonly LessonStageRow[];
  readonly covers: readonly (MediaAsset | undefined)[];
  readonly railTitle: string;
  readonly railSubtitle: string;
  readonly noun: Course["lessonNoun"];
  readonly watched?: CourseProgressView["watched"];
  readonly count?: string;
}

export interface LessonStageInput {
  readonly catalog: PublicCatalog;
  readonly course: Course;
  readonly lesson: Lesson;
  readonly edition: Edition;
  readonly author: PublicCatalog["authors"][number];
  /** Lesson figures the page already read. */
  readonly figures: ReadonlyMap<string, readonly MediaAsset[]>;
  readonly progress?: CourseProgressView;
  /** Present for a signed-in viewer, including an empty list. Absent when signed out. */
  readonly viewerRows?: readonly ProgressRow[];
  readonly t: string | string[] | undefined;
}

/** The view `LessonView` paints. Signed out always starts at zero. An explicit `?t=` wins for a signed-in viewer. */
export function lessonStage(input: LessonStageInput): LessonStage {
  const { catalog, course, lesson, edition, author, figures, progress, t } = input;
  const lessons = lessonsForEdition(catalog, edition.id);
  const editionLabel = course.editions.length > 1 ? edition.label : null;
  const { previous, next } = lessonNeighbors(catalog, lesson.id);
  const courseHref = `/c/${course.slug}`;
  const signedIn = input.viewerRows !== undefined;
  const saved = input.viewerRows?.find((row) => row.lessonId === lesson.id);
  const second = requestedSecond(t, lesson.durationSeconds);
  const duration = saved?.durationSeconds ?? lesson.durationSeconds;
  const startAt = signedIn ? lessonStartSecond(saved, typeof t === "string" && t.trim() !== "" ? second : null, duration) : 0;
  const rows = lessons.map((entry): LessonStageRow => ({
    id: entry.id,
    href: `${courseHref}/${entry.slug}`,
    title: entry.displayTitle,
    label: `${lessonLabel(course, entry)} ${String(entry.order)}`,
    duration: lessonDuration(entry.durationSeconds),
    ...(progress?.watchedIds.includes(entry.id) ? { status: "watched" as const } : {}),
  }));
  const prefix = editionLabel === null ? "" : `${editionLabel}${metaDot}`;
  return {
    lessonId: lesson.id,
    courseSlug: course.slug,
    lessonSlug: lesson.slug,
    route: `${courseHref}/${lesson.slug}`,
    courseHref,
    poster: chosenLessonCover(figures.get(lesson.id)),
    source: lessonPlaybackSource(lesson),
    second,
    startAt,
    completed: saved?.completed ?? false,
    kicker: `${prefix}${lessonLabel(course, lesson)} ${String(lesson.order)} of ${String(lessons.length)}${metaDot}${course.shelfTitle}`,
    title: lesson.displayTitle,
    author: author.name,
    duration: lessonDuration(lesson.durationSeconds),
    language: course.languageLabel,
    editionLabel,
    navigationLabel: lectureNavigation,
    lectureSuffix: lectureWord,
    backLabel: backToCourse,
    ...(previous ? { previous: { href: `${courseHref}/${previous.slug}`, label: previousLecture } } : {}),
    ...(next ? { next: { href: `${courseHref}/${next.slug}`, label: nextLecture } } : {}),
    about: lessonAbout(lesson),
    rows,
    covers: lessons.map((entry) => chosenLessonCover(figures.get(entry.id))),
    railTitle: course.displayTitle,
    railSubtitle: course.subtitle,
    noun: course.lessonNoun,
    ...(progress ? { watched: editionLabel === null ? progress.watched : watchedAmong(progress, lessons.map((entry) => entry.id)) } : {}),
    ...(editionLabel === null ? {} : { count: editionCount(course, edition) }),
  };
}
