"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { shouldSelectCard } from "@/ui/CourseCard/activation";
import { PlayIcon } from "@/ui/icons/icons";
import styles from "./PlaylistItem.module.css";

export interface CourseLessonRow {
  readonly id: string;
  readonly href: string;
  readonly title: string;
  readonly label: string;
  readonly duration: string;
  /** Signed in (F11): Watched shows the check; Current is the lesson Resume points at, with its own meta. */
  readonly status?: "watched" | "current";
  /** Current row meta, e.g. "Resume · 1h 40m left". */
  readonly currentMeta?: string;
}

/** The row's chrome. Selection stays a separate screen state, so a selected row can still be current, watched, or preceding. */
export type LessonRowMark = "playing" | "current" | "watched" | "preceding" | "none";

/** First activation selects, second opens; selection is never Now playing. The caller writes the meta and the accessible text. */
export function PlaylistItem({ lesson, thumbnail, selected, onSelect, meta, description, mark = "none", rowClassName, copyClassName, metaClassName, thumbClassName, titleClassName }: {
  readonly lesson: CourseLessonRow;
  readonly thumbnail: ReactNode;
  readonly selected: boolean;
  readonly meta: ReactNode;
  readonly description: string;
  readonly mark?: LessonRowMark;
  readonly rowClassName?: string;
  readonly copyClassName?: string;
  readonly metaClassName?: string;
  readonly thumbClassName?: string;
  readonly titleClassName?: string;
  readonly onSelect: (id: string) => void;
}) {
  const playing = mark === "playing";
  const current = mark === "current";
  const watched = mark === "watched";
  const preceding = mark === "preceding";
  return (
    <Link className={[styles.item ?? "", "tower-focus-rounded", rowClassName].filter(Boolean).join(" ")} href={lesson.href} prefetch={false}
      data-testid={`playlist-item-${lesson.id}`} data-selected={selected} data-now-playing={playing} data-preceding={preceding}
      data-status={playing ? undefined : current ? "current" : watched ? "watched" : undefined}
      aria-current={playing ? "true" : current ? "step" : undefined}
      aria-label={`${lesson.label}: ${lesson.title}, ${lesson.duration}`}
      aria-description={description}
      onClick={(event) => {
        if (shouldSelectCard(event, selected)) { event.preventDefault(); onSelect(lesson.id); }
      }}
      onKeyDown={(event) => {
        if (event.key === " " && !event.repeat) { event.preventDefault(); event.currentTarget.click(); }
      }}>
      {playing || current ? <svg className={styles["playing-edge"]} viewBox="0 0 12 70" preserveAspectRatio="none" aria-hidden="true"><path d="M12 70C3.71573 70 -3 63.2843 -3 55V15C-3 6.71573 3.71573 0 12 0C7.02944 0 3 5.37258 3 12V58C3 64.6274 7.02944 70 12 70Z" fill="currentColor" /></svg> : null}
      <span className={[styles.thumb, thumbClassName].filter(Boolean).join(" ")} data-testid="playlist-thumb">{thumbnail}</span>
      <span className={[styles.copy, copyClassName].filter(Boolean).join(" ")}>
        <span className={[styles.meta, metaClassName].filter(Boolean).join(" ")}>{meta}</span>
        <span className={[styles.title, titleClassName].filter(Boolean).join(" ")}>{lesson.title}</span>
      </span>
      {playing ? <svg className={styles.playing} viewBox="0 0 18 18" aria-hidden="true"><rect x="2.25" y="7.5" width="2.25" height="7.5" rx="1.125" /><rect x="6" y="3" width="2.25" height="12" rx="1.125" /><rect x="9.75" y="9.75" width="2.25" height="5.25" rx="1.125" /><rect x="13.5" y="5.25" width="2.25" height="9.75" rx="1.125" /></svg> : selected ? <span className={styles.selected} aria-hidden="true"><PlayIcon /></span>
        : watched ? <svg className={styles.status} viewBox="0 0 18 18" aria-hidden="true" data-testid="playlist-watched"><path d="M3.8 9.15 7.35 12.7 14.3 5.6" fill="none" stroke="currentColor" strokeWidth="var(--tower-el-icon-stroke)" strokeLinecap="round" strokeLinejoin="round" /></svg>
          : preceding ? <span className={styles.status} aria-hidden="true" /> : null}
    </Link>
  );
}
