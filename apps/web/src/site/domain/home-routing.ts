/**
 * Session split for public routes (ADR-16). Cookie names are an argument: this module does not import identity.
 * Only the cookie's presence selects the twin. The twin validates the session; an expired cookie renders the visitor page.
 * Universities, authors and legal pages show no per-user state, so they stay on the static route (D-037).
 * `?t=` deep links apply to courses only.
 */

export const SIGNED_IN_HOME_PATH = "/signed-in-home";
export const SIGNED_IN_COURSE_PREFIX = "/signed-in-c";

/** Set by the proxy on its own rewrite; Next runs the proxy again on the rewritten path. */
export const HOME_REWRITE_HEADER = "x-open-university-home-rewrite";

export type RouteDecision = { readonly kind: "next" } | { readonly kind: "not-found" } | { readonly kind: "rewrite"; readonly path: string };

const INTERNAL_EXACT = new Set([SIGNED_IN_HOME_PATH]);
const INTERNAL_PREFIXES = [SIGNED_IN_COURSE_PREFIX];

function internal(pathname: string): boolean {
  if (INTERNAL_EXACT.has(pathname)) return true;
  return INTERNAL_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function routeRewriteForSession(input: {
  readonly pathname: string;
  readonly hasTime: boolean;
  readonly rewritten: boolean;
  readonly cookieNames: readonly string[];
  readonly hasCookie: (name: string) => boolean;
}): RouteDecision {
  const { pathname, hasTime, rewritten, cookieNames, hasCookie } = input;
  if (internal(pathname)) return rewritten ? { kind: "next" } : { kind: "not-found" };
  const signedIn = cookieNames.some(hasCookie);
  if (pathname === "/") return signedIn ? { kind: "rewrite", path: SIGNED_IN_HOME_PATH } : { kind: "next" };
  if (pathname.startsWith("/c/")) {
    return signedIn || hasTime ? { kind: "rewrite", path: `${SIGNED_IN_COURSE_PREFIX}${pathname.slice(2)}` } : { kind: "next" };
  }
  return { kind: "next" };
}
