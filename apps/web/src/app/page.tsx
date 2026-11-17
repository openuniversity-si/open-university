import type { Metadata } from "next";
import { getCourseMedia } from "@tower/media";
import { CACHE } from "@/kernel/cache.ts";
import { readPreviewPage } from "@/app/catalog-preview";
import { featuredMediaIds, homeClient } from "@/catalog/domain/view-model";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { emptyCatalogBody, emptyCatalogTitle } from "@/site/domain/reader-copy";
import { siteData } from "@/site/server/site-data";
import { BillboardSelection } from "@/ui/Billboard/BillboardSelection";
import { homeShelves } from "@/ui/showcase/home-shelves";
import { HomePortals } from "@/ui/HomePortals/HomePortals";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";

/**
 * ADR-16: the visitor Home is static (ISR) and reads no request data; a session cookie is rewritten by proxy.ts to
 * /signed-in-home. A media change or a release activation (tags `media`, `catalog`) revalidates it at once;
 * 5 minutes is the safety net.
 */
export const revalidate = 300 satisfies typeof CACHE.homeSeconds;

export const metadata: Metadata = toMetadata(staticPageMetadata("/"));

export default async function HomePage() {
  const catalog = await readPreviewPage({ kind: "release" });
  const media = await getCourseMedia([...featuredMediaIds(catalog)], catalog);
  const home = homeClient(catalog, media);
  if (!home.featured) return <EmptyCatalog title={emptyCatalogTitle} body={emptyCatalogBody} />;
  return <BillboardSelection featured={home.featured} shelves={homeShelves([])} intro={siteData().homeIntro}><HomePortals portals={home.portals} /></BillboardSelection>;
}
