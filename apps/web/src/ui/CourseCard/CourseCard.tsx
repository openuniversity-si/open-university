"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import type { CardView } from "@/catalog/domain/view-model";
import { courseSelectedDescription } from "@/site/domain/reader-copy.ts";
import { CoverGlass } from "@/ui/CoverGlass/CoverGlass";
import { CoverPlayButton } from "@/ui/CoverPlayButton/CoverPlayButton";
import { LazyPoster } from "@/ui/LazyPoster/LazyPoster";
import { shouldSelectCard } from "./activation";
import styles from "./CourseCard.module.css";

interface CourseCardProps {
  readonly course: CardView;
  readonly selected?: boolean;
  readonly onSelect?: (courseId: string) => void;
  /** F11 inserts the Continue scrim below glass and progress above it. */
  readonly coverScrim?: ReactNode;
  readonly coverProgress?: ReactNode;
  /** Type=Continue (Continue Watching): resumes at the saved second (Decision 2) and shows lesson progress. */
  readonly resume?: { readonly label: string; readonly remaining: string; readonly fraction: number; readonly href: string };
  /** In the HTML and loaded at once (never preloaded): the cards of the first rows that fit the viewport (`isEagerPoster`); the rest on demand. */
  readonly eager?: boolean;
  readonly children?: ReactNode;
}

/** CourseCard uses the title of the current catalog, including synthetic fixtures. */
export function CourseCard({ course, selected = false, onSelect, coverScrim, coverProgress, resume, eager = false, children }: CourseCardProps) {
  const name = course.title;
  const progress = resume ? { "--tower-continue-progress": `${String(resume.fraction * 100)}%` } as CSSProperties : undefined;
  return (
    <Link
      className={`${styles.card ?? ""} tower-focus-rounded`}
      href={resume?.href ?? `/c/${course.slug}`}
      prefetch={false}
      title={course.title}
      aria-label={resume ? `${course.title}, ${resume.label}, ${resume.remaining}` : course.title}
      aria-current={selected ? "true" : undefined}
      aria-description={selected ? courseSelectedDescription : undefined}
      data-testid={`course-card-${course.id}`}
      data-selected={selected}
      data-type={resume ? "continue" : "poster"}
      onClick={(event) => {
        if (onSelect && shouldSelectCard(event, selected)) {
          event.preventDefault();
          onSelect(course.id);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === " " && !event.repeat) {
          event.preventDefault();
          event.currentTarget.click();
        }
      }}
    >
      <span className={styles["cover-frame"]} data-testid="tower-card-poster">
        <span className={styles.cover} data-testid="tower-card-cover">
          {course.assets.poster ? (
            eager ? (
              // perf: pre-optimized at the origin (540×960 WebP, budget in src/media/domain/budget.ts); no image optimizer. The
              // <picture> keeps React from hoisting a <link rel=preload> for it: only the hero is preloaded. fetchPriority="low": the hero (the LCP) gets the bandwidth first (ADR-23).
              <picture>
                <img className={styles.art} src={course.assets.poster.url} alt="" width={course.assets.poster.width} height={course.assets.poster.height} loading="eager" decoding="async" fetchPriority="low" />
              </picture>
            ) : <LazyPoster className={styles.art} src={course.assets.poster.url} width={course.assets.poster.width} height={course.assets.poster.height} />
          ) : null}
          {resume ? <span className={styles.scrim} /> : coverScrim}
          <CoverGlass />
          {selected ? <CoverPlayButton /> : null}
          {resume ? <span className={styles.track} style={progress} data-testid="tower-card-progress"><span className={styles.fill} /></span> : coverProgress}
        </span>
        <span className={styles.ring} aria-hidden="true" />
      </span>
      {resume ? (
        <span className={styles.meta} data-testid="tower-card-continue">
          <span className={styles["meta-title"]}>{name}</span>
          <span className={styles["meta-label"]}>{resume.label}</span>
          <span className={styles["meta-left"]}>{resume.remaining}</span>
        </span>
      ) : <span className={styles.name} data-testid="tower-card-name">{name}</span>}
      {children}
    </Link>
  );
}
