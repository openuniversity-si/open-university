import { expect, it } from "vitest";
import { resolveCover } from "../../catalog/domain/cover-resolve.ts";
const asset = (kind: string, sha256 = kind, extra = {}) => ({ kind, sha256, variant: "default", isActive: true, ...extra });

it("D-031: a lesson uses its own frame, then the declared owner's still or lesson default", () => {
  const lesson = [asset("cover_16x9")];
  const course = [asset("still_16x9"), asset("lesson_default")];
  const subarea = [asset("lesson_default", "shared")];
  expect(resolveCover({ lesson, course, subarea, coverFrom: "own", courseId: "course-1" }, { target: "lesson" })).toBe(lesson[0]);
  expect(resolveCover({ course, subarea, coverFrom: "own", courseId: "course-1" }, { target: "lesson" })).toBe(course[0]);
  expect(resolveCover({ course: course.slice(1), subarea, coverFrom: "own", courseId: "course-1" }, { target: "lesson" })).toBe(course[1]);
  expect(resolveCover({ subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "lesson" })).toBe(subarea[0]);
  expect(resolveCover({ subarea, coverFrom: "own", courseId: "course-1" }, { target: "lesson" })).toBeUndefined();
  expect(resolveCover({}, { target: "lesson" })).toBeUndefined();
});

it("ignores inactive and alternate lesson assets and does not walk to another owner", () => {
  const subarea = [asset("lesson_default")];
  expect(resolveCover({
    lesson: [asset("cover_16x9", "old", { isActive: false }), asset("cover_16x9", "alt", { variant: "alternate" })],
    subarea, coverFrom: "own", courseId: "course-1",
  }, { target: "lesson" })).toBeUndefined();
  expect(resolveCover({
    lesson: [asset("cover_16x9", "old", { isActive: false })],
    subarea, coverFrom: "subarea:mechanics", courseId: "course-1",
  }, { target: "lesson" })).toBe(subarea[0]);
});

it("D-031: a course reads only its declared owner", () => {
  const course = [asset("poster_9x16")];
  const subarea = [asset("poster_9x16", "shared"), asset("og")];
  expect(resolveCover({ course, subarea, coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBe(course[0]);
  expect(resolveCover({ subarea, coverFrom: "own", courseId: "course-1" }, { target: "course" })).toBeUndefined();
  expect(resolveCover({ subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course" })).toBe(subarea[0]);
  expect(resolveCover({ subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course", kind: "hero_desktop_16x9", variant: "og" })).toBe(subarea[1]);
  expect(resolveCover({ subarea, coverFrom: "subarea:mechanics", courseId: "course-1" }, { target: "course", kind: "poster_9x16", variant: "alternate" })).toBeUndefined();
});
