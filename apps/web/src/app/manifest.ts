import type { MetadataRoute } from "next";
import { siteData } from "@/site/server/site-data";
import { TOWER_THEME_COLOR } from "@/ui/tokens/layout";

/** `/manifest.webmanifest` (ADR-13): installable shell in the site's dark chrome. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: siteData().metadata.siteName,
    short_name: siteData().metadata.siteName,
    description: siteData().metadata.defaultDescription,
    start_url: "/",
    display: "standalone",
    background_color: TOWER_THEME_COLOR,
    theme_color: TOWER_THEME_COLOR,
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
