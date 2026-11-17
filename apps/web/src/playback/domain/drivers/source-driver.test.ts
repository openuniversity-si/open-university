import { describe, expect, it } from "vitest";
import { AppError } from "../../../kernel/errors.ts";
import { institutionalUrlDriver } from "./institutional-url.ts";
import { youtubeIdSchema, youtubeSourceDriver } from "./youtube.ts";
import { playbackContentSources, playbackDrivers } from "../../server/source-registry.ts";
import { reportOnlyContentSecurityPolicy } from "../../../platform/security/csp.ts";

describe("source drivers", () => {
  it("keeps one YouTube id schema and rejects a bad id or the wrong provider", () => {
    expect(youtubeIdSchema.safeParse("abcdefghijk").success).toBe(true);
    expect(youtubeIdSchema.safeParse("short").success).toBe(false);
    expect(youtubeSourceDriver.validateSource({ provider: "youtube", videoId: "bad id!!!!" })).toEqual(["videoId"]);
    expect(youtubeSourceDriver.validateSource({ provider: "institutional-url", url: "https://ocw.example/a" })).toEqual(["provider"]);
    expect(youtubeSourceDriver.toPlaybackDescriptor({ provider: "youtube", videoId: "abcdefghijk" })).toEqual({ kind: "youtube", videoId: "abcdefghijk" });
    expect(() => youtubeSourceDriver.toPlaybackDescriptor({ provider: "youtube", videoId: "nope" })).toThrow(AppError);
  });

  it("accepts an allowlisted HTTPS link and refuses credentials, other hosts and embeds", () => {
    const driver = institutionalUrlDriver(["ocw.example"]);
    expect(driver.cspDomains.frameSrc).toEqual([]);
    expect(driver.validateSource({ provider: "institutional-url", url: "https://ocw.example/course" })).toEqual([]);
    expect(driver.validateSource({ provider: "institutional-url", url: "https://user:pw@ocw.example/course" })).toEqual(["url"]);
    expect(driver.validateSource({ provider: "institutional-url", url: "http://ocw.example/course" })).toEqual(["url"]);
    expect(driver.validateSource({ provider: "institutional-url", url: "https://evil.example/course" })).toEqual(["url"]);
    expect(driver.toPlaybackDescriptor({ provider: "institutional-url", url: "https://ocw.example/course" })).toEqual({ kind: "external-link", url: "https://ocw.example/course" });
  });

  it("registers each provider once and keeps the institutional link out of frame-src", () => {
    const drivers = playbackDrivers(["ocw.example"]);
    expect(drivers.map((driver) => driver.provider)).toEqual(["youtube", "institutional-url"]);
    expect(new Set(drivers.map((driver) => driver.provider)).size).toBe(drivers.length);
    const sources = playbackContentSources(["ocw.example"]);
    expect(sources.frameSrc).toEqual(["https://www.youtube.com"]);
    expect(sources.scriptSrc).toEqual(["https://www.youtube.com"]);
    expect(sources.imgSrc).toEqual(["https://i.ytimg.com"]);
    const policy = reportOnlyContentSecurityPolicy(["media.example"], sources);
    expect(policy).toContain("frame-src https://www.youtube.com");
    expect(policy).not.toContain("ocw.example");
    expect(policy).not.toContain("nocookie");
  });
});
