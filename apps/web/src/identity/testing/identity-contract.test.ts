import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { createInMemoryIdentity } from "./in-memory-identity.ts";
import { identityContract } from "./identity-contract.ts";

describe("identity contract", () => {
  it("runs the shared cases against the in-memory sessions", async () => {
    const suite = identityContract();
    expect(suite.portId).toBe("IdentitySessionPort");
    await executeContract(suite, createInMemoryIdentity());
  });
});
