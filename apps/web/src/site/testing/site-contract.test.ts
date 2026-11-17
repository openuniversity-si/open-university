import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { createInMemorySiteData } from "./in-memory-site.ts";
import { siteContract } from "./site-contract.ts";

describe("site contract", () => {
  it("runs the shared cases against the in-memory site data", async () => {
    const suite = siteContract();
    expect(suite.portId).toBe("SiteDataStorePort");
    await executeContract(suite, createInMemorySiteData());
  });
});
