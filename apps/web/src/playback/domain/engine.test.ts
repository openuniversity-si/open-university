import { describe, expect, it } from "vitest";
import { CorePlaybackEngine } from "./engine.ts";
import { FakeEngine } from "../testing/fake-engine.ts";

const lesson = { courseSlug: "course", lessonSlug: "lesson" };
const gesture = { type: "click", isTrusted: true };
describe("playback core", () => {
  it("requires a gesture for start, resume and retry and drops stale events", () => {
    const engine = new FakeEngine(lesson);
    expect(engine.play({ ...gesture, isTrusted: false })).toBe(false);
    expect(engine.play({ ...gesture, type: "load" })).toBe(false);
    engine.emit("playing"); expect(engine.state).toBe("idle");
    expect(engine.play(gesture)).toBe(true); expect(engine.state).toBe("loading");
    expect(engine.play(gesture)).toBe(false);
    engine.emit("ended"); expect(engine.state).toBe("loading");
    engine.emit("playing"); expect(engine.state).toBe("playing");
    engine.pause(); expect(engine.state).toBe("paused");
    engine.emit("playing", 1); expect(engine.state).toBe("paused");
    engine.play(gesture); engine.emit("error"); expect(engine.state).toBe("error");
    expect(engine.play({ ...gesture, isTrusted: false })).toBe(false);
    engine.play(gesture); engine.emit("error", 3); expect(engine.state).toBe("loading");
    engine.emit("playing"); expect(engine.state).toBe("playing");
    engine.dispose(); engine.emit("ended"); expect(engine.state).toBe("playing");
    expect(engine.play(gesture)).toBe(false);
  });
  it("emits exactly one completion per ended attempt", () => {
    const engine = new FakeEngine(lesson, () => 123);
    const events: unknown[] = []; const unsubscribe = engine.subscribe((event) => events.push(event));
    engine.play(gesture); engine.emit("playing"); engine.emit("ended"); engine.emit("ended");
    expect(engine.state).toBe("ended");
    expect(events).toContainEqual({ type: "ended", completion: { ...lesson, endedAt: 123 } });
    expect(events).toHaveLength(4);
    unsubscribe(); engine.play(gesture); expect(events).toHaveLength(4);
  });
  it("cancels loading and converts transport exceptions to retryable errors", () => {
    const engine = new FakeEngine(lesson); engine.play(gesture); engine.pause(); engine.emit("playing");
    expect(engine.state).toBe("paused");
    const broken = new CorePlaybackEngine({ start() { throw new Error("failure"); }, pause() {}, dispose() {} }, lesson);
    broken.play(gesture); expect(broken.state).toBe("error");
  });
  it("records seeks before the first start and drops stale time updates", () => {
    const engine = new FakeEngine(lesson); const times: number[] = [];
    engine.subscribe((event) => { if (event.type === "time") times.push(event.seconds); });
    engine.seek(-3); engine.seek(12);
    expect(engine.starts).toEqual([]); expect(engine.seeks).toEqual([0, 12]); expect(engine.position).toBe(12);
    engine.play(gesture); engine.emit("playing"); engine.time(30);
    const stale = engine.starts.at(-1); engine.pause(); engine.time(99, stale);
    expect(engine.position).toBe(30); expect(times).toEqual([0, 12, 30]);
    engine.dispose(); engine.seek(5); expect(engine.position).toBe(30);
  });
});
