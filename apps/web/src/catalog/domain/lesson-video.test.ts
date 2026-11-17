import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { VIDEO_CHECK_FRESH_DAYS, videoCheckCutoff } from "./lesson-video.ts";

describe("lesson video check", () => {
  it("keeps the seven-day age on the lesson and the twenty-four-hour sheet on the watcher", () => {
    const now = new Date("2026-10-24T00:00:00.000Z");
    expect(VIDEO_CHECK_FRESH_DAYS).toBe(7);
    expect(videoCheckCutoff(now)).toBe("2026-10-17T00:00:00.000Z");
    const port = readFileSync(new URL("../../playback/ports/oembed.ts", import.meta.url), "utf8");
    const schedule = readFileSync(new URL("../../playback/domain/oembed-schedule.ts", import.meta.url), "utf8");
    const courses = readFileSync(new URL("../server/courses.ts", import.meta.url), "utf8");
    expect(port).not.toContain("OEMBED_FRESH_DAYS");
    expect(port).not.toContain("VIDEO_CHECK_FRESH_DAYS");
    expect(schedule).toContain("OEMBED_FRESH_MS");
    expect(schedule).not.toContain("cleanTitle");
    expect(schedule).not.toContain("looksLikeTrailer");
    expect(courses).toContain("videoCheckCutoff");
    expect(courses).not.toContain("OEMBED_FRESH_DAYS");
  });
});
