/** The address the current host puts on a request. Callers do not read the forwarding header. */

const forwardedHeader = "x-forwarded-for";

/**
 * Header the host rewrites before the app sees the request.
 * The session library is told this name and no other.
 */
export function sessionAddressHeaders(): readonly string[] {
  return [forwardedHeader];
}

/** First address the host wrote, then the single-address header, then unknown. */
export function requestAddress(headers: Headers): string {
  return headers.get(forwardedHeader)?.split(",")[0]?.trim() || headers.get("x-real-ip") || "unknown";
}
