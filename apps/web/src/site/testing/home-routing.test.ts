import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CACHE } from "../../kernel/cache.ts";
import { SESSION_COOKIE_NAMES } from "../../identity/domain/settings.ts";
import { proxyMatcher } from "../domain/route-registry.ts";
import { HOME_REWRITE_HEADER, routeRewriteForSession, SIGNED_IN_COURSE_PREFIX, SIGNED_IN_HOME_PATH } from "../domain/home-routing.ts";

const source = (file: string) => readFileSync(new URL(file, import.meta.url), "utf8");
const cookie = SESSION_COOKIE_NAMES[1];
const signedIn = (name: string) => name === cookie;
const decide = (pathname: string, hasCookie: (name: string) => boolean, hasTime = false, rewritten = false) =>
  routeRewriteForSession({ pathname, hasTime, rewritten, cookieNames: SESSION_COOKIE_NAMES, hasCookie });

describe("Course and lesson routing (static /c/ for visitors)", () => {
  it("serves static /c/ pages without a session cookie or ?t=", () => {
    expect(decide("/c/mit-x", () => false)).toEqual({ kind: "next" });
    expect(decide("/c/mit-x/lecture-1", () => false)).toEqual({ kind: "next" });
  });

  it("rewrites a session cookie or a ?t= deep link to the dynamic twin", () => {
    expect(decide("/c/mit-x", signedIn)).toEqual({ kind: "rewrite", path: `${SIGNED_IN_COURSE_PREFIX}/mit-x` });
    expect(decide("/c/mit-x/lecture-1", () => false, true)).toEqual({ kind: "rewrite", path: `${SIGNED_IN_COURSE_PREFIX}/mit-x/lecture-1` });
  });

  it("never serves the twin directly, only its marked rewrite", () => {
    const path = `${SIGNED_IN_COURSE_PREFIX}/mit-x`;
    expect(decide(path, signedIn)).toEqual({ kind: "not-found" });
    expect(decide(path, signedIn, false, true)).toEqual({ kind: "next" });
  });

  it("keeps the route config: static pages without request data, dynamic noindex twins, matched by the proxy", () => {
    for (const page of ["../../app/c/[courseSlug]/(course)/page.tsx", "../../app/c/[courseSlug]/[lessonSlug]/page.tsx"]) {
      const text = source(page);
      expect(text).toMatch(/export const revalidate = /);
      expect(text).not.toMatch(/force-dynamic|getViewerProgress/);
    }
    const twin = source(`../../app${SIGNED_IN_COURSE_PREFIX}/[courseSlug]/(course)/page.tsx`);
    expect(twin).toMatch(/export const dynamic = "force-dynamic";/);
    expect(twin).toMatch(/robots: \{ index: false, follow: false \}/);
    const proxy = source("../../proxy.ts");
    expect(proxy).toContain("SESSION_COOKIE_NAMES");
    expect(proxyMatcher().length).toBeGreaterThan(0);
  });
});

describe("Home routing (ADR-16)", () => {
  it("serves the static Home without a session cookie", () => {
    expect(decide("/", () => false)).toEqual({ kind: "next" });
    expect(decide("/", (name) => name === "open-university.session_data")).toEqual({ kind: "next" });
  });

  it("rewrites any session cookie, plain or __Secure-, to the dynamic Home", () => {
    expect(SESSION_COOKIE_NAMES).toEqual(["open-university.session_token", "__Secure-open-university.session_token"]);
    expect(decide("/", (name) => name === "open-university.session_token")).toEqual({ kind: "rewrite", path: SIGNED_IN_HOME_PATH });
    expect(decide("/", signedIn)).toEqual({ kind: "rewrite", path: SIGNED_IN_HOME_PATH });
  });

  it("never serves the internal route directly", () => {
    expect(decide(SIGNED_IN_HOME_PATH, signedIn)).toEqual({ kind: "not-found" });
    expect(decide(SIGNED_IN_HOME_PATH, signedIn, false, true)).toEqual({ kind: "next" });
  });

  it("keeps the route config: ISR Home without request data, dynamic signed-in Home, matched by the proxy", () => {
    const home = source("../../app/page.tsx");
    expect(CACHE.homeSeconds).toBe(300);
    expect(home).toMatch(/export const revalidate = 300 satisfies typeof CACHE\.homeSeconds;/);
    expect(home).not.toMatch(/force-dynamic|next\/headers|getViewerProgress|@\/progress|@\/auth/);
    const signed = source(`../../app${SIGNED_IN_HOME_PATH}/page.tsx`);
    expect(signed).toMatch(/export const dynamic = "force-dynamic";/);
    expect(signed).toMatch(/robots: \{ index: false, follow: false \}/);
    const proxy = source("../../proxy.ts");
    expect(HOME_REWRITE_HEADER).toBe("x-open-university-home-rewrite");
    expect(proxy).toContain("HOME_REWRITE_HEADER");
    const matcher = [...(proxy.match(/matcher:\s*\[([\s\S]*?)\]/)?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    expect(matcher).toEqual([...proxyMatcher()]);
  });
});
