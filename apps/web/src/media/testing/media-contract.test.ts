import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { createInMemoryMedia } from "./in-memory-media.ts";
import { mediaContract } from "./media-contract.ts";

describe("media contract", () => {
  it("runs the shared cases against the in-memory store", async () => {
    const suite = mediaContract();
    expect(suite.portId).toBe("MediaObjectStore");
    await executeContract(suite, createInMemoryMedia());
  });
});
