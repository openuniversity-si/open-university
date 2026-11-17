// The public proof of a lesson reslug (BRIEF-P7 §3): only GETs against the site, a short pause between requests and a
// retry on network errors and 502–504. scripts/verify-slug-redirects.ts is the command; this is the testable part.

export interface SlugPair { readonly from: string; readonly to: string }

export interface VerifyOptions {
  readonly base: string;
  readonly pairs: readonly SlugPair[];
  readonly fetch: typeof fetch;
  readonly sleep: (ms: number) => Promise<void>;
  /** Between requests (default 150 ms). */
  readonly pauseMs?: number;
  /** Extra attempts after a network error or a 502/503/504 (default 3, backing off 1 s, 2 s, 4 s). */
  readonly retries?: number;
}

export interface VerifyReport {
  readonly ok: boolean;
  readonly passed: number;
  readonly total: number;
  readonly failures: readonly string[];
  readonly lines: readonly string[];
}

const TRANSIENT = new Set([502, 503, 504]);

/** Lesson paths only: `/c/<course>/<lesson>`, the old and the new slug different. */
export function parsePairs(value: unknown): SlugPair[] {
  if (!Array.isArray(value)) throw new Error("Pairs must be a JSON array of { from, to }.");
  return value.map((entry, index) => {
    const { from, to } = (entry ?? {}) as Record<string, unknown>;
    if (typeof from !== "string" || typeof to !== "string" || !/^\/c\/[a-z0-9-]+\/[a-z0-9-]+$/.test(from) || !/^\/c\/[a-z0-9-]+\/[a-z0-9-]+$/.test(to) || from === to) {
      throw new Error(`Pair ${String(index)} is not { from: "/c/<course>/<old>", to: "/c/<course>/<new>" }.`);
    }
    return { from, to };
  });
}

/** The `<link rel=canonical>` href and the `og:url` content of a page, whatever the attribute order. */
export function pageUrls(html: string): { canonical: string | null; ogUrl: string | null } {
  const tags = html.match(/<(?:link|meta)\b[^>]*>/gi) ?? [];
  const attributes = (tag: string) => Object.fromEntries([...tag.matchAll(/([a-z:-]+)\s*=\s*"([^"]*)"/gi)].map((match) => [String(match[1]).toLowerCase(), match[2] ?? ""]));
  let canonical: string | null = null;
  let ogUrl: string | null = null;
  for (const tag of tags) {
    const attrs = attributes(tag);
    if (canonical === null && attrs.rel === "canonical" && attrs.href) canonical = attrs.href;
    if (ogUrl === null && attrs.property === "og:url" && attrs.content) ogUrl = attrs.content;
  }
  return { canonical, ogUrl };
}

const pathOf = (url: string | null, base: string) => (url === null ? null : new URL(url, base).pathname);

export async function verifySlugRedirects(options: VerifyOptions): Promise<VerifyReport> {
  const base = options.base.replace(/\/+$/, "");
  const pause = options.pauseMs ?? 150;
  const retries = options.retries ?? 3;
  const headers: Record<string, string> = { accept: "text/html,application/xml;q=0.9,*/*;q=0.8", "user-agent": "tower-verify-slug-redirects" };

  const get = async (path: string): Promise<Response> => {
    for (let attempt = 0; ; attempt += 1) {
      await options.sleep(pause);
      try {
        const response = await options.fetch(`${base}${path}`, { method: "GET", redirect: "manual", headers });
        if (!TRANSIENT.has(response.status) || attempt >= retries) return response;
      } catch (error) {
        if (attempt >= retries) throw new Error(`GET ${path}: ${error instanceof Error ? error.message : String(error)} after ${String(retries + 1)} attempts.`, { cause: error });
      }
      await options.sleep(1000 * 2 ** attempt);
    }
  };

  const failures: string[] = [];
  let passed = 0;
  for (const pair of options.pairs) {
    const problems: string[] = [];
    try {
      const old = await get(pair.from);
      const location = pathOf(old.headers.get("location"), `${base}/`);
      if (old.status !== 308) problems.push(`old answered ${String(old.status)}, not 308`);
      else if (location !== pair.to) problems.push(`old redirects to ${String(location)}, not ${pair.to}`);
      const page = await get(pair.to);
      if (page.status !== 200) problems.push(`new answered ${String(page.status)}${page.status >= 300 && page.status < 400 ? ` → ${String(page.headers.get("location"))} (more than one hop)` : ""}`);
      else {
        const urls = pageUrls(await page.text());
        if (pathOf(urls.canonical, `${base}/`) !== pair.to) problems.push(`canonical is ${String(urls.canonical)}`);
        if (pathOf(urls.ogUrl, `${base}/`) !== pair.to) problems.push(`og:url is ${String(urls.ogUrl)}`);
      }
    } catch (error) {
      problems.push(error instanceof Error ? error.message : String(error));
    }
    if (problems.length === 0) passed += 1;
    else failures.push(`${pair.from} → ${pair.to}: ${problems.join("; ")}`);
  }

  const sitemap = await get("/sitemap.xml");
  const locs = new Set([...(await sitemap.text()).matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)].map((match) => new URL(match[1] ?? "", `${base}/`).pathname));
  const missing = options.pairs.filter((pair) => !locs.has(pair.to)).map((pair) => pair.to);
  const stale = options.pairs.filter((pair) => locs.has(pair.from)).map((pair) => pair.from);
  if (sitemap.status !== 200) failures.push(`sitemap.xml answered ${String(sitemap.status)}`);
  if (missing.length) failures.push(`sitemap lacks ${String(missing.length)} new path(s): ${missing.slice(0, 5).join(", ")}`);
  if (stale.length) failures.push(`sitemap still lists ${String(stale.length)} old path(s): ${stale.slice(0, 5).join(", ")}`);

  const course = options.pairs[0]?.to.split("/")[2];
  if (course !== undefined) {
    const absent = `/c/${course}/no-such-lesson-${Date.now().toString(36)}`;
    const notFound = await get(absent);
    if (notFound.status !== 404) failures.push(`${absent} answered ${String(notFound.status)}, not 404`);
  }

  const total = options.pairs.length;
  const lines = [
    `Redirects: ${String(passed)}/${String(total)} ok (308 to the new slug in one hop, new slug 200, canonical and og:url on the new slug).`,
    `Sitemap: ${String(locs.size)} URL(s), ${String(total - missing.length)}/${String(total)} new present, ${String(stale.length)} old listed.`,
    ...failures.map((failure) => `FAIL ${failure}`),
  ];
  return { ok: failures.length === 0 && passed === total, passed, total, failures, lines };
}
