import { expect } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import type { SiteDataStorePort } from "../ports/data.ts";
import { siteFixtureV1, siteFixtureV2 } from "./site-fixture.ts";

export interface SiteBench {
  readonly port: SiteDataStorePort;
  reset(): Promise<void>;
  dispose(): Promise<void>;
  load(raw: unknown): Promise<void>;
}

/** Site data is read-only. Invalid documents are refused and returned objects do not share mutable state. */
export function siteContract(): ContractSuite<SiteBench> {
  return {
    portId: "SiteDataStorePort",
    cases: [
      { id: "site.data.invalid", async run(harness) {
        const error = await harness.load({ schemaVersion: 2 }).then(() => { throw new Error("expected invalid site data"); }, (caught: unknown) => caught);
        expect(error).toBeInstanceOf(AppError);
        expect((error as AppError).code).toBe("invalid");
      } },
      { id: "site.data.upcast", async run(harness) {
        await harness.load(siteFixtureV1);
        const data = await harness.port.read();
        expect(data.schemaVersion).toBe(2);
        expect(data.metadata.siteName).toBe("Open University");
        expect(data.countries.map((country) => country.id)).toEqual(["si"]);
      } },
      { id: "site.data.isolated", async run(harness) {
        const input = structuredClone(siteFixtureV2);
        await harness.load(input);
        input.metadata = { ...input.metadata, siteName: "Changed" };
        const first = await harness.port.read();
        expect(first.metadata.siteName).toBe("Open University");
        (first.metadata as { siteName: string }).siteName = "Changed again";
        const second = await harness.port.read();
        expect(second.metadata.siteName).toBe("Open University");
      } },
    ],
  };
}
