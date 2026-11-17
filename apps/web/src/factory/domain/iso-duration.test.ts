import { describe, expect, it } from "vitest";
import { youtubeDurationSeconds } from "./iso-duration.ts";

describe("youtube duration", () => {
  it("reads hours, minutes and seconds", () => {
    expect(youtubeDurationSeconds("PT52M")).toBe(3120);
    expect(youtubeDurationSeconds("PT1H2M3S")).toBe(3723);
    expect(youtubeDurationSeconds("PT30S")).toBe(30);
    expect(youtubeDurationSeconds("PT0S")).toBe(0);
  });

  it("rejects a value that is not a YouTube duration", () => {
    expect(youtubeDurationSeconds("PT")).toBeNull();
    expect(youtubeDurationSeconds("P1D")).toBeNull();
    expect(youtubeDurationSeconds("52:00")).toBeNull();
  });
});
