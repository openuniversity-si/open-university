import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CATALOG_PATHS } from "./catalog-paths.ts";
import { PUBLIC_ROUTE_SPECS } from "./route-registry.ts";

const app = new URL("../../app/", import.meta.url).pathname;
function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return pages(full);
    return name === "page.tsx" ? [full] : [];
  });
}

describe("catalog revalidation paths", () => {
  it("is the registry invalidation plan, in registry order", () => {
    const expected = PUBLIC_ROUTE_SPECS.flatMap((spec) => spec.invalidation.map((entry) => (entry.type ? [entry.path, entry.type] : [entry.path])));
    expect(CATALOG_PATHS).toEqual(expected);
    expect(CATALOG_PATHS).toEqual([["/"], ["/sitemap.xml"], ["/c/[courseSlug]", "layout"], ["/universities", "layout"], ["/authors", "layout"], ["/credits"]]);
  });

  it("covers the Universities tab, its universities and areas, Authors, Credits and Home", () => {
    const covered = (route: string) => CATALOG_PATHS.some(([path, type]) => path === route || (type === "layout" && route.startsWith(`${path}/`)));
    for (const route of ["/", "/universities", "/universities/mit", "/universities/mit/artificial-intelligence", "/authors", "/credits", "/c/[courseSlug]", "/c/[courseSlug]/lesson"]) expect(covered(route), route).toBe(true);
  });

  it("every ISR page that reads the catalog is purged on publish", () => {
    for (const file of pages(app)) {
      let source = readFileSync(file, "utf8");
      if (source.includes('from "./view"')) source += readFileSync(join(file, "../view.tsx"), "utf8");
      if (!/export const revalidate = (?:\d+|false|CACHE\.\w+)/.test(source) || !source.includes("getCatalog")) continue;
      const route = `/${file.slice(app.length).replace(/\/?page\.tsx$/, "")}`.replace(/\/\[[^\]]+\]/g, "/[courseSlug]").replace(/\/\([^)]+\)/g, "");
      const covered = CATALOG_PATHS.some(([path, type]) => path === route || (type === "layout" && route.startsWith(`${path}/`)));
      expect(covered, route).toBe(true);
    }
  });
});
