"use client";

import type { ReactNode } from "react";
import { useAuthSelection } from "@/identity/client/AuthProvider";
import { courseProgressLabel, fill, lessonActivateDescription, lessonSelectedDescription, metaDot, metaGap, nowPlaying as nowPlayingLabel, nowPlayingDescribed, watchedCountTemplate, watchedDescribed } from "@/site/domain/reader-copy.ts";
import { CourseProgressBar, CourseProgressPercent, type WatchedProgress } from "@/ui/lesson-row/CourseProgress";
import { PlaylistItem, type CourseLessonRow, type LessonRowMark } from "@/ui/lesson-row/PlaylistItem";
import styles from "./PlayerRail.module.css";

export function PlayerRail({ title, subtitle, author, noun, lessons, thumbnails, playingId, progress, edition, count }: {
  readonly title: string;
  readonly subtitle: string;
  readonly author: string;
  readonly noun: "Lecture" | "Episode";
  readonly lessons: readonly CourseLessonRow[];
  readonly thumbnails: readonly ReactNode[];
  readonly playingId: string;
  /** Signed in (F11): watched counts and the course progress bars. */
  readonly progress?: WatchedProgress;
  /** A course with editions: the lesson's edition heads the section ("Spring 2026 · 3 of 26 watched", ADR-21). */
  readonly edition?: string;
  /** Signed out: the count after the edition ("2 lectures + 1 labs"); default "<n> <noun>s". */
  readonly count?: string;
}) {
  const watched = progress ? fill(watchedCountTemplate, { count: String(progress.count), total: String(progress.total) }) : null;
  const [selectedId, setSelectedId] = useAuthSelection(`player:${title}`);
  const playingIndex = lessons.findIndex((lesson) => lesson.id === playingId);
  return <section className={styles.panel} id="player-lectures" tabIndex={-1} aria-label={`${title} ${noun.toLowerCase()}s`} data-testid="player-rail">
    <header className={styles.header} data-testid="player-rail-header"><h2 className={styles.desktop} id="player-rail-course">{title}</h2><h2 className={styles.mobile} id="player-lectures-heading">{noun}s</h2><p className={styles.desktop}>{author}</p><p className={styles.mobile}>{title}{metaDot}{watched ?? `${String(lessons.length)} ${noun.toLowerCase()}s`}</p>
      {progress ? <span className={styles.mobile}><CourseProgressPercent progress={progress} /></span> : null}</header>
    {progress ? <CourseProgressBar progress={progress} className={`${styles.mobile ?? ""} ${styles["mobile-bar"] ?? ""}`} /> : null}
    {progress ? <div className={styles.progress} data-testid="player-rail-progress"><p><span>{courseProgressLabel}</span><span>{progress.count} of {progress.total}{metaGap}{progress.percent}</span></p><CourseProgressBar progress={progress} className={styles.bar} /></div> : null}
    <div className={styles.section} data-testid="player-rail-section"><h3>{subtitle}</h3><p>{edition === undefined ? null : `${edition}${metaDot}`}{watched ?? count ?? `${String(lessons.length)} ${noun.toLowerCase()}s`}</p></div>
    <div className={styles.list} data-testid="player-lecture-list" tabIndex={0} aria-label={`${noun}s`}>
      {lessons.map((lesson, index) => {
        const selected = selectedId === lesson.id;
        const playing = playingId === lesson.id;
        const current = !playing && lesson.status === "current";
        const watched = !playing && lesson.status === "watched";
        const preceding = !progress && index < playingIndex;
        const mark: LessonRowMark = playing ? "playing" : current ? "current" : watched ? "watched" : preceding ? "preceding" : "none";
        const meta = current && lesson.currentMeta ? lesson.currentMeta : <>{playing ? nowPlayingLabel : lesson.label}{metaGap}{lesson.duration}</>;
        const description = `${playing ? nowPlayingDescribed : current && lesson.currentMeta ? `${lesson.currentMeta}. ` : watched ? watchedDescribed : ""}${selected ? lessonSelectedDescription : lessonActivateDescription}`;
        return <PlaylistItem key={lesson.id} lesson={lesson} thumbnail={thumbnails[index]} selected={selected} onSelect={setSelectedId} meta={meta} description={description} mark={mark}
          rowClassName={[styles["player-row"] ?? "", selected ? styles["player-row-selected"] ?? "" : ""].filter(Boolean).join(" ")} copyClassName={styles["player-copy"] ?? ""} metaClassName={styles["player-meta"] ?? ""}
          {...(preceding ? { thumbClassName: styles["player-preceding-thumb"] ?? "", titleClassName: styles["player-preceding-title"] ?? "" } : {})} />;
      })}
    </div>
  </section>;
}
