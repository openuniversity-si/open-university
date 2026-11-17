import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { cleanTitle, looksLikeTrailer, slugify, uniqueSlug } from "../../../catalog/domain/lesson-address.ts";
import { playlistIdOf } from "./youtube.ts";

describe("import title helpers (plan §4.2)", () => {
  it("cleans lecture prefixes and channel suffixes, keeping the title when nothing would be left", () => {
    expect(cleanTitle("Lecture 3 – Freud | Yale")).toBe("Freud");
    expect(cleanTitle("Ep. 12: The Flood")).toBe("The Flood");
    expect(cleanTitle("07. Abraham")).toBe("Abraham");
    expect(cleanTitle("  Plain title  ")).toBe("Plain title");
    expect(cleanTitle("Lecture 1 - | Yale")).toBe("Lecture 1 - | Yale");
  });

  it("slugifies accents and punctuation, within the length budget", () => {
    expect(slugify("Ça va, Éden & Égypte!")).toBe("ca-va-eden-egypte");
    expect(slugify("!!!")).toBe("lesson");
    expect(slugify("word ".repeat(60), 20)).toBe("word-word-word-word");
  });

  it("adds -2, -3… on collision", () => {
    expect(uniqueSlug("freud", new Set())).toBe("freud");
    expect(uniqueSlug("freud", new Set(["freud", "freud-2"]))).toBe("freud-3");
    expect(uniqueSlug("a".repeat(10), new Set(["a".repeat(10)]), 10)).toBe(`${"a".repeat(8)}-2`);
  });

  it("suggests a trailer only for a short first item named like one", () => {
    expect(looksLikeTrailer("Course trailer", 120, 0)).toBe(true);
    expect(looksLikeTrailer("Introduction", 1200, 0)).toBe(false);
    expect(looksLikeTrailer("Intro", 120, 1)).toBe(false);
    expect(looksLikeTrailer("Intro", null, 0)).toBe(false);
  });

  it("leaves the title and the trailer suggestion off the watcher", () => {
    const source = readFileSync(new URL("./youtube.ts", import.meta.url), "utf8");
    expect(source).not.toContain("looksLikeTrailer");
    expect(source).not.toContain("cleanTitle");
    expect(source).toContain("youtubeIdSchema");
  });

  it("reads the playlist id from youtube.com URLs only", () => {
    expect(playlistIdOf("https://www.youtube.com/playlist?list=PLabcdefghij12")).toBe("PLabcdefghij12");
    expect(playlistIdOf("https://evil.example/playlist?list=PLabcdefghij12")).toBeNull();
    expect(playlistIdOf("https://www.youtube.com/watch?v=x")).toBeNull();
    expect(playlistIdOf("not a url")).toBeNull();
  });
});
