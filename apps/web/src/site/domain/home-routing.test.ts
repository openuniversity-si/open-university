import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CACHE } from "../../kernel/cache.ts";
import { SESSION_COOKIE_NAMES } from "../../identity/domain/settings.ts";
import { proxyMatcher } from "./route-registry.ts";
import { HOME_REWRITE_HEADER, routeRewriteForSession, SIGNED_IN_COURSE_PREFIX, SIGNED_IN_HOME_PATH } from "./home-routing.ts";

const source = (file: string) => readFileSync(new URL(file, import.meta.url), "utf8");
const cookie = SESSION_COOKIE_NAMES[1];
const signedIn = (name: string) => name === cookie;
const decide = (pathname: string, hasCookie: (name: string) => boolean, hasTime = false, rewritten = false) =>
  routeRewriteForSession({ pathname, hasTime, rewritten, cookieNames: SESSION_COOKIE_NAMES, hasCookie });

describe("session rewrites", () => {
  it("serves public pages without a session cookie", () => {
    expect(SESSION_COOKIE_NAMES).toEqual(["open-university.session_token", "__Secure-open-university.session_token"]);
    for (const path of ["/", "/c/mit-x", "/c/mit-x/lecture-1", "/universities", "/universities/mit", "/universities/mit/economics", "/authors", "/privacy"]) {
      expect(decide(path, () => false), path).toEqual({ kind: "next" });
    }
    expect(decide("/", (name) => name === "open-university.session_data")).toEqual({ kind: "next" });
  });

  it("rewrites a session cookie to the private twin and keeps legal pages public", () => {
    expect(decide("/", signedIn)).toEqual({ kind: "rewrite", path: SIGNED_IN_HOME_PATH });
    expect(decide("/c/mit-x", signedIn)).toEqual({ kind: "rewrite", path: `${SIGNED_IN_COURSE_PREFIX}/mit-x` });
    expect(decide("/c/mit-x/lecture-1", () => false, true)).toEqual({ kind: "rewrite", path: `${SIGNED_IN_COURSE_PREFIX}/mit-x/lecture-1` });
    expect(decide("/universities", signedIn)).toEqual({ kind: "next" });
    expect(decide("/universities/mit", signedIn)).toEqual({ kind: "next" });
    expect(decide("/universities/mit/economics", signedIn)).toEqual({ kind: "next" });
    expect(decide("/authors", signedIn)).toEqual({ kind: "next" });
    expect(decide("/privacy", signedIn, true)).toEqual({ kind: "next" });
    expect(decide("/terms", signedIn)).toEqual({ kind: "next" });
    expect(decide("/universities/mit", () => false, true)).toEqual({ kind: "next" });
  });

  it("blocks a direct twin and lets the marked second pass through", () => {
    for (const path of [SIGNED_IN_HOME_PATH, `${SIGNED_IN_COURSE_PREFIX}/mit-x`, `${SIGNED_IN_COURSE_PREFIX}/mit-x/lecture-1`]) {
      expect(decide(path, signedIn), path).toEqual({ kind: "not-found" });
      expect(decide(path, signedIn, false, true), path).toEqual({ kind: "next" });
    }
    expect(decide("/", () => false, false, true)).toEqual({ kind: "next" });
  });

  it("keeps visitor pages static and twins dynamic, noindex, and matched from the registry", () => {
    const home = source("../../app/page.tsx");
    expect(CACHE.homeSeconds).toBe(300);
    expect(home).toMatch(/export const revalidate = 300 satisfies typeof CACHE\.homeSeconds;/);
    expect(home).not.toMatch(/force-dynamic|next\/headers|getViewerProgress|@\/progress|@\/auth/);
    const signedInHome = source(`../../app${SIGNED_IN_HOME_PATH}/page.tsx`);
    expect(signedInHome).toMatch(/export const dynamic = "force-dynamic";/);
    expect(signedInHome).toMatch(/robots: \{ index: false, follow: false \}/);
    for (const page of ["../../app/c/[courseSlug]/(course)/page.tsx", "../../app/c/[courseSlug]/[lessonSlug]/page.tsx", "../../app/universities/page.tsx", "../../app/authors/page.tsx"]) {
      expect(source(page)).toMatch(/export const revalidate = /);
      expect(source(page)).not.toMatch(/force-dynamic|getViewerProgress/);
    }
    for (const twin of [`../../app${SIGNED_IN_COURSE_PREFIX}/[courseSlug]/(course)/page.tsx`, `../../app${SIGNED_IN_COURSE_PREFIX}/[courseSlug]/[lessonSlug]/page.tsx`]) {
      const text = source(twin);
      expect(text).toMatch(/export const dynamic = "force-dynamic";/);
      expect(text).toMatch(/robots: \{ index: false, follow: false \}/);
      expect(text).toMatch(/getViewerProgress\(/);
    }
    const proxy = source("../../proxy.ts");
    expect(HOME_REWRITE_HEADER).toBe("x-open-university-home-rewrite");
    expect(proxy).toContain("HOME_REWRITE_HEADER");
    expect(proxy).toContain("SESSION_COOKIE_NAMES");
    const matcher = [...(proxy.match(/matcher:\s*\[([\s\S]*?)\]/)?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    expect(matcher).toEqual([...proxyMatcher()]);
  });
});
