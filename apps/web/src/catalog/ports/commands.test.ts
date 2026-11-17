import { describe, expectTypeOf, it } from "vitest";
import type { CatalogStatePort, StatusChange } from "./commands.ts";

describe("catalog state transaction", () => {
  it("asks for the course revision and the status change", () => {
    expectTypeOf<Parameters<CatalogStatePort["read"]>[0]>().toEqualTypeOf<Pick<StatusChange, "courseId" | "expectedRevision">>();
    expectTypeOf<Parameters<CatalogStatePort["changeStatus"]>[0]>().toEqualTypeOf<StatusChange>();
  });
});
