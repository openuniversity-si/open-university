import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { R2_MEDIA_BUCKET_DEFAULT } from "../server/storage.ts";
import { MEDIA_PUBLIC_HOST, mediaPublicHost, mediaPublicHosts } from "./types.ts";

// Guardian (2026-10-11, Daniel): images are served from ONE host, media.openuniversity.si (R2 custom domain on bucket open-university-media), and the old
// media.thetower.si is retired with no fallback. The host and the bucket are written once (types.ts, storage.ts); everything else imports them.
const sources = (): string[] => {
  const files: string[] = ["next.config.ts"];
  const walk = (dir: string) => { for (const entry of readdirSync(dir)) { const path = join(dir, entry); if (entry === "node_modules" || entry.startsWith(".")) continue; if (statSync(path).isDirectory()) walk(path); else if (/\.(ts|tsx|mjs|css)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) files.push(path); } };
  for (const dir of ["src", "scripts", "e2e"]) walk(dir);
  return files;
};

describe("media host and bucket", () => {
  it("are the Open University ones, and the environment cannot bring back the old host", () => {
    expect(MEDIA_PUBLIC_HOST).toBe("media.openuniversity.si");
    expect(R2_MEDIA_BUCKET_DEFAULT).toBe("open-university-media");
    expect(mediaPublicHost({})).toBe(MEDIA_PUBLIC_HOST);
    expect(mediaPublicHosts({})).toContain(MEDIA_PUBLIC_HOST);
    expect(() => mediaPublicHost({ TOWER_MEDIA_PUBLIC_HOST: "media.thetower.si" })).toThrow();
  });

  it("are written once in the source: nobody else hard-codes the host, the old host or either bucket name", () => {
    for (const file of sources()) {
      const text = readFileSync(file, "utf8");
      if (file !== join("src", "media", "domain", "types.ts")) expect(text, `${file} hard-codes the media host`).not.toContain("media.openuniversity.si");
      if (file !== join("src", "media", "domain", "types.ts")) expect(text, `${file} names the retired media host`).not.toMatch(/media\.thetower\.si/);
      if (file !== join("src", "media", "server", "storage.ts")) expect(text, `${file} hard-codes the media bucket`).not.toMatch(/["'`]open-university-media["'`]|["'`]the-tower-media["'`]/); // pragma: allowlist secret
    }
  });
});
