import { expect } from "vitest";
import type { CachedVideoMetadata, OEmbedResolverPort, VideoIdentity } from "../ports/oembed.ts";

export interface OEmbedBench {
  resolver(deps: {
    readonly now: () => Date;
    readonly transport: (identity: VideoIdentity, signal?: AbortSignal) => Promise<CachedVideoMetadata>;
    readonly cache?: Map<string, CachedVideoMetadata>;
  }): OEmbedResolverPort;
}

const at = "2026-01-01T00:00:00.000Z";
const video = (index: number): VideoIdentity => {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  return { provider: "youtube", externalId: `abcdefghi${alphabet[Math.floor(index / 36)] ?? "a"}${alphabet[index % 36] ?? "a"}` };
};

/** Shared oEmbed cases. The transport is a stub; nothing in here opens a socket. */
export function oembedContract() {
  return [
    { id: "playback.oembed.pool", async run(bench: OEmbedBench) {
      let active = 0;
      let max = 0;
      const resolver = bench.resolver({
        now: () => new Date(at),
        transport: async () => {
          active += 1;
          max = Math.max(max, active);
          await new Promise((resolve) => { setTimeout(resolve, 5); });
          active -= 1;
          return { status: "resolved" as const, verifiedAt: at, title: "Lecture" };
        },
      });
      await resolver.resolveMany(Array.from({ length: 40 }, (_, index) => video(index)));
      expect(max).toBe(16);
    } },
    { id: "playback.oembed.dedupe", async run(bench: OEmbedBench) {
      let calls = 0;
      const resolver = bench.resolver({
        now: () => new Date(at),
        transport: () => { calls += 1; return Promise.resolve({ status: "resolved" as const, verifiedAt: at }); },
      });
      const identity = video(0);
      const results = await resolver.resolveMany(Array.from({ length: 8 }, () => identity));
      expect(calls).toBe(1);
      expect(results).toHaveLength(8);
      expect(results.every((result) => result.identity.externalId === identity.externalId)).toBe(true);
    } },
    { id: "playback.oembed.timeout", async run(bench: OEmbedBench) {
      const resolver = bench.resolver({
        now: () => new Date(at),
        transport: async (_identity, signal) => {
          await new Promise((_, reject) => { signal?.addEventListener("abort", () => { reject(new Error("timeout")); }); });
          return { status: "unavailable" as const, verifiedAt: at };
        },
      });
      const controller = new AbortController();
      const pending = resolver.resolveMany([video(1)], controller.signal);
      controller.abort();
      await expect(pending).rejects.toThrow("timeout");
    } },
    { id: "playback.oembed.fresh", async run(bench: OEmbedBench) {
      let calls = 0;
      const cache = new Map<string, CachedVideoMetadata>([[
        `${video(2).provider}:${video(2).externalId}`,
        { status: "resolved", verifiedAt: "2026-01-01T00:00:00.000Z", title: "Cached" },
      ]]);
      const resolver = bench.resolver({
        now: () => new Date("2026-01-01T23:59:00.000Z"),
        cache,
        transport: () => { calls += 1; return Promise.resolve({ status: "resolved" as const, verifiedAt: at }); },
      });
      const [result] = await resolver.resolveMany([video(2)]);
      expect(calls).toBe(0);
      expect(result?.status).toBe("resolved");
    } },
    { id: "playback.oembed.expired", async run(bench: OEmbedBench) {
      let calls = 0;
      const identity = video(3);
      const cache = new Map<string, CachedVideoMetadata>([[
        `${identity.provider}:${identity.externalId}`,
        { status: "resolved", verifiedAt: "2026-01-01T00:00:00.000Z" },
      ]]);
      const resolver = bench.resolver({
        now: () => new Date("2026-01-02T00:00:00.000Z"),
        cache,
        transport: () => { calls += 1; return Promise.resolve({ status: "unavailable" as const, verifiedAt: "2026-01-02T00:00:00.000Z" }); },
      });
      const [result] = await resolver.resolveMany([identity]);
      expect(calls).toBe(1);
      expect(result?.status).toBe("unavailable");
    } },
    { id: "playback.oembed.future", async run(bench: OEmbedBench) {
      let calls = 0;
      const identity = video(4);
      const cache = new Map<string, CachedVideoMetadata>([[
        `${identity.provider}:${identity.externalId}`,
        { status: "resolved", verifiedAt: "2026-01-02T00:00:00.000Z", durationSeconds: 0 },
      ]]);
      const resolver = bench.resolver({
        now: () => new Date("2026-01-01T00:00:00.000Z"),
        cache,
        transport: () => { calls += 1; return Promise.resolve({ status: "resolved" as const, verifiedAt: at, title: "Live" }); },
      });
      const [result] = await resolver.resolveMany([identity]);
      expect(calls).toBe(1);
      expect(result && "durationSeconds" in result ? result.durationSeconds : undefined).toBeUndefined();
    } },
  ];
}
