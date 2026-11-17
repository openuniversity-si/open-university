import { describe, expect, it } from "vitest";
import { DatabaseToolError, parseTargetArgs, resolveDatabaseTarget, safeDatabaseError, validateDatabaseUrl } from "./database-target.ts";

const prod = "postgresql://tower_app:test-only@db.example.invalid:5432/tower?sslmode=require";
const staging = "postgresql://tower_app:test-only@staging-db.example.invalid:5432/tower?sslmode=verify-full";

describe("database command isolation", () => {
  it.each([[], ["--target", "legacy"], ["--target"], ["--target", "prod", "--force"], ["--target", "prod", "--target", "container"]])("rejects invalid arguments %j", (...args) => {
    expect(() => parseTargetArgs(args)).toThrow(DatabaseToolError);
  });
  it("accepts each named target and dry-run", () => {
    for (const target of ["container", "staging", "prod"]) {
      expect(parseTargetArgs(["--target", target, "--dry-run"])).toEqual({ target, dryRun: true });
    }
  });
  it("accepts any remote PostgreSQL host with a role, a database and TLS", () => {
    expect(validateDatabaseUrl(prod, "prod").hostname).toBe("db.example.invalid");
    expect(validateDatabaseUrl(staging, "staging").pathname).toBe("/tower");
    expect(resolveDatabaseTarget("prod", { APP_DATABASE_URL_PROD_UNPOOLED: prod })).toBe(prod);
    expect(() => validateDatabaseUrl(prod.replace("sslmode=require", "sslmode=disable"), "prod")).toThrow("sslmode=require");
    expect(() => validateDatabaseUrl("postgres://tower_app@localhost/tower?sslmode=require", "prod")).toThrow("remote host");
  });
  it("does not consume legacy or unscoped URLs", () => {
    expect(() => resolveDatabaseTarget("prod", { DATABASE_URL: prod, APP_DATABASE_URL_UNPOOLED: prod, TEST_DATABASE_URL: prod })).toThrow("Missing APP_DATABASE_URL_PROD_UNPOOLED");
  });
  it("accepts explicitly scoped APP_DATABASE_URL_UNPOOLED", () => {
    expect(resolveDatabaseTarget("staging", { APP_DATABASE_TARGET: "staging", APP_DATABASE_URL_UNPOOLED: staging })).toBe(staging);
  });
  it("allows the local integration database for container only", () => {
    const url = "postgres://postgres@localhost:5432/tower_test_f02";
    expect(resolveDatabaseTarget("container", { TEST_DATABASE_URL: url })).toBe(url);
    expect(() => resolveDatabaseTarget("prod", { TEST_DATABASE_URL: url })).toThrow("Missing");
    expect(() => validateDatabaseUrl(prod, "container")).toThrow("tower_test");
  });
  it.each([
    prod.replace("/tower?", "/?"),
    prod.replace("tower_app:test-only@", ""),
    prod.replace("sslmode=require", "sslmode=prefer"),
    prod.replace("?sslmode=require", ""),
    "https://example.invalid/tower",
    "invalid",
  ])("refuses unsafe remote destinations", (value) => {
    expect(() => validateDatabaseUrl(value, "prod")).toThrow(DatabaseToolError);
  });
  it("rejects a shared staging and production database", () => {
    expect(() => resolveDatabaseTarget("prod", { APP_DATABASE_URL_PROD_UNPOOLED: prod, APP_DATABASE_URL_STAGING_UNPOOLED: prod })).toThrow("distinct");
    expect(resolveDatabaseTarget("prod", { APP_DATABASE_URL_PROD_UNPOOLED: prod, APP_DATABASE_URL_STAGING_UNPOOLED: staging })).toBe(prod);
  });
  it("redacts driver errors while keeping controlled diagnostics", () => {
    expect(safeDatabaseError(new Error(prod))).not.toContain(prod);
    expect(safeDatabaseError(new DatabaseToolError("Missing credential."))).toBe("Missing credential.");
  });
});
