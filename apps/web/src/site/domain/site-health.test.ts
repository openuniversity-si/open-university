import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fixtureMeasurements } from "../../catalog/testing/route-payload.ts";
import { CACHE_ENTRY_BUDGET_BYTES } from "../../kernel/cache-budget.ts";
import { measurementFailures, reportRefusal, siteHealthCeiling, siteHealthFailures, siteHealthReport, SITE_HEALTH, type Audience, type SiteHealthRoute } from "./site-health.ts";

// Verifies: D-038
const sha = "ab".repeat(32);

describe("site health (D-038)", () => {
  it("D-038: a full-size release fits every route and audience", () => {
    const measurements = fixtureMeasurements();
    expect(siteHealthFailures(measurements)).toEqual([]);
    expect(measurements).toHaveLength(SITE_HEALTH.length * 2);
    const universities = siteHealthCeiling("/universities", "anonymous");
    expect(universities.rendering).toBe("isr");
    expect(siteHealthCeiling("/universities", "signed-in").rendering).toBe("isr");
    expect(siteHealthCeiling("/", "signed-in").rendering).toBe("per-user");
    expect(siteHealthCeiling("/c/[courseSlug]/[lessonSlug]", "signed-in").rendering).toBe("per-user");
    expect(universities.cacheEntryBytes).toBe(CACHE_ENTRY_BUDGET_BYTES);
    const index = measurements.find((entry) => entry.route === "/universities" && entry.audience === "anonymous");
    expect(index?.rscBytes).toBeLessThan(universities.rscBytes);
    expect(siteHealthReport(sha, measurements).passed).toBe(true);
  });

  it("D-038: a stored pass is refused when the measurements miss the current ceilings", () => {
    const measurements = fixtureMeasurements();
    const report = siteHealthReport(sha, measurements);
    expect(reportRefusal(sha, report)).toBeNull();
    expect(reportRefusal("c".repeat(64), report)).toBe("site-health report is for a different batch");
    const blown = measurements.map((entry) => entry.route === "/universities" && entry.audience === "anonymous" ? { ...entry, queries: 2363 } : entry);
    const lying = { ...siteHealthReport(sha, blown), passed: true };
    expect(reportRefusal(sha, lying)).toContain("2363 queries");
    expect(reportRefusal(sha, { batchSha: sha, passed: true, failures: [], routes: [] })).toContain("was not measured");
  });

  it("judges universities and authors once, with or without a session", () => {
    for (const route of ["/universities", "/universities/[slug]", "/authors"] as const) {
      expect(siteHealthCeiling(route, "signed-in")).toEqual(siteHealthCeiling(route, "anonymous"));
    }
    const loop = (route: SiteHealthRoute, audience: Audience) => measurementFailures([{
      route, audience, rscBytes: 20 * 1024, queries: 2363, serverMs: 0, cacheEntryBytes: 1,
    }]);
    expect(loop("/universities", "anonymous")).toEqual(["/universities anonymous 2363 queries over 8"]);
    expect(loop("/universities", "signed-in")).toEqual(["/universities signed-in 2363 queries over 8"]);
    expect(loop("/authors", "anonymous")).toEqual(["/authors anonymous 2363 queries over 8"]);
    expect(loop("/authors", "signed-in")).toEqual(["/authors signed-in 2363 queries over 8"]);
    const home = siteHealthCeiling("/", "anonymous");
    expect(measurementFailures([{
      route: "/", audience: "anonymous", rscBytes: home.rscBytes + 1, queries: 1, serverMs: 0, cacheEntryBytes: 1,
    }])[0]).toContain("RSC");
    expect(catalogDomainSource()).not.toContain("measurementFailures");
  });
});

function catalogDomainSource(): string {
  const root = fileURLToPath(new URL("../../catalog/domain/", import.meta.url));
  const chunks: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(path);
      else if (entry.name.endsWith(".ts")) chunks.push(readFileSync(path, "utf8"));
    }
  };
  walk(root);
  return chunks.join("\n");
}
