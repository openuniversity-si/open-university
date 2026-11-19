import { expect, it } from "vitest";
import { unsharedVideoPairs } from "./video-share.ts";

// Verifies: D-032
const use = (courseId: string, youtubeId = "abcdefghijk") => ({ courseId, youtubeId });

it("D-032: a video in two courses is refused unless both declare the share", () => {
  const uses = [use("course-a"), use("course-b")];
  const declared = new Set(["course-a", "course-b"]);
  expect(unsharedVideoPairs(uses, new Map(), declared)).toEqual([
    { courseId: "course-a", otherCourseId: "course-b", youtubeId: "abcdefghijk" },
    { courseId: "course-b", otherCourseId: "course-a", youtubeId: "abcdefghijk" },
  ]);
  const oneSide = new Map([["course-a", ["course-b"]]]);
  expect(unsharedVideoPairs(uses, oneSide, declared)).toHaveLength(2);
  const both = new Map([["course-a", ["course-b"]], ["course-b", ["course-a"]]]);
  expect(unsharedVideoPairs(uses, both, declared)).toEqual([]);
});

it("D-032: courses whose videos do not overlap need no share, and a stored pair is not this write's problem", () => {
  const declared = new Set(["course-c"]);
  expect(unsharedVideoPairs([use("course-a", "aaaaaaaaaaa"), use("course-b", "bbbbbbbbbbb"), use("course-c", "ccccccccccc")], new Map(), declared)).toEqual([]);
  expect(unsharedVideoPairs([use("course-a"), use("course-b")], new Map(), declared)).toEqual([]);
  expect(unsharedVideoPairs([use("course-a"), use("course-c")], new Map(), declared)).toEqual([
    { courseId: "course-c", otherCourseId: "course-a", youtubeId: "abcdefghijk" },
  ]);
});
