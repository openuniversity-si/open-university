import type { Metadata } from "next";
import { getCourseMedia } from "@tower/media";
import { readPreviewPage } from "@/app/catalog-preview";
import { authorMediaIds, authorsClient } from "@/catalog/domain/view-model";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { emptyCatalogBody, emptyCatalogTitle } from "@/site/domain/reader-copy";
import { siteData } from "@/site/server/site-data";
import { BillboardSelection } from "@/ui/Billboard/BillboardSelection";
import { homeShelves } from "@/ui/showcase/home-shelves";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";

export const metadata: Metadata = toMetadata(staticPageMetadata("/authors"));

/** The authors tab. The same static HTML for every visitor (D-037). */
export default async function AuthorsPage() {
  const catalog = await readPreviewPage({ kind: "release" });
  const media = await getCourseMedia(authorMediaIds(catalog), catalog);
  const tab = authorsClient(catalog, media);
  if (!tab.featured) return <EmptyCatalog title={emptyCatalogTitle} body={emptyCatalogBody} />;
  return <BillboardSelection featured={tab.featured} shelves={homeShelves(tab.rails)} intro={siteData().homeIntro} />;
}
