import { afterEach, describe, expect, it, vi } from "vitest";
import { groupByOwner, pickAsset } from "./group.ts";
import { mediaOrPlaceholders } from "../server/group.ts";
import type { MediaAsset } from "./types.ts";

const asset = (ownerId: string, kind: MediaAsset["kind"], variant = "default") => ({ ownerId, kind, variant, isActive: true }) as MediaAsset;

describe("grouped media reads (ADR-17)", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("groups by owner and picks one kind and variant", () => {
    const groups = groupByOwner([asset("lesson-1", "cover_16x9"), asset("lesson-1", "cover_9x16"), asset("lesson-2", "cover_16x9", "alt")]);
    expect([...groups.keys()]).toEqual(["lesson-1", "lesson-2"]);
    expect(pickAsset(groups.get("lesson-1"), "cover_9x16")?.kind).toBe("cover_9x16");
    expect(pickAsset(groups.get("lesson-2"), "cover_16x9")).toBeUndefined();
    expect(pickAsset(undefined, "cover_16x9")).toBeUndefined();
  });

  it("degrades a failed read to placeholders with one MEDIA_READ_FAILED log", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect((await mediaOrPlaceholders(Promise.reject(new Error("connect ECONNREFUSED")))).size).toBe(0);
    expect(log.mock.calls).toEqual([[JSON.stringify({ event: "MEDIA_READ_FAILED" })]]);
  });
});
