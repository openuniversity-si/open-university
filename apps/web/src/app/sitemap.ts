import type { MetadataRoute } from "next";
import { CACHE } from "@/kernel/cache.ts";
import { readPreviewPage } from "@/app/catalog-preview";
import { PRODUCTION_ORIGIN } from "@/site/domain/origin";
import { publicRouteSnapshot } from "@/catalog/server/public-routes";
import { publicPaths } from "@/site/domain/route-registry";

/**
 * Cached for an hour (it was rendered per request, and every crawler fetch re-ran it over the whole release). Releases
 * also purge it (CATALOG_PATHS); when that purge lags on the host, the hour bounds the staleness.
 * Formerly rendered per request. The URL list is a pure function of the active release, which the page catalog serves from the tagged
 * Data Cache (one cheap read; `invalidateCatalog` expires it at once). A prerendered sitemap (`revalidate`) stayed on the
 * previous release's URLs for hours on the previous host, even after `revalidatePath("/sitemap.xml")` (observed on preview and prod).
 */
export const revalidate = 3_600 satisfies typeof CACHE.sitemapSeconds;

/** Static pages, universities, every course and every lesson of the active release; absolute URLs, no invented dates. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  return publicPaths(publicRouteSnapshot(await readPreviewPage({ kind: "release" }))).map((path) => ({ url: `${PRODUCTION_ORIGIN}${path}` }));
}
