import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { NextRequest, type NextResponse } from "next/server";
import { SESSION_COOKIE_NAMES } from "@/identity/domain/settings";
import { HOME_REWRITE_HEADER } from "@/site/domain/home-routing";
import { proxyMatcher } from "@/site/domain/route-registry";
import { proxy, config } from "./proxy.ts";

function request(pathname: string, options: { cookie?: string; time?: boolean; rewritten?: boolean } = {}) {
  const url = new URL(`http://127.0.0.1:3999${pathname}${options.time ? "?t=12" : ""}`);
  const headers = new Headers(options.rewritten ? { [HOME_REWRITE_HEADER]: "1" } : {});
  if (options.cookie) headers.set("cookie", `${options.cookie}=1`);
  return new NextRequest(url, { headers });
}

const rewritePath = (response: NextResponse) => response.headers.get("x-middleware-rewrite") ?? response.headers.get("location");

describe("proxy", () => {
  it("repeats the registry matcher as a Next literal and passes identity cookie names in", () => {
    expect([...config.matcher]).toEqual([...proxyMatcher()]);
    const source = readFileSync(new URL("./proxy.ts", import.meta.url), "utf8");
    expect(source).toContain("SESSION_COOKIE_NAMES");
    expect(source).not.toContain("identity/server");
    expect(SESSION_COOKIE_NAMES.length).toBeGreaterThan(0);
  });

  it("rewrites a session to the twin, preserves ?t=, and 404s a direct twin", () => {
    const cookie = SESSION_COOKIE_NAMES[0];
    const home = proxy(request("/", { cookie }));
    expect(rewritePath(home)).toContain("/signed-in-home");
    expect(home.headers.get("x-middleware-request-x-open-university-home-rewrite") ?? home.headers.get(HOME_REWRITE_HEADER)).toBeTruthy();
    const course = proxy(request("/c/mit-x/lecture-1", { time: true }));
    expect(rewritePath(course)).toContain("/signed-in-c/mit-x/lecture-1");
    expect(rewritePath(course)).toContain("t=12");
    expect(rewritePath(proxy(request("/universities/mit/economics", { cookie })))).toBeNull();
    expect(rewritePath(proxy(request("/authors", { cookie })))).toBeNull();
    expect(rewritePath(proxy(request("/privacy", { cookie })))).toBeNull();
    const direct = proxy(request("/signed-in-c/mit-x", { cookie }));
    expect(rewritePath(direct)).toContain("/_not-routable");
    expect(rewritePath(proxy(request("/signed-in-home", { cookie, rewritten: true })))).toBeNull();
  });
});
