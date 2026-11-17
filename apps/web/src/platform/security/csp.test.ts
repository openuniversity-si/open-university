import { expect, it } from "vitest";
import { reportOnlyContentSecurityPolicy, summarizeCspReports } from "./csp.ts";

const youtubeSources = { scriptSrc: ["https://www.youtube.com"], frameSrc: ["https://www.youtube.com"], imgSrc: ["https://i.ytimg.com"] };

it("renders structural origins without importing a playback driver", () => {
  const directives = new Map(reportOnlyContentSecurityPolicy(["media.example"], youtubeSources).split("; ").map((entry) => [entry.split(" ")[0], entry]));
  expect(directives.get("frame-src")).toBe("frame-src https://www.youtube.com");
  expect(reportOnlyContentSecurityPolicy([])).not.toContain("youtube");
  expect(reportOnlyContentSecurityPolicy([])).not.toContain("nocookie");
  expect(directives.get("script-src")).toBe("script-src 'self' 'unsafe-inline' https://www.youtube.com");
  expect(directives.get("img-src")).toBe("img-src 'self' data: blob: https://media.example https://i.ytimg.com");
  expect(directives.get("media-src")).toBe("media-src 'self' blob:");
  expect(directives.get("connect-src")).toBe("connect-src 'self'");
});

it("summarizes Reporting API and legacy CSP reports without echoing paths or junk", () => {
  expect(summarizeCspReports(JSON.stringify([{ type: "csp-violation", body: { effectiveDirective: "connect-src", blockedURL: "https://stream.example.com/abc.m3u8?token=secret" } }]))).toEqual(["connect-src → https://stream.example.com"]);
  expect(summarizeCspReports(JSON.stringify({ "csp-report": { "violated-directive": "media-src", "blocked-uri": "blob" } }))).toEqual(["media-src → blob"]);
  expect(summarizeCspReports("not json")).toEqual([]);
  expect(summarizeCspReports(JSON.stringify([null, { body: 3 }]))).toEqual([]);
});
