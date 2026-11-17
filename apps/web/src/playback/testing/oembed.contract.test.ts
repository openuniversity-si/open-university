import { describe, expect, it } from "vitest";
import { createOEmbedResolver } from "../server/oembed-resolver.ts";
import { createFakeOEmbedResolver } from "./fake-oembed.ts";
import { oembedContract } from "./oembed-contract.ts";

describe("oEmbed contract", () => {
  it.each([
    ["memory", createFakeOEmbedResolver],
    ["adapter", createOEmbedResolver],
  ] as const)("%s", async (_name, resolver) => {
    for (const entry of oembedContract()) await entry.run({ resolver });
  });

  it("does not invent a zero duration from an empty payload", async () => {
    const resolver = createOEmbedResolver({
      now: () => new Date("2026-01-01T00:00:00.000Z"),
      transport: () => Promise.resolve({ status: "resolved" as const, verifiedAt: "2026-01-01T00:00:00.000Z" }),
    });
    const [result] = await resolver.resolveMany([{ provider: "youtube", externalId: "abcdefghijk" }]);
    expect(result?.status).toBe("resolved");
    expect(result && "durationSeconds" in result ? result.durationSeconds : undefined).toBeUndefined();
  });
});
