import { describe, expect, it } from "vitest";
import { buildWithoutDatabase, hasDatabase } from "./database-env.ts";

describe("database adapter environment", () => {
  it("reads only the adapter variable and ignores a legacy name", () => {
    expect(hasDatabase({})).toBe(false);
    expect(hasDatabase({ DATABASE_URL: "postgres://unused" })).toBe(false);
    expect(hasDatabase({ APP_DATABASE_URL: "  " })).toBe(false);
    expect(hasDatabase({ APP_DATABASE_URL: "postgres://db" })).toBe(true);
  });

  it("treats a missing url during the production build as no database, without trimming", () => {
    expect(buildWithoutDatabase({ NEXT_PHASE: "phase-production-build" })).toBe(true);
    expect(buildWithoutDatabase({ APP_DATABASE_URL: "", NEXT_PHASE: "phase-production-build" })).toBe(true);
    expect(buildWithoutDatabase({ APP_DATABASE_URL: " ", NEXT_PHASE: "phase-production-build" })).toBe(false);
    expect(buildWithoutDatabase({ APP_DATABASE_URL: "postgres://db", NEXT_PHASE: "phase-production-build" })).toBe(false);
    expect(buildWithoutDatabase({ APP_DATABASE_URL: "postgres://db" })).toBe(false);
    expect(buildWithoutDatabase({})).toBe(false);
  });
});
