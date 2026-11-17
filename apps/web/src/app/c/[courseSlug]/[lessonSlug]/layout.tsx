import type { ReactNode } from "react";
import { readPreviewPage } from "@/app/catalog-preview";
import { publicRouteSnapshot } from "@/catalog/server/public-routes";
import { guardCatalogPath } from "@/site/server/guard";

/** Lesson guard: a lesson outside the release (or under another course) is a 404, an old path a 308 (ADR-17). */
export default async function LessonLayout({ children, params }: { readonly children: ReactNode; readonly params: Promise<{ courseSlug: string; lessonSlug: string }> }) {
  const { courseSlug, lessonSlug } = await params;
  guardCatalogPath(`/c/${courseSlug}/${lessonSlug}`, publicRouteSnapshot(await readPreviewPage({ kind: "course", slug: courseSlug })));
  return children;
}
