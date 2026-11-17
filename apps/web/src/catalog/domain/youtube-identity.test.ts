import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { playlistIdFromUrl, playlistIdOf, youtubeIdSchema } from "./youtube-identity.ts";

describe("lesson video identity", () => {
  it("accepts an eleven-character YouTube id and rejects any other length", () => {
    expect(youtubeIdSchema.safeParse("abcdefghijk").success).toBe(true);
    expect(youtubeIdSchema.safeParse("abc_-defghi").success).toBe(true);
    expect(youtubeIdSchema.safeParse("short").success).toBe(false);
    expect(youtubeIdSchema.safeParse("abcdefghijkl").success).toBe(false);
  });

  it("reads a playlist id from a youtube.com URL and rejects any other address", () => {
    expect(playlistIdOf("https://www.youtube.com/playlist?list=PLabcdefghij12")).toBe("PLabcdefghij12");
    expect(playlistIdFromUrl("https://www.youtube.com/playlist?list=PLabcdefghij12")).toBe("PLabcdefghij12");
    expect(playlistIdOf("https://evil.example/playlist?list=PLabcdefghij12")).toBeNull();
    expect(() => playlistIdFromUrl("https://evil.example/playlist?list=PLabcdefghij12")).toThrow("playlistUrl must be a youtube.com URL with a list= playlist id.");
  });

  it("keeps the id pattern on the lesson and makes the player import it", () => {
    const lesson = readFileSync(new URL("./youtube-identity.ts", import.meta.url), "utf8");
    const player = readFileSync(new URL("../../playback/domain/drivers/youtube.ts", import.meta.url), "utf8");
    expect(lesson).toContain("[A-Za-z0-9_-]{11}");
    expect(player).not.toContain("[A-Za-z0-9_-]{11}");
    expect(player).toContain("catalog/domain/youtube-identity");
    expect(player).toContain("youtubeIdSchema");
  });
});
