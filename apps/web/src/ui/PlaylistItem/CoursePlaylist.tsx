"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { useAuthSelection } from "@/identity/client/AuthProvider";
import { fill, lessonActivateDescription, lessonSelectedDescription, metaDot, watchedCountTemplate, watchedDescribed } from "@/site/domain/reader-copy.ts";
import { PlaylistItem, type CourseLessonRow, type LessonRowMark } from "@/ui/lesson-row/PlaylistItem";
import { CourseProgressBar, CourseProgressPercent, type WatchedProgress } from "@/ui/lesson-row/CourseProgress";
import styles from "./CoursePlaylist.module.css";

// A component-specific readiness signal: streamed markup may exist before its selection handlers are attached.
const subscribe = () => () => {};
const clientReady = () => true;
const serverReady = () => false;

/** A part of an edition's list ("Lectures · 12", ADR-21): its label and the index of its first row. */
export interface PlaylistPart { readonly label: string; readonly from: number }

export function CoursePlaylist({ title, noun, lessons, thumbnails, progress, parts, count, headingId = "course-lessons-heading" }: {
  readonly title: string;
  /** Headers before each part, when the edition has Lectures and Labs. */
  readonly parts?: readonly PlaylistPart[];
  /** Signed out: the count after the title ("12 lectures + 14 labs"); default "<n> <noun>s". */
  readonly count?: string;
  /** Unique per page: one list per edition. */
  readonly headingId?: string;
  /** Signed in (F11): "3 of 17 watched", percent and the course progress bar. */
  readonly progress?: WatchedProgress;
  readonly noun: "Lecture" | "Episode";
  readonly lessons: readonly CourseLessonRow[];
  readonly thumbnails: readonly ReactNode[];
}) {
  const hydrated = useSyncExternalStore(subscribe, clientReady, serverReady);
  const [selectedId, setSelectedId] = useAuthSelection(`course:${title}`);
  return (
    <section className={styles.panel} aria-labelledby={headingId} data-testid="course-lectures" data-hydrated={hydrated}>
      <header className={styles.header} data-testid="course-lectures-header">
        <h2 id={headingId}>{noun}s</h2>
        <p>{title}{metaDot}{progress ? fill(watchedCountTemplate, { count: String(progress.count), total: String(progress.total) }) : count ?? `${String(lessons.length)} ${noun.toLowerCase()}s`}</p>
        {progress ? <CourseProgressPercent progress={progress} /> : null}
      </header>
      {progress ? <CourseProgressBar progress={progress} className={styles.progress} /> : null}
      <div className={styles.list} data-testid="course-lecture-list" tabIndex={0} aria-label={`${noun}s`}>
        {lessons.map((lesson, index) => {
          const part = parts?.find((entry) => entry.from === index);
          const selected = selectedId === lesson.id;
          const current = lesson.status === "current";
          const watched = lesson.status === "watched";
          const mark: LessonRowMark = current ? "current" : watched ? "watched" : "none";
          const meta = current && lesson.currentMeta ? lesson.currentMeta : <>{lesson.label}{metaDot}{lesson.duration}</>;
          const description = `${current && lesson.currentMeta ? `${lesson.currentMeta}. ` : watched ? watchedDescribed : ""}${selected ? lessonSelectedDescription : lessonActivateDescription}`;
          const item = <PlaylistItem key={lesson.id} lesson={lesson} thumbnail={thumbnails[index]} selected={selected} onSelect={setSelectedId} meta={meta} description={description} mark={mark} />;
          return part ? [<p key={`part-${part.label}`} className={styles.part} data-testid="course-part-header">{part.label}</p>, item] : item;
        })}
      </div>
    </section>
  );
}
