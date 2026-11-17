import { describe, expectTypeOf, it } from "vitest";
import type { CoverDescriptor, MediaCommandsPort } from "./commands.ts";
import type { CatalogOwnersPort, MediaOwner } from "./owner.ts";

describe("media port operations", () => {
  it("asks media commands for the cover operation", () => {
    expectTypeOf<Parameters<MediaCommandsPort["covers"]>[0]>().toEqualTypeOf<readonly { readonly owner: "course" | "lesson" | "subarea"; readonly id: string }[]>();
    expectTypeOf<Parameters<MediaCommandsPort["validateObject"]>[0]>().toEqualTypeOf<CoverDescriptor & { readonly mediaSha256?: string }>();
    expectTypeOf<Parameters<MediaCommandsPort["drain"]>[0]>().toEqualTypeOf<() => { delete(key: string): Promise<void> }>();
  });

  it("asks catalog owners for the owner, not a query", () => {
    expectTypeOf<Parameters<CatalogOwnersPort["courseOf"]>>().toEqualTypeOf<[MediaOwner, string]>();
    expectTypeOf<Parameters<CatalogOwnersPort["graph"]>>().toEqualTypeOf<[]>();
    expectTypeOf<Parameters<CatalogOwnersPort["lockGraph"]>>().toEqualTypeOf<[]>();
    expectTypeOf<Parameters<CatalogOwnersPort["inventory"]>>().toEqualTypeOf<[]>();
  });
});
