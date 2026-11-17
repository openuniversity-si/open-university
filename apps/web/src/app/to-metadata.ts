import type { Metadata } from "next";
import type { PageMeta, SiteDefaults } from "@/site/domain/metadata";

/** Routes pass this to Next. The fields are the domain object's title, description and image. */
export function toMetadata(meta: SiteDefaults | PageMeta): Metadata {
  if ("metadataBase" in meta) {
    return {
      ...meta,
      icons: { icon: [...meta.icons.icon], apple: [...meta.icons.apple] },
    };
  }
  return {
    ...meta,
    ...(meta.openGraph ? { openGraph: { ...meta.openGraph, images: [...meta.openGraph.images] } } : {}),
    ...(meta.twitter ? { twitter: { ...meta.twitter, images: [...meta.twitter.images] } } : {}),
  };
}
