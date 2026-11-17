import { describe, expect, it } from "vitest";
import { EDITION_YEARS as fieldsYears, LIMITS as fieldsLimits } from "../catalog/domain/schema/fields.ts";
import { EDITION_YEARS, LIMITS } from "./limits.ts";

describe("D-050 limits", () => {
  it("keeps the catalog object the database checks already share", () => {
    expect(fieldsLimits).toBe(LIMITS);
    expect(fieldsYears).toBe(EDITION_YEARS);
    expect(LIMITS.entityId).toBe(64);
    expect(LIMITS.courseTitle).toBe(200);
    expect(LIMITS.lessonTitle).toBe(1000);
    expect(LIMITS.monogram).toBe(3);
    expect(LIMITS.text).toBe(10_000);
    expect(EDITION_YEARS).toEqual({ min: 1990, max: 2100 });
    expect(LIMITS.mediaBodyBytes).toBe(4 * 1024 * 1024);
    expect(LIMITS.mediaMultipartOverhead).toBe(64 * 1024);
    expect(LIMITS.cspReportBytes).toBe(LIMITS.mediaMultipartOverhead);
    expect(LIMITS.oembedTimeoutMs).toBe(10_000);
    expect(LIMITS.dbIdleMs).toBe(20_000);
    expect(LIMITS.adminRouteMs).toBe(30_000);
    expect(LIMITS.r2Concurrency).toBe(4);
    expect(LIMITS.r2ConcurrencyCap).toBe(16);
  });
});
