import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { readPreviewPage } from "@/app/catalog-preview";
import { getCourseMedia, getLessonMedia } from "@tower/media";
import { courseReading } from "@/catalog/server/progress-reading";
import { authorOf, courseBySlug, editionOf, lessonBySlug } from "@/catalog/domain/queries";
import { mediaOrPlaceholders } from "@/media/server/group";
import { MediaImage } from "@/media/client/MediaImage";
import type { ViewerProgress } from "@/progress/server/viewer";
import { lessonMetadataInput } from "@/catalog/server/metadata";
import { toMetadata } from "@/app/to-metadata";
import { lessonMetadata } from "@/site/domain/metadata";
import { metaGap } from "@/site/domain/reader-copy.ts";
import { siteData } from "@/site/server/site-data";
void siteData();
import { EditionBadge } from "@/ui/EditionBadge/EditionBadge";
import { CompletionToggle } from "@/ui/playback/CompletionToggle";
import { LectureAbout } from "@/ui/playback/LectureAbout";
import { LecturesAnchor } from "@/ui/playback/LecturesAnchor";
import { PlayerFrame } from "@/ui/playback/PlayerFrame";
import { lessonStage } from "@/ui/playback/lesson-stage";
import { towerBreakpointDesktop, towerCourseThumbWidth, towerLessonStageInset, towerViewportWidth } from "@/ui/tokens/values";
import { PlayerRail } from "@/ui/playback/PlayerRail";
import { ChevronLeftIcon, ChevronRightIcon } from "@/ui/icons/icons";
import styles from "./page.module.css";

/** Lesson poster `sizes`, read from the screen-measure keys. */
const lessonPosterSizes = `(min-width: ${towerBreakpointDesktop}) calc(${towerViewportWidth} - ${towerLessonStageInset}), ${towerViewportWidth}`;

export async function lessonViewMetadata({ params }: { readonly params: Promise<{ courseSlug: string; lessonSlug: string }> }): Promise<Metadata> {
  const { courseSlug, lessonSlug } = await params;
  const catalog = await readPreviewPage({ kind: "course", slug: courseSlug });
  const course = courseBySlug(catalog, courseSlug);
  const media = await mediaOrPlaceholders(getCourseMedia(course ? [course.id] : [], catalog));
  return toMetadata(lessonMetadata(lessonMetadataInput(catalog, courseSlug, lessonSlug, course ? media.get(course.id) : undefined)));
}

/** The lesson page body: `viewerProgress` null and no `t` render the signed-out page (static /c/…/…), otherwise the per-request one (ADR-16). */
export async function LessonView({ courseSlug, lessonSlug, t, viewerProgress }: {
  readonly courseSlug: string; readonly lessonSlug: string; readonly t: string | string[] | undefined; readonly viewerProgress: ViewerProgress | null;
}) {
  const catalog = await readPreviewPage({ kind: "course", slug: courseSlug });
  // The layout guard already answered 404/308; these stay as a safety net. Playback needs only the YouTube id (ADR-11).
  const course = courseBySlug(catalog, courseSlug);
  if (!course) notFound();
  const lesson = lessonBySlug(catalog, course.id, lessonSlug);
  const author = authorOf(catalog, course);
  const edition = lesson ? editionOf(catalog, lesson) : undefined;
  if (!lesson || !author || !edition) notFound();
  // The rail, the numbers and previous/next stay inside the lesson's edition; there is no edition switch here (ADR-21).
  const lessonMedia = await mediaOrPlaceholders(getLessonMedia(course.id, catalog));
  const progress = viewerProgress ? courseReading(catalog, course, viewerProgress) : undefined;
  // Signed in (F11): the saved position (or ?t=) is shown and played from; signed out stays at 0:00 (D1).
  const stage = lessonStage({ catalog, course, lesson, edition, author, figures: lessonMedia, t, ...(progress ? { progress } : {}), ...(viewerProgress ? { viewerRows: viewerProgress } : {}) });
  return <div className={styles.player} data-testid="player-page">
    <div className={styles.stage} data-testid="player-stage">
      <div className={styles.main}>
        <PlayerFrame key={stage.lessonId} lesson={{ courseSlug: stage.courseSlug, lessonSlug: stage.lessonSlug }}
          source={stage.source} poster={<MediaImage asset={stage.poster} sizes={lessonPosterSizes} />} second={stage.second} startAt={stage.startAt} route={stage.route} />
        <div className={styles.body}>
          <nav className={styles.navigation} aria-label={stage.navigationLabel} data-testid="player-navigation">
            {stage.previous ? <Link className={styles.previous} href={stage.previous.href} data-testid="player-previous"><ChevronLeftIcon /><span>{stage.previous.label}<span className={styles.desktop}>{stage.lectureSuffix}</span></span></Link> : null}
            <Link className={styles.next} href={stage.next ? stage.next.href : stage.courseHref} data-testid={stage.next ? "player-next" : "player-back-to-course"}><span>{stage.next ? <>{stage.next.label}<span className={styles.desktop}>{stage.lectureSuffix}</span></> : stage.backLabel}</span><ChevronRightIcon /></Link>
          </nav>
          <header className={styles.header} data-testid="player-lesson-header">
            <p className={styles.kicker}>{stage.kicker}</p>
            <h1>{stage.title}</h1>
            <p className={styles.meta}>{stage.author}{metaGap}{stage.duration}<span className={styles.desktop}>{metaGap}{stage.language}</span>{stage.editionLabel === null ? null : <EditionBadge label={stage.editionLabel} />}</p>
          </header>
          <div className={styles.actions} data-testid="player-actions"><CompletionToggle key={stage.lessonId} lesson={{ courseSlug: stage.courseSlug, lessonSlug: stage.lessonSlug }} completed={stage.completed} signedIn={viewerProgress !== null} /><LecturesAnchor />{stage.next ? <Link className={styles.back} href={stage.courseHref}><ChevronLeftIcon /><span>{stage.backLabel}</span></Link> : null}</div>
          <LectureAbout text={stage.about} />
        </div>
      </div>
      <PlayerRail title={stage.railTitle} subtitle={stage.railSubtitle} author={stage.author} noun={stage.noun} lessons={stage.rows} playingId={stage.lessonId} {...(stage.watched ? { progress: stage.watched } : {})}
        {...(stage.editionLabel === null ? {} : { edition: stage.editionLabel, count: stage.count })}
        thumbnails={stage.rows.map((row, index) => <MediaImage key={row.id} asset={stage.covers[index]} sizes={towerCourseThumbWidth} />)} />
    </div>
    <div className={styles.gap} aria-hidden="true" data-testid="player-footer-gap" />
  </div>;
}
