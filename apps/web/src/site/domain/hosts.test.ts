import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import { installSiteData, parseSiteData } from "./site-data.ts";
installSiteData(parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))));
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import nextConfig from "../../../next.config.ts";
import robots from "../../app/robots.ts";
import sitemap from "../../app/sitemap.ts";
import { ALTERNATE_HOSTS, alternateHostRedirects, CANONICAL_HOST, hostRole, normalizeHost, PERMANENT_REDIRECT_HOSTS, TEMPORARY_REDIRECT_HOSTS } from "./hosts.ts";
import { courseMetadataInput, lessonMetadataInput } from "../../catalog/server/metadata.ts";
import { publicRouteSnapshot } from "../../catalog/server/public-routes.ts";
import { courseMetadata, lessonMetadata, staticPageMetadata } from "./metadata.ts";
import { PRODUCTION_ORIGIN } from "./origin.ts";
import { PUBLIC_STATIC_ROUTES, publicCatalogRoutes } from "./route-registry.ts";

describe("host configuration (openuniversity.si is canonical, every other address redirects)", () => {
  it("keeps openuniversity.si canonical", () => {
    expect(CANONICAL_HOST).toBe("openuniversity.si");
    expect(PRODUCTION_ORIGIN).toBe("https://openuniversity.si"); // pragma: allowlist secret
  });

  it("lists bare, lowercase, unique hostnames, never the canonical one", () => {
    expect(new Set(ALTERNATE_HOSTS).size).toBe(ALTERNATE_HOSTS.length);
    for (const host of ALTERNATE_HOSTS) {
      expect(host).toMatch(/^[a-z0-9-]+(\.[a-z0-9-]+)+$/);
      expect(host).not.toBe(CANONICAL_HOST);
    }
  });

  it("redirects thetower.si temporarily and the other Open University addresses permanently", () => {
    expect([...TEMPORARY_REDIRECT_HOSTS].sort()).toEqual(["thetower.si", "www.thetower.si"].sort());
    expect([...PERMANENT_REDIRECT_HOSTS].sort()).toEqual(["theopenuniversity.si", "www.openuniversity.si", "www.theopenuniversity.si"].sort());
    expect([...ALTERNATE_HOSTS].sort()).toEqual(["thetower.si", "theopenuniversity.si", "www.openuniversity.si", "www.theopenuniversity.si", "www.thetower.si"].sort());
  });

  it("never lists the media host: media.openuniversity.si is R2 and does not reach this app", () => {
    expect(ALTERNATE_HOSTS as readonly string[]).not.toContain("media.openuniversity.si");
    expect(hostRole("media.openuniversity.si")).toBe("other");
  });
});

describe("normalizeHost and hostRole", () => {
  it.each([
    ["OpenUniversity.SI", "openuniversity.si"],
    ["openuniversity.si:443", "openuniversity.si"],
    ["openuniversity.si.", "openuniversity.si"],
    ["  www.thetower.si ", "www.thetower.si"],
    [undefined, ""],
    [null, ""],
  ])("normalizes %j to %j", (raw, host) => {
    expect(normalizeHost(raw)).toBe(host);
  });

  it("names the canonical host", () => {
    expect(hostRole("openuniversity.si")).toBe("canonical");
    expect(hostRole("OpenUniversity.SI:3000")).toBe("canonical");
  });

  it.each(ALTERNATE_HOSTS)("names %s an alternate host", (host) => {
    expect(hostRole(host)).toBe("alternate");
    expect(hostRole(host.toUpperCase())).toBe("alternate");
  });

  it.each(["the-tower-abc123.preview.example.invalid", "localhost:3100", "127.0.0.1", "evil-openuniversity.si", "openuniversity.si.evil.com", "thetower.si.evil.com", "media.thetower.si", "", undefined])("treats %j as another host", (host) => {
    expect(hostRole(host)).toBe("other");
  });
});

describe("alternateHostRedirects", () => {
  const rules = alternateHostRedirects();

  it("is one rule per alternate host, matched on the Host header, sending every path to the canonical origin", () => {
    expect(rules).toHaveLength(ALTERNATE_HOSTS.length);
    for (const host of ALTERNATE_HOSTS) {
      const own = rules.filter((rule) => rule.has[0]?.value === host);
      expect(own).toHaveLength(1);
      expect(own[0]?.has).toEqual([{ type: "host", value: host }]);
      expect(own[0]?.source).toBe("/:path*");
      expect(own[0]?.destination).toBe("https://openuniversity.si/:path*"); // pragma: allowlist secret
    }
  });

  it("is temporary (307) for thetower.si, because The Tower will get its own site, and permanent (308) for the other addresses", () => {
    for (const rule of rules) {
      const host = rule.has[0]?.value ?? "";
      expect(rule.permanent, host).toBe(!(TEMPORARY_REDIRECT_HOSTS as readonly string[]).includes(host));
    }
    expect(rules.filter((rule) => !rule.permanent).map((rule) => rule.has[0]?.value).sort()).toEqual(["thetower.si", "www.thetower.si"].sort());
  });

  it("grows by configuration: a new host is a new rule and nothing else", () => {
    expect(alternateHostRedirects(["example.test"], []).map((rule) => rule.has[0]?.value)).toEqual(["example.test"]);
  });

  it("is wired into next.config redirects() and adds no Link or robots headers per host", async () => {
    expect(await nextConfig.redirects?.()).toEqual(rules);
    const headers = await nextConfig.headers?.();
    expect((headers ?? []).filter((rule) => rule.has?.some((condition) => condition.type === "host"))).toEqual([]);
  });
});

describe("no public output names an alternate host (every URL is on the canonical openuniversity.si)", () => {
  const mentionsAlternate = (text: string) => ALTERNATE_HOSTS.some((host) => text.includes(host));

  it("keeps every canonical and Open Graph URL on the canonical origin", () => {
    const metadata = [
      ...PUBLIC_STATIC_ROUTES.map((route) => staticPageMetadata(route)),
      ...publicCatalogRoutes(publicRouteSnapshot(catalog)).map((route) => (route.lessonSlug === undefined ? courseMetadata(courseMetadataInput(catalog, route.courseSlug)) : lessonMetadata(lessonMetadataInput(catalog, route.courseSlug, route.lessonSlug)))),
    ];
    for (const entry of metadata) {
      expect(mentionsAlternate(JSON.stringify(entry.alternates)), "canonical").toBe(false);
      expect(mentionsAlternate(JSON.stringify(entry.openGraph)), "open graph").toBe(false);
    }
  });

  it("lists only canonical URLs in the sitemap", async () => {
    for (const entry of await sitemap()) expect(entry.url.startsWith(`${PRODUCTION_ORIGIN}/`)).toBe(true);
  });

  it("points robots.txt at the canonical sitemap, with no extra host and no blanket Disallow in production", () => {
    const previous = process.env.SITE_ENV;
    process.env.SITE_ENV = "production";
    try {
      const result = robots();
      expect(result.sitemap).toBe(`${PRODUCTION_ORIGIN}/sitemap.xml`);
      expect(result.host).toBeUndefined();
      expect(JSON.stringify(result)).not.toMatch(/"disallow":"\/"/);
      expect(mentionsAlternate(JSON.stringify(result))).toBe(false);
    } finally {
      if (previous === undefined) delete process.env.SITE_ENV;
      else process.env.SITE_ENV = previous;
    }
  });
});
