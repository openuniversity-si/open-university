import type { MediaAsset } from "@/media/domain/types";

/**
 * The lesson cover `getLessonMedia` already resolved and tagged `cover_16x9`.
 * The page paints this asset. It does not choose another figure.
 */
export function chosenLessonCover(assets: readonly MediaAsset[] | undefined): MediaAsset | undefined {
  return assets?.find((asset) => asset.isActive && asset.kind === "cover_16x9" && asset.variant === "default");
}
