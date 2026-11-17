import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { isSiteIndexable } from "../../site/domain/indexing.ts";
import { adminDeployment, buildEnvFromHost, hostCommit, indexingFacts, siteEnv } from "./env.ts";

describe("site environment", () => {
  it("accepts only the three exact labels", () => {
    expect(siteEnv({ SITE_ENV: "production" })).toBe("production");
    expect(siteEnv({ SITE_ENV: "preview" })).toBe("preview");
    expect(siteEnv({ SITE_ENV: "development" })).toBe("development");
    for (const label of [undefined, "", "Production", "prod", " production"]) expect(siteEnv({ SITE_ENV: label })).toBeUndefined();
  });
});

describe("indexing facts", () => {
  it("treats only the production label as production, whatever the opt-in says", () => {
    for (const siteIndexable of [undefined, "", "false", "true"]) {
      expect(isSiteIndexable(indexingFacts({ SITE_ENV: "production", SITE_INDEXABLE: siteIndexable }))).toBe(true);
    }
  });

  it.each([undefined, "preview", "development", "Production"])("is not production for %j", (label) => {
    expect(indexingFacts({ SITE_ENV: label }).production).toBe(false);
    expect(isSiteIndexable(indexingFacts({ SITE_ENV: label, SITE_INDEXABLE: "false" }))).toBe(false);
  });

  it("keeps the exact local opt-in outside production", () => {
    expect(isSiteIndexable(indexingFacts({ SITE_INDEXABLE: "true" }))).toBe(true);
    expect(isSiteIndexable(indexingFacts({ SITE_ENV: "preview", SITE_INDEXABLE: "true" }))).toBe(true);
  });
});

describe("admin deployment", () => {
  it("is prod only for the production label", () => {
    expect(adminDeployment({ SITE_ENV: "production" })).toBe("prod");
    expect(adminDeployment({ SITE_ENV: "preview" })).toBe("preview");
    expect(adminDeployment({ SITE_ENV: "development" })).toBe("preview");
    expect(adminDeployment({})).toBe("preview");
  });
});

describe("host commit", () => {
  it("prefers BUILD_SHA, then the forge sha, and leaves an inlined commit alone", () => {
    expect(hostCommit({ BUILD_SHA: "a".repeat(40), GITHUB_SHA: "b".repeat(40) })).toBe("a".repeat(40));
    expect(hostCommit({ GITHUB_SHA: "b".repeat(40) })).toBe("b".repeat(40));
    expect(hostCommit({ BUILD_SHA: "  " })).toBeUndefined();
    expect(hostCommit({})).toBeUndefined();
    expect(buildEnvFromHost({ TOWER_BUILD_COMMIT: "local", BUILD_SHA: "c".repeat(40) }).TOWER_BUILD_COMMIT).toBe("local");
    expect(buildEnvFromHost({ BUILD_SHA: "43844ff7889838d7f040463ae3f9d76c46ae37c3" }).TOWER_BUILD_COMMIT).toBe("43844ff7889838d7f040463ae3f9d76c46ae37c3");
  });
});

describe("deployment variables", () => {
  it("are read only by the host module", () => {
    const root = new URL("../../../", import.meta.url);
    const files = ["src/site/domain/indexing.ts", "src/identity/domain/settings.ts", "src/admin/permissions.ts", "src/kernel/env.ts", "next.config.ts"];
    const leaks = files.filter((file) => /\b(?:SITE_ENV|BUILD_SHA)\b/.test(readFileSync(new URL(file, root), "utf8")));
    expect(leaks).toEqual([]);
  });
});
