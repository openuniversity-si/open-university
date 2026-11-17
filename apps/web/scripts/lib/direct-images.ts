/** Assert the built application cannot send a visitor to a request-metered image optimizer. */
export function assertDirectImages(config: { images?: { unoptimized?: boolean; loaderFile?: string; loader?: string } }, html: string): void {
  if (config.images?.unoptimized !== true || config.images.loaderFile || (config.images.loader && config.images.loader !== "default")) {
    throw new Error("Direct images required: disable image optimization; no metered replacement loader (ADR-31).");
  }
  if (/(?:\/|%2f)_next(?:\/|%2f)image|\/cdn-cgi\/image\//i.test(html)) throw new Error("Image optimizer URL in generated HTML (ADR-31).");
}
