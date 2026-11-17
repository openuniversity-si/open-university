import type { Metadata } from "next";
import { readPreviewPage } from "@/app/catalog-preview";
import { universityIndexView } from "@/catalog/domain/view-model";
import { siteData } from "@/site/server/site-data";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { emptyCatalogBody, emptyCatalogTitle } from "@/site/domain/reader-copy";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";
import { UniversitiesShowcase, type UniversityShowcaseGroup } from "@/ui/Universities/UniversitiesShowcase";

export const metadata: Metadata = toMetadata(staticPageMetadata("/universities"));

/** The universities index. The same static HTML for every visitor (D-037). */
export default async function UniversitiesPage() {
  const catalog = await readPreviewPage({ kind: "release" });
  const view = universityIndexView(catalog, siteData().countries);
  if (view.groups.length === 0) return <EmptyCatalog title={emptyCatalogTitle} body={emptyCatalogBody} />;
  const flags = siteData().flags;
  const groups: UniversityShowcaseGroup[] = view.groups.map((group) => {
    const flag = group.country ? flags[group.country.id] : undefined;
    return { ...group, ...(flag ? { flag } : {}) };
  });
  return <UniversitiesShowcase groups={groups} courseCount={view.courseCount} />;
}
