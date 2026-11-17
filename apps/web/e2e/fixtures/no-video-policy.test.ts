import { describe, expect, it } from "vitest";
import { describeViolation, isBlockedVideoHost, isBlockedVideoUrl } from "./no-video-policy.ts";

describe("no-video policy (ADR-11)", () => {
  it.each(["stream.mux.com", "image.mux.com", "mux.com", "MUX.COM", "inferred.litix.io", "litix.io", "stream.mux.com."])(
    "blocks %s",
    (host) => {
      expect(isBlockedVideoHost(host)).toBe(true);
    },
  );

  it.each(["notmux.com", "mux.com.evil.test", "litix.io.example", "localhost", "thetower.si", "example.com"])(
    "allows %s",
    (host) => {
      expect(isBlockedVideoHost(host)).toBe(false);
    },
  );

  it("parses full URLs", () => {
    expect(isBlockedVideoUrl("https://stream.mux.com/abc.m3u8?token=x")).toBe(true);
    expect(isBlockedVideoUrl("http://127.0.0.1:3100/api/health")).toBe(false);
    expect(isBlockedVideoUrl("not a url")).toBe(false);
  });

  it("describes violations", () => {
    expect(describeViolation({ kind: "request", url: "https://stream.mux.com/a" })).toBe("request to https://stream.mux.com/a");
    expect(describeViolation({ kind: "play-call", src: "" })).toBe("HTMLMediaElement.play() called (src: none)");
    expect(describeViolation({ kind: "play-event", src: "blob:x" })).toBe('media "play" event fired (src: blob:x)');
  });
});
