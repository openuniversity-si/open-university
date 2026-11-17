const raster = /\.(?:png|jpe?g|gif|webp|avif|bmp|tiff?|ico)$/i;
/**
 * Raster files git may track: the logo and wordmark, UI icons/favicons in `public/icons/`, and the Open Graph
 * brand card `public/brand/og.*` (ADR-13; a Genesis cover appears in it only reduced and darkened). Covers and
 * every other image live in R2.
 */
const allowed = /^apps\/web\/public\/(?:brand\/(?:logo|wordmark|og)\.[a-z0-9]+|icons\/[^\n]+)$/;

/** Tracked raster files outside the allowlist. */
export function rejectedRasterFiles(tracked: readonly string[]): string[] {
  return tracked.filter((file) => raster.test(file) && !allowed.test(file));
}
