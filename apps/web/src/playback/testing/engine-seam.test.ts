import { describe, expect, it } from "vitest";
import { playbackEngine as fake } from "./fake.ts";
import { ENGINE_MARKERS } from "../domain/markers.ts";
import { playbackEngine as youtube } from "../client/youtube.ts";

describe("playback engine seam", () => {
  it("keeps each engine id in sync with the markers bundle:check looks for", () => {
    expect(youtube.id).toBe(ENGINE_MARKERS.youtube);
    expect(fake.id).toBe(ENGINE_MARKERS.fake);
  });
});
