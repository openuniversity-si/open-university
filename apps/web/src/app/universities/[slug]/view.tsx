import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCourseMedia } from "@tower/media";
import { readPreviewPage } from "@/app/catalog-preview";
import { findUniversity } from "@/catalog/domain/universities";
import { universityDetailRails } from "@/catalog/domain/view-model";
import { toMetadata } from "@/app/to-metadata";
import { coverShareImage, pageMetadata } from "@/site/domain/metadata";
import { browseCourses, courseNoun, freeInOrderSuffix, jumpToArea, jumpToLabel, universitiesTitle } from "@/site/domain/reader-copy.ts";
import { siteData } from "@/site/server/site-data";
void siteData();
import { Billboard } from "@/ui/Billboard/Billboard";
import { plural, universityHero } from "@/ui/showcase/shelf-sentences.ts";
import { UniversityRails } from "@/ui/Universities/UniversityRails";
import styles from "@/ui/Universities/Universities.module.css";

export async function universityMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const catalog = await readPreviewPage({ kind: "university", slug });
  const entry = findUniversity(catalog, slug);
  if (!entry) return {};
  const description = `${entry.fullName}: ${plural(entry.courses.length, courseNoun)}${freeInOrderSuffix}`;
  return toMetadata(pageMetadata(`/universities/${entry.slug}`, description, entry.name, coverShareImage(entry.cover ? { ...entry.cover, ...(entry.og ? { og: entry.og } : {}) } : null, entry.fullName)));
}

/** A university page. The same static HTML for every visitor (D-037). */
export async function UniversityView({ slug }: { readonly slug: string }) {
  const catalog = await readPreviewPage({ kind: "university", slug });
  const listed = findUniversity(catalog, slug);
  if (!listed) notFound();
  const media = await getCourseMedia(listed.courses.map((course) => course.id), catalog);
  const entry = findUniversity(catalog, slug, media) ?? listed;
  const rails = universityDetailRails(catalog, entry.slug, entry.courses);
  const hero = universityHero({ slug: entry.slug, name: entry.name, fullName: entry.fullName, place: entry.place, cover: entry.cover, courseCount: entry.courses.length, areaCount: entry.areaCount, areasNamed: entry.areasNamed });
  const chips = rails.filter((rail, index) => rails.findIndex((other) => other.areaId === rail.areaId) === index)
    .map((rail) => ({ id: rail.areaId, href: `#${rail.id}`, title: rail.kind === "subarea" || rail.kind === "rest" ? areaTitle(catalog, rail.areaId, rail.title) : rail.title }));
  const back = <Link className={styles.back} href="/universities" prefetch={false} data-testid="university-back"><span aria-hidden="true">‹</span> {universitiesTitle}</Link>;
  return (
    <>
      <Billboard course={hero} context="course" meta={{ mobile: hero.metaMobile, desktop: hero.meta }} primary={{ href: `#${rails[0]?.id ?? ""}`, label: browseCourses }} back={back} />
      <div className={styles.rails} data-testid="university-areas">
        {chips.length > 1 ? (
          <ul className={styles.chips} aria-label={jumpToArea}>
            <li className={styles["chips-label"]} aria-hidden="true">{jumpToLabel}</li>
            {chips.map((chip) => <li key={chip.id}><a className={`${styles.chip ?? ""} tower-focus-rounded`} href={chip.href}>{chip.title}</a></li>)}
          </ul>
        ) : null}
        <UniversityRails rails={rails} />
      </div>
    </>
  );
}

function areaTitle(catalog: { areas?: readonly { id: string; title: string }[] | undefined }, areaId: string, fallback: string): string {
  return catalog.areas?.find((area) => area.id === areaId)?.title ?? fallback;
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  return universityMetadata({ params });
}

export default async function UniversityPage({ params }: { params: Promise<{ slug: string }> }) {
  return <UniversityView slug={(await params).slug} />;
}
