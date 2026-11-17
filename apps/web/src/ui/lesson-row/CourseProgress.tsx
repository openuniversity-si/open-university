import type { CSSProperties } from "react";
import { courseProgressLabel, fill, watchedCountTemplate } from "@/site/domain/reader-copy.ts";
import styles from "./CourseProgress.module.css";

export interface WatchedProgress {
  readonly count: number;
  readonly total: number;
  readonly percent: string;
  readonly fraction: number;
}

/** Spec 06 lesson-list header: the percent sits at the right of the titles; the bar follows the header. */
export function CourseProgressPercent({ progress }: { readonly progress: WatchedProgress }) {
  return <span className={styles.percent} data-testid="course-progress-percent">{progress.percent}</span>;
}

export function CourseProgressBar({ progress, className }: { readonly progress: WatchedProgress; readonly className?: string }) {
  const width = { "--tower-course-progress": `${String(progress.fraction * 100)}%` } as CSSProperties;
  return <span className={[styles.track, className].filter(Boolean).join(" ")} role="progressbar" aria-label={courseProgressLabel} aria-valuemin={0} aria-valuemax={progress.total}
    aria-valuenow={progress.count} aria-valuetext={fill(watchedCountTemplate, { count: String(progress.count), total: String(progress.total) })} data-testid="course-progress-bar" style={width}>
    <span className={styles.fill} />
  </span>;
}
