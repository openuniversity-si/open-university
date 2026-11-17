import { PRODUCTION_ORIGIN } from "./origin.ts";

/**
 * Hosts of this app (ADR-12, ADR-19, ADR-20). Relative imports only: `next.config.ts` loads this module in plain Node.
 *
 * `openuniversity.si` is the one canonical host and the only one that serves pages. Every other address of the project answers with a redirect
 * to it, keeping the path and the query. Canonical links, Open Graph URLs, the sitemap and the robots.txt pointer are all built from
 * PRODUCTION_ORIGIN, never from the request host.
 *
 * - `thetower.si` and `www.thetower.si` are redirected **temporarily (307)**: The Tower will get its own site later, so the move must not be
 *   cached as permanent by browsers or search engines.
 * - `www.openuniversity.si`, `theopenuniversity.si` and `www.theopenuniversity.si` are redirected **permanently (308)** to the apex.
 *
 * The media host (`MEDIA_PUBLIC_HOST`, src/media/domain/types.ts) is not here: it is Cloudflare R2 and never reaches this app.
 */
export const CANONICAL_HOST = new URL(PRODUCTION_ORIGIN).host;

/** THE lists. A new address is one more entry (and the domain on the edge in front of the app, which may redirect before the app is reached). */
export const TEMPORARY_REDIRECT_HOSTS = ["thetower.si", "www.thetower.si"] as const;
export const PERMANENT_REDIRECT_HOSTS = ["www.openuniversity.si", "theopenuniversity.si", "www.theopenuniversity.si"] as const;
export const ALTERNATE_HOSTS = [...TEMPORARY_REDIRECT_HOSTS, ...PERMANENT_REDIRECT_HOSTS] as const;

export type HostRole = "canonical" | "alternate" | "other";

/** `Host` header value to a bare lowercase hostname: no port, no trailing dot. */
export function normalizeHost(raw: string | null | undefined): string {
  return (raw ?? "").trim().toLowerCase().replace(/:\d+$/, "").replace(/\.$/, "");
}

export function hostRole(raw: string | null | undefined): HostRole {
  const host = normalizeHost(raw);
  if (host === CANONICAL_HOST) return "canonical";
  return (ALTERNATE_HOSTS as readonly string[]).includes(host) ? "alternate" : "other";
}

/**
 * What `next.config.ts` returns from `redirects()`: one rule per alternate host, matched on the Host header, sending every path (and its query)
 * to the same path on the canonical origin. `permanent: false` is a 307 and `permanent: true` a 308 (both keep the method). The edge may
 * redirect the same hosts; this list is the declarative record and the fallback if a domain loses its edge redirect.
 */
export function alternateHostRedirects(temporary: readonly string[] = TEMPORARY_REDIRECT_HOSTS, permanent: readonly string[] = PERMANENT_REDIRECT_HOSTS) {
  const rule = (host: string, isPermanent: boolean) => ({
    source: "/:path*",
    has: [{ type: "host" as const, value: host }],
    destination: `${PRODUCTION_ORIGIN}/:path*`,
    permanent: isPermanent,
  });
  return [...temporary.map((host) => rule(host, false)), ...permanent.map((host) => rule(host, true))];
}
