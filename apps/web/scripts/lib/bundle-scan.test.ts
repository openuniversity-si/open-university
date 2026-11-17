import { describe, expect, it } from "vitest";
import { extractScriptPaths, findSecretLeaks, frameworkScriptPaths } from "./bundle-scan.ts";

describe("findSecretLeaks", () => {
  it("is clean for ordinary client code", () => {
    expect(findSecretLeaks('function a(){return "tower"}', {})).toEqual([]);
  });

  it("flags secret env var names", () => {
    expect(findSecretLeaks("process.env.AUTH_SECRET", {})).toEqual(["env var name AUTH_SECRET"]);
    expect(findSecretLeaks('x("MUX_SIGNING_PRIVATE_KEY")', {})).toContain("env var name MUX_SIGNING_PRIVATE_KEY");
  });

  it("flags key and credential patterns", () => {
    const pem = ["-----BEGIN", "RSA PRIVATE KEY-----"].join(" ");
    expect(findSecretLeaks(pem, {})).toContain("PEM private key");
    expect(findSecretLeaks("postgresql://user:pw@host/db", {})).toContain("Postgres URL with credentials");
    expect(findSecretLeaks(`gho_${"a".repeat(36)}`, {})).toContain("GitHub token");
    expect(findSecretLeaks(`GOCSPX-${"b".repeat(28)}`, {})).toContain("Google OAuth client secret");
  });

  it("flags the actual value of a secret present in the environment, by name only", () => {
    const value = "s3cr3t-value-for-test";
    const findings = findSecretLeaks(`const k="${value}"`, { AUTH_SECRET: value });
    expect(findings).toEqual(["value of AUTH_SECRET"]);
    expect(findings.join()).not.toContain(value);
  });

  it("ignores very short env values to avoid false positives", () => {
    expect(findSecretLeaks("abc", { AUTH_SECRET: "abc" })).toEqual([]);
  });
});

describe("extractScriptPaths", () => {
  it("returns unique same-origin Next scripts", () => {
    const html = '<script src="/_next/static/chunks/a.js" async=""></script><script src="/_next/static/chunks/a.js"></script><script src="https://cdn.example/x.js"></script><script>inline()</script><script src="/_next/static/chunks/b.js?dpl=1"></script>';
    expect(extractScriptPaths(html)).toEqual(["/_next/static/chunks/a.js", "/_next/static/chunks/b.js"]);
  });

  it("skips noModule polyfills", () => {
    const html = '<script src="/_next/static/chunks/p.js" noModule=""></script><script src="/_next/static/chunks/a.js" async=""></script>';
    expect(extractScriptPaths(html)).toEqual(["/_next/static/chunks/a.js"]);
  });
});

describe("frameworkScriptPaths", () => {
  it("maps rootMainFiles to URL paths", () => {
    expect(frameworkScriptPaths({ rootMainFiles: ["static/chunks/r.js"] })).toEqual(new Set(["/_next/static/chunks/r.js"]));
    expect(frameworkScriptPaths({})).toEqual(new Set());
  });
});
