import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Since 14 October 2026 the only public mailbox is contact@openuniversity.si (Daniel's decision). No address on the old
// The Tower domain may come back anywhere in the app: site copy, tests, scripts or docs.
const APP = fileURLToPath(new URL("../../..", import.meta.url));
const LEGACY_DOMAIN = ["thetower", "si"].join(".");
const LEGACY_EMAIL = new RegExp(`[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\\.)*${LEGACY_DOMAIN.replace(".", "\\.")}\\b`, "gi");
const SELF = "src/site/domain/no-legacy-email.test.ts";
const SKIP = new Set(["node_modules", ".git", "test-results", "playwright-report", ".reports", "coverage", ".fidelity-cache", ".media-migration"]);
const BINARY = /\.(png|jpe?g|webp|gif|ico|woff2?|pdf|mp4|avif|tsbuildinfo)$/i;

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (SKIP.has(entry.name) || entry.name.startsWith(".next")) return [];
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return filesUnder(path);
    return entry.isFile() && !BINARY.test(entry.name) ? [path] : [];
  });
}

describe("no legacy-domain email addresses", () => {
  it("detects legacy addresses", () => {
    const contact = `contact@${LEGACY_DOMAIN}`;
    const subdomain = `a@mail.${LEGACY_DOMAIN}`;
    expect(`write to ${contact} or ${subdomain}`.match(LEGACY_EMAIL)).toEqual([contact, subdomain]);
    expect(`contact@openuniversity.si and https://${LEGACY_DOMAIN}`.match(LEGACY_EMAIL)).toBeNull();
  });

  it("finds none in the app's files", () => {
    const hits: string[] = [];
    for (const path of filesUnder(APP)) {
      const file = relative(APP, path);
      if (file === SELF) continue;
      for (const m of readFileSync(path, "utf8").match(LEGACY_EMAIL) ?? []) hits.push(`${file}: ${m}`);
    }
    expect(hits).toEqual([]);
  });
});
