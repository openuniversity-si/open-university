import type { MetadataRoute } from "next";
import { currentEnv } from "@/kernel/env.ts";
import { indexingFacts } from "@/platform/host/env.ts";
import { isSiteIndexable } from "@/site/domain/indexing";
import { PRODUCTION_ORIGIN } from "@/site/domain/origin";

/** Production: crawl every page, hide only the API (ADR-12). Elsewhere: disallow everything. */
export default function robots(): MetadataRoute.Robots {
  if (isSiteIndexable(indexingFacts(currentEnv()))) {
    return { rules: [{ userAgent: "*", allow: "/", disallow: ["/api/"] }], sitemap: `${PRODUCTION_ORIGIN}/sitemap.xml` };
  }
  return { rules: { userAgent: "*", disallow: "/" } };
}
