import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { createInMemoryProgress } from "./in-memory-progress.ts";
import { progressContract } from "./progress-contract.ts";

describe("progress contract", () => {
  it("runs the shared cases against the in-memory repository", async () => {
    const suite = progressContract();
    expect(suite.portId).toBe("ProgressRepositoryPort");
    await executeContract(suite, createInMemoryProgress());
  });
});
