import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAMES } from "@/identity/domain/settings";
import { HOME_REWRITE_HEADER, routeRewriteForSession } from "@/site/domain/home-routing";

/**
 * Visitors stay on the static route. A session cookie (or `?t=` on a course) is rewritten to the dynamic twin.
 * A direct twin without the rewrite mark is sent to a `_` path so Next serves not-found.tsx with a real 404.
 * Next runs the proxy again on the rewritten path; HOME_REWRITE_HEADER lets that second pass through.
 * Catalog paths are guarded by their layouts, which read the active release.
 */
const NOT_FOUND_REWRITE = "/_not-routable";

function rewriteMarked(request: NextRequest, path: string) {
  const headers = new Headers(request.headers);
  headers.set(HOME_REWRITE_HEADER, "1");
  const url = new URL(request.url);
  url.pathname = path;
  return NextResponse.rewrite(url, { request: { headers } });
}

export function proxy(request: NextRequest) {
  const decision = routeRewriteForSession({
    pathname: request.nextUrl.pathname,
    hasTime: request.nextUrl.searchParams.has("t"),
    rewritten: request.headers.get(HOME_REWRITE_HEADER) === "1",
    cookieNames: SESSION_COOKIE_NAMES,
    hasCookie: (name) => request.cookies.has(name),
  });
  if (decision.kind === "next") return NextResponse.next();
  if (decision.kind === "not-found") return NextResponse.rewrite(new URL(NOT_FOUND_REWRITE, request.url));
  return rewriteMarked(request, decision.path);
}

// Literal paths: Next reads the matcher statically. It must equal proxyMatcher() from the route registry.
export const config = {
  matcher: ["/", "/signed-in-home", "/c/:path*", "/signed-in-c", "/signed-in-c/:path*"],
};
