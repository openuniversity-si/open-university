import { describe, expect, it } from "vitest";
import nextConfig from "../../next.config.ts";

/**
 * Guardian for SSDF PW.9 (docs/security/SECURE-DEFAULTS.md): every path carries HSTS, nosniff, a referrer policy and
 * a frame refusal, and the CSP stays report-only until its reports are read (F09).
 */
async function catchAllHeaders(): Promise<Map<string, string>> {
  if (nextConfig.headers === undefined) throw new Error("next.config.ts must define headers()");
  const rules = await nextConfig.headers();
  const rule = rules.find((entry) => entry.source === "/:path*" && entry.has === undefined);
  if (rule === undefined) throw new Error("next.config.ts must send headers on /:path*");
  return new Map(rule.headers.map((header) => [header.key, header.value]));
}

describe("security headers in next.config.ts", () => {
  it("sends HSTS, nosniff, Referrer-Policy and X-Frame-Options on every path", async () => {
    const headers = await catchAllHeaders();
    expect(headers.get("Strict-Transport-Security")).toBe("max-age=31536000; includeSubDomains");
    expect(headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(headers.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    expect(headers.get("X-Frame-Options")).toBe("DENY");
  });

  it("enforces the CSP, with frame-ancestors 'none', and sends no report-only copy", async () => {
    const headers = await catchAllHeaders();
    expect(headers.has("Content-Security-Policy-Report-Only")).toBe(false);
    expect(headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
  });
});
