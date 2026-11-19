import { describe, expect, it } from "vitest";
import nextConfig from "../../next.config.ts";
import { MEDIA_PUBLIC_HOST } from "../../src/media/domain/types.ts";

/**
 * Guardian: images come from one origin, the public media host (Cloudflare R2). The CSP img-src and the
 * next/image remote patterns name it and no other object store.
 */
describe("media origins in next.config.ts", () => {
  it("lists only the public media host in the CSP img-src", async () => {
    if (nextConfig.headers === undefined) throw new Error("next.config.ts must define headers()");
    const rules = await nextConfig.headers();
    const policies = rules.flatMap((rule) => rule.headers).filter((header) => header.key === "Content-Security-Policy").map((header) => header.value);
    expect(policies.length).toBeGreaterThan(0);
    for (const policy of policies) {
      const imgSrc = policy.split("; ").find((entry) => entry.startsWith("img-src "));
      const origins = (imgSrc ?? "").split(" ").slice(1).filter((value) => value.startsWith("https://"));
      expect(origins).toContain(`https://${MEDIA_PUBLIC_HOST}`);
      expect(origins.filter((origin) => origin !== `https://${MEDIA_PUBLIC_HOST}`).every((origin) => !/storage|bucket|\*/.test(origin))).toBe(true);
      expect(imgSrc).not.toMatch(/\*\./);
    }
  });

  it("lets next/image load only the public media host", () => {
    const patterns = nextConfig.images?.remotePatterns ?? [];
    expect(patterns.length).toBeGreaterThan(0);
    expect([...new Set(patterns.map((pattern) => (pattern instanceof URL ? pattern.hostname : pattern.hostname)))]).toEqual([MEDIA_PUBLIC_HOST]);
  });
});
