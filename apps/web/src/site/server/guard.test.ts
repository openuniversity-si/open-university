import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
const navigation = vi.hoisted(() => ({
  notFound: () => { throw new Error("404"); },
  permanentRedirect: (to: string) => { throw new Error(`308 ${to}`); },
}));
vi.mock("next/navigation", () => navigation);
import { guardCatalogPath } from "./guard.ts";
import type { PublicRouteSnapshot } from "../domain/route-registry.ts";

const snapshot: PublicRouteSnapshot = {
  courses: [{ slug: "alpha", lessonSlugs: ["one"] }],
  institutions: [],
  redirects: [{ from: "/c/old", to: "/c/alpha" }],
};

describe("guardCatalogPath", () => {
  it("lets a live path through, redirects a moved one and 404s a missing one before streaming", () => {
    expect(() => { guardCatalogPath("/c/alpha", snapshot); }).not.toThrow();
    expect(() => { guardCatalogPath("/c/alpha/", snapshot); }).not.toThrow();
    expect(() => { guardCatalogPath("/c/old", snapshot); }).toThrow("308 /c/alpha");
    expect(() => { guardCatalogPath("/c/missing", snapshot); }).toThrow("404");
  });
});
