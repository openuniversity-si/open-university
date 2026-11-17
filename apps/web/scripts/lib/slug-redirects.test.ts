import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { pageUrls, parsePairs, verifySlugRedirects, type SlugPair } from "./slug-redirects.ts";

/** A fake site: `redirects` answer 308, `pages` 200 with their canonical/og:url, the sitemap lists `sitemap`, the rest 404. */
interface Site { redirects: Record<string, string>; pages: Record<string, { canonical: string; ogUrl: string }>; sitemap: string[]; flaky: Record<string, number>; sitemapStatus?: number; missingStatus?: number }
let site: Site;
let server: Server;
let base = "";
const requests: string[] = [];

beforeAll(async () => {
  server = createServer((request, response) => {
    const path = request.url ?? "/";
    requests.push(path);
    const flaky = site.flaky[path] ?? 0;
    if (flaky > 0) {
      site.flaky[path] = flaky - 1;
      if (flaky % 2 === 0) { request.socket.destroy(); return; }
      response.writeHead(503).end();
      return;
    }
    const to = site.redirects[path];
    if (to) { response.writeHead(308, { location: to }).end(); return; }
    const page = site.pages[path];
    if (page) {
      response.writeHead(200, { "content-type": "text/html" }).end(`<html><head><meta content="${page.ogUrl}" property="og:url"><link href="${page.canonical}" rel="canonical"></head></html>`);
      return;
    }
    if (path === "/sitemap.xml") {
      response.writeHead(site.sitemapStatus ?? 200, { "content-type": "application/xml" }).end(`<urlset>${site.sitemap.map((loc) => `<url><loc>https://openuniversity.si${loc}</loc></url>`).join("")}</urlset>`);
      return;
    }
    response.writeHead(site.missingStatus ?? 404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${String((server.address() as AddressInfo).port)}`;
});
afterAll(() => new Promise<void>((resolve) => { server.close(() => { resolve(); }); }));

const pairs: SlugPair[] = [{ from: "/c/cmu-db/01-relational-model", to: "/c/cmu-db/lecture-01-relational-model" }, { from: "/c/cmu-db/fa24-sql", to: "/c/cmu-db/lecture-02-sql" }];
function healthy(): Site {
  return {
    redirects: Object.fromEntries(pairs.map((pair) => [pair.from, `https://openuniversity.si${pair.to}`])),
    pages: Object.fromEntries(pairs.map((pair) => [pair.to, { canonical: `https://openuniversity.si${pair.to}`, ogUrl: pair.to }])),
    sitemap: ["/", "/c/cmu-db", ...pairs.map((pair) => pair.to)], flaky: {},
  };
}
const sleeps: number[] = [];
const run = (extra: Partial<Parameters<typeof verifySlugRedirects>[0]> = {}) => verifySlugRedirects({ base, pairs, fetch, sleep: (ms) => { sleeps.push(ms); return Promise.resolve(); }, ...extra });

describe("verifySlugRedirects (fake site)", () => {
  it("reports N/N when every old URL is one 308 hop from a 200 page whose canonical and og:url are the new slug", async () => {
    site = healthy();
    requests.length = 0;
    const report = await run();
    expect(report).toMatchObject({ ok: true, passed: 2, total: 2, failures: [] });
    expect(report.lines[0]).toBe("Redirects: 2/2 ok (308 to the new slug in one hop, new slug 200, canonical and og:url on the new slug).");
    expect(report.lines[1]).toBe("Sitemap: 4 URL(s), 2/2 new present, 0 old listed.");
    expect(requests.at(-1)).toMatch(/^\/c\/cmu-db\/no-such-lesson-/);
  });

  it("fails on a 200 instead of 308, a wrong target, a chain, a wrong canonical/og:url, the sitemap and a soft 404", async () => {
    site = healthy();
    site.redirects["/c/cmu-db/01-relational-model"] = "/c/cmu-db/elsewhere";
    delete site.redirects["/c/cmu-db/fa24-sql"];
    site.pages["/c/cmu-db/fa24-sql"] = { canonical: "/c/cmu-db/fa24-sql", ogUrl: "/c/cmu-db/fa24-sql" };
    site.sitemap.push("/c/cmu-db/fa24-sql");
    site.pages["/c/cmu-db/lecture-02-sql"] = { canonical: "/c/cmu-db/fa24-sql", ogUrl: "/c/cmu-db/lecture-02-sql" };
    const report = await run();
    expect(report.ok).toBe(false);
    expect(report.passed).toBe(0);
    expect(report.failures).toEqual([
      "/c/cmu-db/01-relational-model → /c/cmu-db/lecture-01-relational-model: old redirects to /c/cmu-db/elsewhere, not /c/cmu-db/lecture-01-relational-model",
      "/c/cmu-db/fa24-sql → /c/cmu-db/lecture-02-sql: old answered 200, not 308; canonical is /c/cmu-db/fa24-sql",
      "sitemap still lists 1 old path(s): /c/cmu-db/fa24-sql",
    ]);
    site = healthy();
    site.redirects["/c/cmu-db/lecture-02-sql"] = "/c/cmu-db/again";
    site.sitemap = ["/"];
    const chained = await run();
    expect(chained.failures).toEqual([
      "/c/cmu-db/fa24-sql → /c/cmu-db/lecture-02-sql: new answered 308 → /c/cmu-db/again (more than one hop)",
      "sitemap lacks 2 new path(s): /c/cmu-db/lecture-01-relational-model, /c/cmu-db/lecture-02-sql",
    ]);
  });

  it("retries network errors and 503 with backoff, pausing between requests, and gives up after the retries", async () => {
    site = healthy();
    site.flaky["/c/cmu-db/fa24-sql"] = 2;
    sleeps.length = 0;
    const report = await run({ pauseMs: 50 });
    expect(report.ok, report.failures.join("\n")).toBe(true);
    expect(sleeps.filter((ms) => ms === 50).length).toBeGreaterThanOrEqual(6);
    expect(sleeps.filter((ms) => ms >= 1000)).toEqual([1000, 2000]);
    site = healthy();
    site.flaky["/c/cmu-db/fa24-sql"] = 9;
    const failed = await run({ retries: 1 });
    expect(failed.failures[0]).toMatch(/^\/c\/cmu-db\/fa24-sql → \/c\/cmu-db\/lecture-02-sql: (old answered 503, not 308|GET \/c\/cmu-db\/fa24-sql: .* after 2 attempts\.)/);
  });
});

describe("verifySlugRedirects: site-wide checks", () => {
  it("fails a broken sitemap and a soft 404; an empty list checks only the sitemap", async () => {
    site = { ...healthy(), sitemapStatus: 500, missingStatus: 200 };
    const report = await run();
    expect(report.failures).toEqual(["sitemap.xml answered 500", expect.stringMatching(/^\/c\/cmu-db\/no-such-lesson-\S+ answered 200, not 404$/)]);
    site = healthy();
    requests.length = 0;
    expect(await run({ pairs: [] })).toMatchObject({ ok: true, passed: 0, total: 0 });
    expect(requests).toEqual(["/sitemap.xml"]);
  });
});

describe("parsePairs and pageUrls", () => {
  it("accepts only lesson path pairs that change", () => {
    expect(parsePairs(pairs)).toEqual(pairs);
    for (const bad of [{}, [{ from: "/c/a", to: "/c/a/b" }], [{ from: "/c/a/b", to: "/c/a/b" }], [{ from: "c/a/b", to: "/c/a/c" }]]) expect(() => parsePairs(bad), JSON.stringify(bad)).toThrow();
  });

  it("reads canonical and og:url in any attribute order, null when absent", () => {
    expect(pageUrls('<link rel="canonical" href="/a"><meta property="og:url" content="https://x/a">')).toEqual({ canonical: "/a", ogUrl: "https://x/a" });
    expect(pageUrls("<p>none</p>")).toEqual({ canonical: null, ogUrl: null });
  });
});
