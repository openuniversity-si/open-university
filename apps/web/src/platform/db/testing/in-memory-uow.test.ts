import { describe, expect, it } from "vitest";
import { createInMemoryUnitOfWork } from "./in-memory-uow.ts";
import { executeContract, uowContract, type UowBench } from "./uow-contract.ts";

function bench(): UowBench {
  let uow = createInMemoryUnitOfWork();
  return {
    port: { kind: "infrastructure" },
    reset() { uow = createInMemoryUnitOfWork(); return Promise.resolve(); },
    dispose() { return Promise.resolve(); },
    register(participant) { uow.register(participant); },
    run(work) { return uow.run(work); },
  };
}

describe("in-memory unit of work", () => {
  it("runs the shared contract", async () => {
    const harness = bench();
    expect(uowContract().portId).toBe("UnitOfWork");
    await executeContract(uowContract(), harness);
  });

  it("rejects a transaction after it finishes and a second bench", async () => {
    const uow = createInMemoryUnitOfWork();
    let saved: Parameters<Parameters<typeof uow.run>[0]>[0] | undefined;
    await uow.run((tx) => { saved = tx; expect(uow.owns(tx)).toBe(true); return Promise.resolve(); });
    if (!saved) throw new Error("missing transaction");
    expect(uow.owns(saved)).toBe(false);
    const other = createInMemoryUnitOfWork();
    await other.run((tx) => { expect(uow.owns(tx)).toBe(false); return Promise.resolve(); });
  });
});
