import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import nextConfig from "../../next.config.ts";
import robots from "../../src/app/robots.ts";
import sitemap from "../../src/app/sitemap.ts";
import { indexingFacts } from "../../src/platform/host/env.ts";
import { robotsMetadata } from "../../src/site/domain/indexing.ts";

/**
 * Guardian for ADR-12: production (SITE_ENV=production) must be indexable whatever SITE_INDEXABLE says;
 * every other environment stays noindex. Reintroducing noindex or a total Disallow in production fails here.
 */
async function robotsHeaders(): Promise<unknown> {
  if (nextConfig.headers === undefined) throw new Error("next.config.ts must define headers()");
  const rules = await nextConfig.headers();
  // The report-only CSP (F09) is sent on every path regardless of indexing. Host-conditioned rules (alternate hosts, src/site/domain/hosts.ts)
  // stack on top of it and carry only their canonical Link header, never a robots header.
  for (const rule of rules.filter((entry) => entry.has !== undefined)) expect(rule.headers.map((header) => header.key)).toEqual(["Link"]);
  for (const rule of rules.filter((entry) => entry.has === undefined)) expect(rule.headers.map((header) => header.key)).toContain("Content-Security-Policy");
  return rules.map((rule) => ({ source: rule.source, headers: rule.headers.filter((header) => header.key === "X-Robots-Tag") })).filter((rule) => rule.headers.length > 0);
}

const NOINDEX_EVERYWHERE = [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
const DISALLOW_ALL = { rules: { userAgent: "*", disallow: "/" } };

describe("production is indexable (SITE_ENV=production)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([undefined, "false", "no", "true"])("with SITE_INDEXABLE=%j: no X-Robots-Tag, robots allows pages and points at the sitemap", async (value) => {
    vi.stubEnv("SITE_ENV", "production");
    vi.stubEnv("SITE_INDEXABLE", value);
    expect(await robotsHeaders()).toEqual([]);
    expect(robots()).toEqual({ rules: [{ userAgent: "*", allow: "/", disallow: ["/api/"] }], sitemap: "https://openuniversity.si/sitemap.xml" });
    expect(JSON.stringify(robots())).not.toMatch(/"disallow":"\/"|"disallow":\["\/"\]/);
    expect(robotsMetadata(indexingFacts(process.env))).toEqual({ index: true, follow: true });
  });
});

describe("everything else stays noindex", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([[undefined, undefined], ["preview", undefined], ["preview", "false"], ["development", undefined], [undefined, "1"]])("SITE_ENV=%j SITE_INDEXABLE=%j", async (siteEnv, value) => {
    vi.stubEnv("SITE_ENV", siteEnv);
    vi.stubEnv("SITE_INDEXABLE", value);
    expect(await robotsHeaders()).toEqual(NOINDEX_EVERYWHERE);
    expect(robots()).toEqual(DISALLOW_ALL);
    expect(robotsMetadata(indexingFacts(process.env))).toEqual({ index: false, follow: false });
  });

  it("allows the explicit SITE_INDEXABLE=\"true\" opt-in for local verification builds", async () => {
    vi.stubEnv("SITE_ENV", undefined);
    vi.stubEnv("SITE_INDEXABLE", "true");
    expect(await robotsHeaders()).toEqual([]);
    expect(robots().rules).toEqual([{ userAgent: "*", allow: "/", disallow: ["/api/"] }]);
  });
});

describe("sitemap", () => {
  it("is environment-independent and only lists absolute production URLs without dates", async () => {
    const entries = await sitemap();
    expect(entries.every((entry) => entry.url.startsWith("https://openuniversity.si/") && Object.keys(entry).join() === "url")).toBe(true);
  });
});
