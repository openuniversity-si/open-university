import { describe, expect, it } from "vitest";
import { executeContract } from "../../platform/db/testing/uow-contract.ts";
import { createInMemoryPlayback, playbackDrivers } from "./in-memory-playback.ts";
import { transportContract } from "./transport-contract.ts";

describe("playback transport contract", () => {
  it("runs the shared cases against the in-memory transport", async () => {
    const suite = transportContract();
    expect(suite.portId).toBe("PlaybackTransport");
    expect(playbackDrivers().map((driver) => driver.provider)).toEqual(["youtube", "institutional-url"]);
    const playback = createInMemoryPlayback();
    expect(playback.engine.state).toBe("idle");
    await executeContract(suite, playback);
  });
});
