import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { snapshotCatalog } from "../src/catalog/testing/fake.ts";
import { publicRouteSnapshot } from "../src/catalog/server/public-routes.ts";
import { publicPaths } from "../src/site/domain/route-registry.ts";

// node scripts/html-snapshot.ts <base-url> <out.json>: the rendered HTML of every public page (static pages plus the
// snapshot release's 131 catalog pages), normalized so two builds of the same content compare equal (ADR-17 parity).
// Scripts (RSC payload, chunk names), build-hashed asset URLs and CSS-module hash prefixes are dropped; markup, text
// and <head> metadata stay.
const [base, out] = process.argv.slice(2);
if (!base || !out) throw new Error("Usage: node scripts/html-snapshot.ts <base-url> <out.json>");

export function normalizeHtml(html: string): string {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "")
    .replace(/\/_next\/static\/[^"' )]+/g, "/_next/static/…")
    .replace(/<link rel="(?:preload|modulepreload|stylesheet)"[^>]*>/g, "")
    .replace(/\s(?:nonce|data-precedence|data-dpl-id)="[^"]*"/g, "")
    // CSS-module class prefixes hash the module's path: moving a page file renames them, the rules stay the same.
    .replace(/class="([^"]*)"/g, (_match, names: string) => `class="${names.replace(/\b[A-Za-z0-9-]{6}_(?=[A-Za-z])/g, "…_")}"`)
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/></g, ">\n<");
}

const pages: Record<string, { status: number; html: string }> = {};
for (const path of publicPaths(publicRouteSnapshot(snapshotCatalog))) {
  const response = await fetch(new URL(path, base), { redirect: "manual" });
  pages[path] = { status: response.status, html: normalizeHtml(await response.text()) };
}
writeFileSync(resolve(out), `${JSON.stringify(pages, null, 1)}\n`);
console.log(`html-snapshot: ${String(Object.keys(pages).length)} pages from ${base} → ${out}`);
