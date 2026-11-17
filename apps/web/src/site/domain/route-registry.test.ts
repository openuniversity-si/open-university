import { describe, expect, it } from "vitest";
import { catalogPathStatus, proxyMatcher, PUBLIC_ROUTE_SPECS, PUBLIC_STATIC_ROUTES, publicCatalogRoutes, publicPaths, publicUniversityPaths, type PublicRouteSnapshot } from "./route-registry.ts";

const snapshot: PublicRouteSnapshot = {
  courses: [{ slug: "alpha", lessonSlugs: ["one", "two"] }, { slug: "beta", lessonSlugs: ["only"] }],
  institutions: [{ slug: "mit", areaIds: ["psychology", "economics"] }],
  redirects: [{ from: "/c/old", to: "/c/alpha" }, { from: "/c/old/lesson", to: "/c/alpha/one" }],
};

describe("public route registry", () => {
  it("lists static pages, institutions and catalog paths, and drops a removed family", () => {
    expect(publicPaths(snapshot)).toEqual([
      ...PUBLIC_STATIC_ROUTES,
      "/universities/mit", "/universities/mit/psychology", "/universities/mit/economics",
      "/c/alpha", "/c/alpha/one", "/c/alpha/two", "/c/beta", "/c/beta/only",
    ]);
    const withoutCourses = { ...snapshot, courses: [] };
    expect(publicPaths(withoutCourses).some((path) => path.startsWith("/c/"))).toBe(false);
    expect(publicUniversityPaths({ ...snapshot, institutions: [] })).toEqual([]);
    expect(publicCatalogRoutes(snapshot).map((route) => route.path)).toEqual(["/c/alpha", "/c/alpha/one", "/c/alpha/two", "/c/beta", "/c/beta/only"]);
  });

  it("answers live, redirect and missing for catalog paths, ignoring a trailing slash", () => {
    expect(catalogPathStatus(snapshot, "/c/alpha")).toEqual({ kind: "live" });
    expect(catalogPathStatus(snapshot, "/c/alpha/")).toEqual({ kind: "live" });
    expect(catalogPathStatus(snapshot, "/c/alpha/two")).toEqual({ kind: "live" });
    expect(catalogPathStatus(snapshot, "/c/old")).toEqual({ kind: "redirect", to: "/c/alpha" });
    expect(catalogPathStatus(snapshot, "/c/old/lesson/")).toEqual({ kind: "redirect", to: "/c/alpha/one" });
    expect(catalogPathStatus(snapshot, "/c/zzz")).toEqual({ kind: "missing" });
    expect(catalogPathStatus(snapshot, "/c/alpha/foreign")).toEqual({ kind: "missing" });
    expect(catalogPathStatus({ ...snapshot, courses: snapshot.courses.slice(1) }, "/c/alpha")).toEqual({ kind: "missing" });
  });

  it("derives the proxy matcher from signed-in families only", () => {
    expect([...proxyMatcher()]).toEqual(["/", "/signed-in-home", "/c/:path*", "/signed-in-c", "/signed-in-c/:path*"]);
    expect(PUBLIC_ROUTE_SPECS.filter((spec) => spec.includeInSitemap && spec.internalPrefix).map((spec) => spec.id)).toEqual(["home", "course", "lesson"]);
    expect(PUBLIC_STATIC_ROUTES.every((route) => PUBLIC_ROUTE_SPECS.some((spec) => spec.pattern === route))).toBe(true);
  });
});
