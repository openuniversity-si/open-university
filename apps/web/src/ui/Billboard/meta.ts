import type { BillboardView } from "@/catalog/domain/view-model";
import { billboardFeatured, billboardSelected, metaGap } from "@/site/domain/reader-copy.ts";

/** Billboard meta as approved: a selected course reads "Selected" (Tap1); otherwise the featured one reads "Featured". */
export function billboardMeta(course: BillboardView, selected: boolean): { readonly mobile: string; readonly desktop: string } {
  const status = selected ? billboardSelected : course.featured ? billboardFeatured : undefined;
  const withStatus = (text: string) => (status ? `${status}${metaGap}${text}` : text);
  return { mobile: withStatus(withResume(course, course.metaMobile)), desktop: withStatus(course.meta) };
}

/** Signed in, mobile meta ends with the lesson Resume points at ("… · Lecture 4"); desktop names it in the CTA. */
export function withResume(course: BillboardView, text: string): string {
  return course.progress?.cta.kind === "resume" ? `${text}${metaGap}${course.progress.cta.lesson}` : text;
}
