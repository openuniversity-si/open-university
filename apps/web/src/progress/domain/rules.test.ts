import { describe, expect, it } from "vitest";
import { continueWatching, courseProgress, durationLabel, lessonHref, lessonStartSecond, remainingLabel, type ProgressLesson, type ProgressRow } from "./rules.ts";

const lessons: ProgressLesson[] = Array.from({ length: 17 }, (_, index) => ({ id: `l${String(index + 1)}`, slug: `s${String(index + 1)}`, order: index + 1, durationSeconds: 9000 + index }));
const row = (lesson: number, patch: Partial<ProgressRow> = {}): ProgressRow => ({ lessonId: `l${String(lesson)}`, positionSeconds: 0, durationSeconds: null, completed: false, updatedAt: lesson, ...patch });
const done = (lesson: number, updatedAt = lesson) => row(lesson, { completed: true, updatedAt });

describe("courseProgress", () => {
  it("Spec 06: Genesis lesson 4 at 3134/9128 s with lessons 1–3 done", () => {
    const progress = courseProgress(lessons, [done(1), done(2), done(3), row(4, { positionSeconds: 3134, durationSeconds: 9128, updatedAt: 10 })]);
    expect(progress).toMatchObject({ started: true, allDone: false, completedCount: 3, total: 17, percent: "18%", continueWatching: true, lastActivity: 10 });
    expect(progress.fraction).toBeCloseTo(3 / 17);
    expect(progress.current).toMatchObject({ lesson: { id: "l4" }, positionSeconds: 3134, durationSeconds: 9128, remainingSeconds: 5994 });
    expect(progress.current?.fraction).toBeCloseTo(0.343, 3);
    expect(progress.cta).toEqual({ kind: "resume", lesson: lessons[3], seconds: 3134 });
    expect(remainingLabel(5994)).toBe("1h 40m left");
  });

  it("not started: Start at lesson 1, not in Continue Watching; rows of other courses are ignored", () => {
    const progress = courseProgress(lessons, [{ ...row(1), lessonId: "elsewhere" }]);
    expect(progress).toMatchObject({ started: false, current: null, cta: { kind: "start", lesson: lessons[0], seconds: 0 }, continueWatching: false, lastActivity: 0, percent: "0%" });
  });

  it("D4: all done → Start restarts at lesson 1, keeps the checks, leaves Continue Watching", () => {
    const progress = courseProgress(lessons, lessons.map((_, index) => done(index + 1)));
    expect(progress).toMatchObject({ allDone: true, completedCount: 17, percent: "100%", current: null, continueWatching: false, cta: { kind: "start", seconds: 0 } });
    expect(progress.cta.lesson.id).toBe("l1");
  });

  it("D5: current lesson done → the next unfinished lesson at 0%, wrapping to the start", () => {
    const next = courseProgress(lessons, [done(1), row(5, { positionSeconds: 100 }), done(4, 20), done(5, 30)]);
    expect(next.current).toMatchObject({ lesson: { id: "l6" }, positionSeconds: 0, fraction: 0 });
    expect(next.cta).toMatchObject({ kind: "resume", seconds: 0 });
    const wrapped = courseProgress(lessons, [...lessons.slice(1).map((_, index) => done(index + 2)), row(1, { positionSeconds: 50, updatedAt: 1 })]);
    expect(wrapped.current).toMatchObject({ lesson: { id: "l1" }, positionSeconds: 0 });
  });

  it("last writer wins and positions are clamped to the lesson", () => {
    const progress = courseProgress(lessons, [row(2, { positionSeconds: 50, updatedAt: 99 }), row(7, { positionSeconds: 99_999, updatedAt: 5 })]);
    expect(progress.current).toMatchObject({ lesson: { id: "l2" }, positionSeconds: 50, durationSeconds: 9001 });
    const late = courseProgress(lessons, [row(7, { positionSeconds: 99_999, durationSeconds: 0, updatedAt: 5 })]);
    expect(late.current).toMatchObject({ positionSeconds: 9006, remainingSeconds: 0 });
  });

  it("rejects a course without lessons", () => {
    expect(() => courseProgress([], [])).toThrow();
  });
});

describe("continueWatching", () => {
  it("keeps started unfinished courses, most recent first", () => {
    const course = (id: string, rows: ProgressRow[]) => ({ id, progress: courseProgress(lessons, rows) });
    const result = continueWatching([course("new", []), course("old", [row(3, { updatedAt: 1 })]), course("finished", lessons.map((_, index) => done(index + 1, 50))), course("recent", [row(2, { updatedAt: 9 })])]);
    expect(result.map((entry) => entry.id)).toEqual(["recent", "old"]);
  });
});

describe("labels and links", () => {
  it("formats durations and remaining time", () => {
    expect(durationLabel(3780)).toBe("1h 03m");
    expect(durationLabel(9128)).toBe("2h 32m");
    expect(durationLabel(3480)).toBe("58m");
    expect(durationLabel(-5)).toBe("0m");
    expect(remainingLabel(3480)).toBe("58m left");
    expect(remainingLabel(1860)).toBe("31m left");
    expect(remainingLabel(0)).toBe("1m left");
  });

  it("Decision 2: resume links carry the saved second", () => {
    expect(lessonHref("genesis", "iv", 3134.7)).toBe("/c/genesis/iv?t=3134");
    expect(lessonHref("genesis", "i")).toBe("/c/genesis/i");
  });

  it("opens the Player at ?t=, else the saved position unless done", () => {
    expect(lessonStartSecond(row(4, { positionSeconds: 3134 }), null, 9128)).toBe(3134);
    expect(lessonStartSecond(row(4, { positionSeconds: 3134 }), 60, 9128)).toBe(60);
    expect(lessonStartSecond(row(4, { positionSeconds: 3134 }), 99_999, 9128)).toBe(9128);
    expect(lessonStartSecond(done(4), null, 9128)).toBe(0);
    expect(lessonStartSecond(undefined, null, 9128)).toBe(0);
  });
});
