import { describe, expectTypeOf, it } from "vitest";
import type { ProgressMaintenancePort } from "./maintenance.ts";

describe("progress maintenance operation", () => {
  it("asks for the lesson count, not a query", () => {
    expectTypeOf<Parameters<ProgressMaintenancePort["countForLessons"]>>().toEqualTypeOf<[readonly string[]]>();
    expectTypeOf<Parameters<ProgressMaintenancePort["orphanedLessons"]>>().toEqualTypeOf<[readonly string[]]>();
  });
});
