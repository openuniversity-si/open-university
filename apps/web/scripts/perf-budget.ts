import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { auditHomeImages, budgetFailures, estimatedFirstViewportsImageBytes, homeImageFailures, linkHeaderTags, type MeasuredResource, PERF_VIEWPORTS, plannedResources } from "./lib/perf-budget.ts";

/**
 * pnpm perf:budget [url]: Home weight check after a deploy (docs/project/CICLO-DIARIO.md). Default URL: production.
 * Counts bytes on the wire (br/gzip as served, headers excluded) of what the HTML makes a browser fetch at 390 and
 * 1440 px; every image in the markup counts, so it is an upper bound for the first two viewports. It also audits the
 * HTML's posters (P8): a src only in the first EAGER_ROWS rails, EAGER_CARDS_IN_HTML at most, no poster preloads.
 * The same audit runs in CI on a rendered 24- and 50-course Home (scripts/lib/perf-budget-home.test.ts).
 */
const target = process.argv[2] ?? "https://openuniversity.si/";

/** Transferred body bytes (no decompression) and, for the document, the decoded text. */
function download(url: string, keepText = false): Promise<{ status: number; bytes: number; text: string; link?: string }> {
  const parsed = new URL(url);
  const headers: Record<string, string> = { "accept-encoding": "br, gzip", "user-agent": "the-tower-perf-budget" };
  const request = parsed.protocol === "http:" ? httpRequest : httpsRequest;
  return new Promise((resolve, reject) => {
    const call = request(parsed, { headers, timeout: 30_000 }, (response) => {
      const chunks: Buffer[] = [];
      let bytes = 0;
      response.on("data", (chunk: Buffer) => { bytes += chunk.length; if (keepText) chunks.push(chunk); });
      response.on("end", () => {
        if (!keepText) { resolve({ status: response.statusCode ?? 0, bytes, text: "" }); return; }
        void (async () => {
          const body = Buffer.concat(chunks);
          const encoding = response.headers["content-encoding"];
          const { brotliDecompressSync, gunzipSync } = await import("node:zlib");
          const decoded = encoding === "br" ? brotliDecompressSync(body) : encoding === "gzip" ? gunzipSync(body) : body;
          const link = response.headers.link;
          resolve({ status: response.statusCode ?? 0, bytes, text: decoded.toString("utf8"), link: Array.isArray(link) ? link.join(", ") : link });
        })().catch(reject);
      });
    });
    call.on("timeout", () => { call.destroy(new Error(`timeout: ${url}`)); });
    call.on("error", reject);
    call.end();
  });
}

const page = await download(target, true);
if (page.status !== 200) throw new Error(`${target} answered HTTP ${String(page.status)}`);
const audit = auditHomeImages(page.text);
const homeFailures = homeImageFailures(audit);
let failed = homeFailures.length > 0;
console.log(`html: posters with a src per rail [${audit.eagerPerRow.join(", ")}], estimate ${(estimatedFirstViewportsImageBytes(audit) / 1024).toFixed(0)} KiB of images (media budgets)`);
for (const failure of homeFailures) console.log(`  FAIL ${failure}`);
const sizes = new Map<string, number>();
for (const [name, width] of Object.entries(PERF_VIEWPORTS)) {
  const planned = plannedResources(linkHeaderTags(page.link) + page.text, target, width);
  const measured: MeasuredResource[] = [{ url: target, type: "document", hero: false, bytes: page.bytes }];
  for (const resource of planned) {
    let bytes = sizes.get(resource.url);
    if (bytes === undefined) {
      const response = await download(resource.url);
      if (response.status !== 200) throw new Error(`${resource.url} answered HTTP ${String(response.status)}`);
      bytes = response.bytes;
      sizes.set(resource.url, bytes);
    }
    measured.push({ ...resource, bytes });
  }
  const kib = (bytes: number) => `${(bytes / 1024).toFixed(1)} KiB`;
  const byType = (["document", "css", "js", "font", "image"] as const).map((type) => {
    const of = measured.filter((resource) => resource.type === type);
    return `${type} ${String(of.length)}×${kib(of.reduce((sum, resource) => sum + resource.bytes, 0))}`;
  });
  const largest = measured.filter((resource) => resource.type === "image").sort((a, b) => b.bytes - a.bytes)[0];
  console.log(`${name} ${String(width)}px: total ${kib(measured.reduce((sum, resource) => sum + resource.bytes, 0))} (${byType.join(", ")}); largest image ${largest ? `${kib(largest.bytes)} ${largest.url}` : "none"}; hero downloads ${String(measured.filter((resource) => resource.hero).length)}`);
  const failures = budgetFailures(measured);
  if (failures.length > 0) failed = true;
  for (const failure of failures.slice(0, 5)) console.log(`  FAIL ${failure}`);
  if (failures.length > 5) console.log(`  … and ${String(failures.length - 5)} more`);
}
console.log(failed ? "perf:budget FAILED" : "perf:budget OK (total < 1 MiB, images < 120 KiB, fonts < 60 KiB, one hero download, posters on demand past rail 2)");
process.exitCode = failed ? 1 : 0;
