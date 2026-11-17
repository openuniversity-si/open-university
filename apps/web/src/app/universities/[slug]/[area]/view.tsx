import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCourseMedia } from "@tower/media";
import { readPreviewPage } from "@/app/catalog-preview";
import { findUniversity, splitArea, universityAreas } from "@/catalog/domain/universities";
import { toMetadata } from "@/app/to-metadata";
import { coverShareImage, pageMetadata } from "@/site/domain/metadata";
import { areaDescriptionTemplate, courseNoun, fill, metaDot } from "@/site/domain/reader-copy.ts";
import { siteData } from "@/site/server/site-data";
void siteData();
import { AreaGrid } from "@/ui/showcase/AreaGrid";
import { plural } from "@/ui/showcase/shelf-sentences.ts";
import styles from "@/ui/Universities/Universities.module.css";

async function resolve(slug: string, areaId: string, media?: Awaited<ReturnType<typeof getCourseMedia>>) {
  const catalog = await readPreviewPage({ kind: "area", slug, area: areaId });
  const entry = findUniversity(catalog, slug, media);
  const area = entry ? universityAreas(catalog, entry.courses).find((candidate) => candidate.id === areaId) : undefined;
  return entry && area ? { entry, area, groups: splitArea(catalog, area) } : null;
}

export async function universityAreaMetadata({ params }: { params: Promise<{ slug: string; area: string }> }): Promise<Metadata> {
  const { slug, area } = await params;
  const found = await resolve(slug, area);
  if (!found) return {};
  const title = `${found.area.title}${metaDot}${found.entry.name}`;
  const path = `/universities/${found.entry.slug}/${found.area.id}`;
  return toMetadata(pageMetadata(path, fill(areaDescriptionTemplate, { fullName: found.entry.fullName, count: plural(found.area.courses.length, courseNoun), area: found.area.title }), title, coverShareImage(found.entry.cover ? { ...found.entry.cover, ...(found.entry.og ? { og: found.entry.og } : {}) } : null, found.entry.fullName)));
}

export async function UniversityAreaView({ slug, area }: { readonly slug: string; readonly area: string }) {
  const catalog = await readPreviewPage({ kind: "area", slug, area });
  const listed = await resolve(slug, area);
  if (!listed) notFound();
  const found = await resolve(slug, area, await getCourseMedia(listed.area.courses.map((course) => course.id), catalog));
  if (!found) notFound();
  const { entry, area: subject, groups } = found;
  return (
    <div className={styles.area} data-testid="university-area">
      <Link className={styles.back} href={`/universities/${entry.slug}`} prefetch={false} data-testid="area-back"><span aria-hidden="true">‹</span> {entry.name}</Link>
      <AreaGrid title={subject.title} meta={plural(subject.courses.length, courseNoun)} groups={groups} />
    </div>
  );
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string; area: string }> }): Promise<Metadata> {
  return universityAreaMetadata({ params });
}

export default async function UniversityAreaPage({ params }: { params: Promise<{ slug: string; area: string }> }) {
  const { slug, area } = await params;
  return <UniversityAreaView slug={slug} area={area} />;
}
