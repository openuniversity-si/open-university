import { afterEach, describe, expect, it, vi } from "vitest";

const { appPool } = vi.hoisted(() => ({ appPool: vi.fn() }));
vi.mock("../../platform/db/pool.ts", () => ({ appPool }));

import { snapshotCatalog } from "../../catalog/testing/fake.ts";
import { handleProgressPost, type ProgressRequestDependencies } from "./handler.ts";

const origin = "https://progress.invalid";
const lesson = snapshotCatalog.lessons[0] ?? (() => { throw new Error("snapshot has no lesson"); })();
const course = snapshotCatalog.courses.find((item) => item.id === lesson.courseId) ?? (() => { throw new Error("snapshot has no course"); })();
const valid = JSON.stringify({ courseSlug: course.slug, lessonSlug: lesson.slug, completed: true });
function fixture() {
  const query = vi.fn().mockResolvedValue({ rows: [{ lesson_id: lesson.id }] });
  const resolvePublishedLesson = (courseSlug: string, lessonSlug: string) => {
    const foundCourse = snapshotCatalog.courses.find((item) => item.slug === courseSlug);
    const foundLesson = foundCourse ? snapshotCatalog.lessons.find((item) => item.courseId === foundCourse.id && item.slug === lessonSlug) : undefined;
    return Promise.resolve(foundCourse && foundLesson ? { courseId: foundCourse.id, lessonId: foundLesson.id, durationSeconds: foundLesson.durationSeconds } : null);
  };
  const deps = {
    resolvePublishedLesson, db: () => ({ query }), expectedOrigin: () => origin,
    userId: (): Promise<string | null> => Promise.resolve("user-1"), uuid: () => "fresh-id",
  };
  return { deps: { ...deps } satisfies ProgressRequestDependencies, query };
}
function request(body = valid, headers: Record<string, string> = {}) {
  return new Request(`${origin}/api/progress`, { method: "POST", headers: { origin, "x-request-id": "client-42", ...headers }, body });
}
afterEach(() => { vi.restoreAllMocks(); appPool.mockReset(); });
describe("progress request correlation", () => {
  it.each([403, 401, 413, 400, 404, 429, 204])("correlates status %i without changing it", async (status) => {
    const { deps, query } = fixture();
    let input = request();
    if (status === 403) input = request(valid, { origin: "https://other.invalid" });
    if (status === 401) deps.userId = () => Promise.resolve(null);
    if (status === 413) input = request("x".repeat(1025));
    if (status === 400) input = request("{");
    if (status === 404) input = request(JSON.stringify({ courseSlug: "absent", lessonSlug: "absent", completed: true }));
    if (status === 429) {
      query.mockResolvedValue({ rows: [] });
      input = request(JSON.stringify({ courseSlug: course.slug, lessonSlug: lesson.slug, positionSeconds: 3 }));
    }
    const response = await handleProgressPost(input, deps);
    expect(response.status).toBe(status);
    expect(response.headers.get("x-request-id")).toBe("client-42");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it("replaces unsafe request IDs", async () => {
    const { deps } = fixture();
    const response = await handleProgressPost(request(valid, { "x-request-id": "unsafe id" }), deps);
    expect(response.headers.get("x-request-id")).toBe("fresh-id");
  });
  it.each(["catalog", "save"])("logs one secret-free correlated line and rethrows a %s failure", async (failure) => {
    const { deps, query } = fixture();
    const error = new Error("private database detail");
    if (failure === "catalog") deps.resolvePublishedLesson = () => Promise.reject(error);
    else query.mockRejectedValue(error);
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(handleProgressPost(request(), deps)).rejects.toBe(error);
    expect(log).toHaveBeenCalledExactlyOnceWith('{"event":"PROGRESS_WRITE_FAILED","requestId":"client-42"}');
  });
  it("uses the app pool when the caller omits the database", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [{ lesson_id: lesson.id }] });
    appPool.mockReturnValue({ query });
    const { deps } = fixture();
    const response = await handleProgressPost(request(), { ...deps, db: undefined });
    expect(response.status).toBe(204);
    expect(appPool).toHaveBeenCalledOnce();
    expect(query).toHaveBeenCalledOnce();
  });
  it("does not open the app pool when the request is refused", async () => {
    const { deps } = fixture();
    const response = await handleProgressPost(request(valid, { origin: "https://other.invalid" }), { ...deps, db: undefined });
    expect(response.status).toBe(403);
    expect(appPool).not.toHaveBeenCalled();
  });
});
