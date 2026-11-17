import type { Metadata } from "next";
import { headers } from "next/headers";
import { getCourseMedia } from "@tower/media";
import { readPreviewPage } from "@/app/catalog-preview";
import { catalogProgressViews } from "@/catalog/server/progress-reading";
import { featuredMediaIds, homeClient, signedInHomeClient, signedInMediaIds } from "@/catalog/domain/view-model";
import { getViewerProgress } from "@/progress/server/viewer";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { emptyCatalogBody, emptyCatalogTitle } from "@/site/domain/reader-copy";
import { siteData } from "@/site/server/site-data";
import { BillboardSelection } from "@/ui/Billboard/BillboardSelection";
import { homeShelves } from "@/ui/showcase/home-shelves";
import { HomePortals } from "@/ui/HomePortals/HomePortals";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";

/** ADR-16: `/` for a request with a session cookie (proxy.ts rewrite); per viewer, so never cached. */
export const dynamic = "force-dynamic";

export const metadata: Metadata = { ...toMetadata(staticPageMetadata("/")), robots: { index: false, follow: false } };

export default async function SignedInHomePage() {
  const [catalog, progress] = await Promise.all([readPreviewPage({ kind: "release" }), getViewerProgress(await headers())]);
  const views = progress ? catalogProgressViews(catalog, progress) : undefined;
  const media = await getCourseMedia(views ? signedInMediaIds(catalog, views) : [...featuredMediaIds(catalog)], catalog);
  const home = views ? signedInHomeClient(catalog, media, views) : { ...homeClient(catalog, media), continueWatching: [] };
  if (!home.featured) return <EmptyCatalog title={emptyCatalogTitle} body={emptyCatalogBody} />;
  return <BillboardSelection featured={home.featured} shelves={homeShelves([], home.continueWatching)} intro={siteData().homeIntro}><HomePortals portals={home.portals} /></BillboardSelection>;
}
