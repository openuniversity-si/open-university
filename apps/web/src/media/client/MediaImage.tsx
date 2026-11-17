import Image from "next/image";
import { coverUnavailable } from "@/site/domain/reader-copy.ts";
import type { MediaAsset } from "../domain/types.ts";

/** Course and lesson screens pass the asset from a grouped read (`getCourseMedia`/`getLessonMedia`); none keeps the placeholder. */
export function MediaImage({ asset, sizes, className }: { asset: MediaAsset | undefined; sizes: string; className?: string }) {
  if (!asset) return <span className={className} role="img" aria-label={coverUnavailable} data-media-placeholder />;
  // perf: pre-optimized at the origin; enforce direct delivery even outside the app's Next config.
  return <Image unoptimized className={className} src={asset.url} alt={asset.alt} width={asset.width} height={asset.height} sizes={sizes} />;
}
