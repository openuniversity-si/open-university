import type { ReactNode } from "react";
import { readPreviewPage } from "@/app/catalog-preview";
import { publicRouteSnapshot } from "@/catalog/server/public-routes";
import { guardCatalogPath } from "@/site/server/guard";

/** Course guard: an unpublished course is a 404, an old slug a 308 (ADR-17). The lesson route has its own guard. */
export default async function CourseLayout({ children, params }: { readonly children: ReactNode; readonly params: Promise<{ courseSlug: string }> }) {
  const { courseSlug } = await params;
  guardCatalogPath(`/c/${courseSlug}`, publicRouteSnapshot(await readPreviewPage({ kind: "course", slug: courseSlug })));
  return children;
}
