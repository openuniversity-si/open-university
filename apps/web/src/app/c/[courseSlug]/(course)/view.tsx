import type { Metadata } from "next";
import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { readPreviewPage } from "@/app/catalog-preview";
import { getCourseMedia, getLessonMedia } from "@tower/media";
import { courseReading } from "@/catalog/server/progress-reading";
import { authorOf, courseBySlug, editionsForCourse } from "@/catalog/domain/queries";
import { mediaOrPlaceholders } from "@/media/server/group";
import { MediaImage } from "@/media/client/MediaImage";
import type { ViewerProgress } from "@/progress/server/viewer";
import { courseMetadataInput } from "@/catalog/server/metadata";
import { toMetadata } from "@/app/to-metadata";
import { courseMetadata } from "@/site/domain/metadata";
import { aboutLengthTemplate, fill, hoursCountTemplate, latestEditionSuffix, metaDot } from "@/site/domain/reader-copy.ts";
import { siteData } from "@/site/server/site-data";
void siteData();
import { billboardView } from "@/catalog/domain/view-model";
import { Billboard } from "@/ui/Billboard/Billboard";
import { withResume } from "@/ui/Billboard/meta";
import { CourseAbout } from "@/ui/CourseAbout/CourseAbout";
import { CourseCard } from "@/ui/CourseCard/CourseCard";
import { EditionPane, EditionScope } from "@/ui/EditionSelector/EditionScope";
import { EditionSelector } from "@/ui/EditionSelector/EditionSelector";
import { editionPanelId, editionTabId } from "@/ui/EditionSelector/ids";
import editionStyles from "@/ui/EditionSelector/EditionSelector.module.css";
import { CoursePlaylist } from "@/ui/PlaylistItem/CoursePlaylist";
import { Rail } from "@/ui/Rail/Rail";
import { courseOpening, type CourseOpeningEdition } from "@/ui/showcase/course-opening";
import { towerCourseThumbWidth } from "@/ui/tokens/values";
import styles from "./page.module.css";

export async function courseViewMetadata({ params }: { readonly params: Promise<{ courseSlug: string }> }): Promise<Metadata> {
  const { courseSlug } = await params;
  const catalog = await readPreviewPage({ kind: "course", slug: courseSlug });
  const course = courseBySlug(catalog, courseSlug);
  const media = await mediaOrPlaceholders(getCourseMedia(course ? [course.id] : [], catalog));
  return toMetadata(courseMetadata(courseMetadataInput(catalog, courseSlug, course ? media.get(course.id) : undefined)));
}

/** The course page body: `viewerProgress` null renders the signed-out page (static /c/…), rows render the signed-in one (ADR-16). */
export async function CourseView({ courseSlug, viewerProgress }: { readonly courseSlug: string; readonly viewerProgress: ViewerProgress | null }) {
  const catalog = await readPreviewPage({ kind: "course", slug: courseSlug });
  // The layout guard already answered 404/308; these stay as a safety net.
  const course = courseBySlug(catalog, courseSlug);
  if (!course) notFound();
  const author = authorOf(catalog, course);
  if (!author) notFound();
  const editions = editionsForCourse(course);
  const authorIds = catalog.courses.filter((entry) => entry.authorId === course.authorId).map((entry) => entry.id);
  const [media, lessonMedia] = await Promise.all([mediaOrPlaceholders(getCourseMedia(authorIds, catalog)), mediaOrPlaceholders(getLessonMedia(course.id, catalog))]);
  const progress = viewerProgress ? courseReading(catalog, course, viewerProgress) : undefined;
  // One view per edition (one for most courses): the hero meta, the lesson list and the About facts describe it (ADR-21).
  const opening = courseOpening({ catalog, course, figures: { lessons: lessonMedia, courses: media }, author, editions, ...(progress ? { progress } : {}) });
  const projected = opening.projection;
  if (!projected) notFound();
  const views = opening.editions;
  const [first] = views;
  if (!first) notFound();
  const hero = billboardView({ ...projected, ...(progress ? { progress } : {}), billboardDescription: course.description, billboardDescriptionMobile: course.descriptionMobile,
    metaMobile: first.metaMobile, meta: first.meta });
  const playlist = (view: CourseOpeningEdition, headingId?: string) => (
    <CoursePlaylist title={course.displayTitle} noun={course.lessonNoun} lessons={view.rows} {...(view.watched ? { progress: view.watched } : {})}
      {...(view.parts ? { parts: view.parts } : {})} {...(view.labs > 0 ? { count: view.count } : {})} {...(headingId ? { headingId } : {})}
      thumbnails={view.rows.map((row, index) => <MediaImage key={row.id} asset={view.covers[index]} sizes={towerCourseThumbWidth} />)} />
  );
  const about = (length: ReactNode, edition?: ReactNode) => (course.about ? <div className={styles.about}><CourseAbout author={author} text={course.about} level={course.level}
    length={length} language={course.languageLabel} format={course.format} {...(edition === undefined ? {} : { edition })} /></div> : null);
  const more = (
    <div className={styles.more} data-testid="course-more">
      <Rail context="course" id="more-from-author" title={opening.moreTitle}>
        {opening.more.map((entry) => <CourseCard key={entry.id} course={entry} />)}
      </Rail>
    </div>
  );
  if (views.length === 1) {
    return (
      <div className={styles.course} data-testid="course-page">
        <Billboard course={hero} context="course" />
        <div className={styles.body} data-testid="course-body">
          {playlist(first)}
          {about(fill(aboutLengthTemplate, { hours: fill(hoursCountTemplate, { hours: String(first.hours) }), dot: metaDot, count: first.count }))}
        </div>
        {more}
        <div className={styles.gap} aria-hidden="true" data-testid="course-footer-gap" />
      </div>
    );
  }
  // More than one edition: the Edition bar below the hero; every edition is in the HTML, the default one shown (ADR-21).
  const pane = (render: (view: CourseOpeningEdition) => ReactNode) => views.map((view) => <EditionPane key={view.slug} slug={view.slug} inline>{render(view)}</EditionPane>);
  const resume = (text: string) => withResume(hero, text);
  return (
    <div className={styles.course} data-testid="course-page">
      <EditionScope slugs={views.map((view) => view.slug)}>
        <Billboard course={hero} context="course" meta={{ mobile: pane((view) => resume(view.metaMobile)), desktop: pane((view) => view.meta) }} />
        <div className={editionStyles.block} data-testid="course-editions">
          <EditionSelector editions={views.map((view) => ({ slug: view.slug, label: view.label }))} />
          <p className={editionStyles.summary} data-testid="edition-summary">{pane((view) => view.summary)}</p>
        </div>
        <div className={styles.body} data-testid="course-body">
          <div className={styles.lists}>
            {views.map((view) => (
              <EditionPane key={view.slug} slug={view.slug} id={editionPanelId(view.slug)} role="tabpanel" aria-labelledby={editionTabId(view.slug)}>
                {playlist(view, `course-lessons-heading-${view.slug}`)}
              </EditionPane>
            ))}
          </div>
          {about(pane((view) => fill(aboutLengthTemplate, { hours: fill(hoursCountTemplate, { hours: String(view.hours) }), dot: metaDot, count: view.count })), pane((view) => (view === first ? `${view.label}${fill(latestEditionSuffix, { dot: metaDot })}` : view.label)))}
        </div>
      </EditionScope>
      {more}
      <div className={styles.gap} aria-hidden="true" data-testid="course-footer-gap" />
    </div>
  );
}
