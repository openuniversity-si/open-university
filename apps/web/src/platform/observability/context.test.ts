import { describe, expect, it } from "vitest";
import { requestIdFrom } from "./context.ts";

describe("request id", () => {
  it("echoes a safe x-request-id and replaces anything else with a fresh id", () => {
    const uuid = () => "fresh";
    expect(requestIdFrom("cli.run_42-a", uuid)).toBe("cli.run_42-a");
    expect(requestIdFrom("x".repeat(64), uuid)).toBe("x".repeat(64));
    for (const bad of [null, "", "x".repeat(65), "has space", "semi;colon", "ünïcode"]) expect(requestIdFrom(bad, uuid)).toBe("fresh");
  });
});
