/**
 * Public route policy (state 2.4). Structural snapshot in, paths out.
 * Catalog and identity stay outside this module: adapters fill the snapshot.
 */

export interface PublicRouteSnapshot {
  readonly courses: readonly { readonly slug: string; readonly lessonSlugs: readonly string[] }[];
  readonly institutions: readonly { readonly slug: string; readonly areaIds: readonly string[] }[];
  readonly redirects: readonly { readonly from: string; readonly to: string }[];
}

export interface PublicRouteSpec {
  readonly id: "home" | "course" | "lesson" | "institution-index" | "institution" | "institution-area" | "authors" | "credits" | "privacy" | "about" | "terms" | "contact";
  readonly pattern: string;
  readonly supportsSignedInVariant: boolean;
  readonly internalPrefix?: string;
  readonly includeInSitemap: boolean;
  readonly invalidation: readonly { readonly path: string; readonly type?: "page" | "layout" }[];
}

/** Registry order is the invalidation order. Signed-in twins are internalPrefix, never their own spec. */
export const PUBLIC_ROUTE_SPECS: readonly PublicRouteSpec[] = [
  { id: "home", pattern: "/", supportsSignedInVariant: true, internalPrefix: "/signed-in-home", includeInSitemap: true, invalidation: [{ path: "/" }, { path: "/sitemap.xml" }] },
  { id: "course", pattern: "/c/:course", supportsSignedInVariant: true, internalPrefix: "/signed-in-c", includeInSitemap: true, invalidation: [{ path: "/c/[courseSlug]", type: "layout" }] },
  { id: "lesson", pattern: "/c/:course/:lesson", supportsSignedInVariant: true, internalPrefix: "/signed-in-c", includeInSitemap: true, invalidation: [] },
  { id: "institution-index", pattern: "/universities", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [{ path: "/universities", type: "layout" }] },
  { id: "institution", pattern: "/universities/:slug", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "institution-area", pattern: "/universities/:slug/:area", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "authors", pattern: "/authors", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [{ path: "/authors", type: "layout" }] },
  { id: "privacy", pattern: "/privacy", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "terms", pattern: "/terms", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "contact", pattern: "/contact", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "about", pattern: "/about", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [] },
  { id: "credits", pattern: "/credits", supportsSignedInVariant: false, includeInSitemap: true, invalidation: [{ path: "/credits" }] },
];

/** Every public non-catalog page (sitemap, metadata guardians). A new static page adds its path here and in the registry. */
export const PUBLIC_STATIC_ROUTES = ["/", "/universities", "/authors", "/privacy", "/terms", "/contact", "/about", "/credits"] as const;
export type PublicStaticRoute = (typeof PUBLIC_STATIC_ROUTES)[number];

export interface CatalogRoute {
  readonly path: string;
  readonly courseSlug: string;
  readonly lessonSlug?: string;
}

/** `/c/<course>` for every course of the snapshot, followed by its lessons in order. */
export function publicCatalogRoutes(snapshot: PublicRouteSnapshot): CatalogRoute[] {
  return snapshot.courses.flatMap((course) => [
    { path: `/c/${course.slug}`, courseSlug: course.slug },
    ...course.lessonSlugs.map((lessonSlug) => ({ path: `/c/${course.slug}/${lessonSlug}`, courseSlug: course.slug, lessonSlug })),
  ]);
}

/** `/universities/<university>` and its `/<area>` pages: only institutions and areas present on the snapshot. */
export function publicUniversityPaths(snapshot: PublicRouteSnapshot): string[] {
  return snapshot.institutions.flatMap((entry) => [`/universities/${entry.slug}`, ...entry.areaIds.map((area) => `/universities/${entry.slug}/${area}`)]);
}

/** Static pages first, then the universities, then the catalog: the full public URL list, as paths. */
export function publicPaths(snapshot: PublicRouteSnapshot): string[] {
  return [...PUBLIC_STATIC_ROUTES, ...publicUniversityPaths(snapshot), ...publicCatalogRoutes(snapshot).map((route) => route.path)];
}

export type CatalogPathStatus = { readonly kind: "live" } | { readonly kind: "redirect"; readonly to: string } | { readonly kind: "missing" };

/**
 * A `/c/...` path is live when the snapshot publishes it, moved when a redirect names it, and missing otherwise.
 * Trailing slashes are ignored. The layout guards answer 308 or a real 404 before streaming.
 */
export function catalogPathStatus(snapshot: PublicRouteSnapshot, pathname: string): CatalogPathStatus {
  const path = pathname.replace(/\/+$/, "");
  if (publicCatalogRoutes(snapshot).some((route) => route.path === path)) return { kind: "live" };
  const to = snapshot.redirects.find((redirect) => redirect.from === path)?.to;
  return to === undefined ? { kind: "missing" } : { kind: "redirect", to };
}

/**
 * Literal Next.js matcher derived from the registry. `proxy.ts` repeats it as a static array
 * (Next does not evaluate a function); the architecture check requires the two to match.
 */
export function proxyMatcher(specs: readonly PublicRouteSpec[] = PUBLIC_ROUTE_SPECS): readonly string[] {
  const out: string[] = [];
  const push = (item: string) => { if (!out.includes(item)) out.push(item); };
  const dynamicInternal = new Set(specs.filter((spec) => spec.pattern.includes(":") && spec.internalPrefix).map((spec) => spec.internalPrefix));
  for (const spec of specs) {
    if (!spec.supportsSignedInVariant || spec.internalPrefix === undefined) continue;
    if (spec.pattern === "/") push("/");
    else if (spec.pattern.includes(":")) push(`/${spec.pattern.split("/")[1] ?? ""}/:path*`);
    else push(spec.pattern);
    push(spec.internalPrefix);
    if (dynamicInternal.has(spec.internalPrefix)) push(`${spec.internalPrefix}/:path*`);
  }
  return out;
}
