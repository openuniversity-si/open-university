import { afterEach, expect, it, vi } from "vitest";
import type { MediaAsset } from "../../media/domain/types.ts";
const calls = vi.hoisted(() => [] as { keys: string[]; tags: string[] }[]);
const reads = vi.hoisted(() => ({ n: 0 }));
const fixtures = vi.hoisted(() => ({
  courses: [] as { id: string; areaId?: string; subareaId?: string; coverFrom?: string }[],
  lessons: [] as { id: string; courseId: string }[],
  area: [] as MediaAsset[],
  shared: [] as MediaAsset[],
}));
vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ unstable_cache: (read: () => unknown, keys: string[], options: { tags: string[] }) => { calls.push({ keys, tags: options.tags }); return read; } }));
vi.mock("../../platform/db/pool.ts", () => ({ appPool: () => ({}) }));
vi.mock("../../media/server/repository.ts", () => ({
  readActiveLessonMedia: () => Promise.resolve([]),
  listPublicMediaRows: (_db: unknown, owners: { owner: string; ownerId: string }[]) => {
    reads.n += 1;
    const rows = owners.flatMap((owner) => {
      const source = owner.owner === "area" ? fixtures.area : owner.owner === "subarea" ? fixtures.shared : [];
      return source.filter((asset) => asset.ownerId === owner.ownerId).map((asset) => ({
        ownerKind: owner.owner, ownerId: asset.ownerId, kind: asset.kind, variant: asset.variant, url: asset.url,
        width: asset.width, height: asset.height, sha256: asset.sha256, alt: asset.alt, transform: asset.transform, isActive: asset.isActive,
      }));
    });
    return Promise.resolve(rows);
  },
}));
import { courseCoverAssets, lessonCoverAssets, ownerRefsForCourses } from "../domain/cover-read.ts";
import { coverOwner } from "../domain/cover-resolve.ts";
import { readLessonAssets, readPublicOwnerAssets } from "../../media/server/index.ts";

async function courseMedia(courseIds: readonly string[]) {
  const rows = await readPublicOwnerAssets(ownerRefsForCourses(fixtures.courses, courseIds));
  return courseCoverAssets(fixtures.courses, courseIds, rows);
}

async function lessonMedia(courseId: string) {
  const course = fixtures.courses.find((item) => item.id === courseId);
  const lessonIds = fixtures.lessons.filter((lesson) => lesson.courseId === courseId).map((lesson) => lesson.id);
  const declared = course?.coverFrom ? coverOwner(course.coverFrom, courseId) : undefined;
  const [lessons, inherited] = await Promise.all([
    readLessonAssets(courseId, lessonIds),
    declared ? readPublicOwnerAssets([{ owner: declared.kind, ownerId: declared.id }]) : Promise.resolve([]),
  ]);
  return lessonCoverAssets(fixtures.lessons, courseId, lessons, inherited.map((row) => row.asset), course?.coverFrom);
}
afterEach(() => { calls.length = 0; reads.n = 0; fixtures.courses = []; fixtures.lessons = []; fixtures.shared = []; fixtures.area = []; });

it("reads the named courses in one public query, not the whole table", async () => {
  await courseMedia(["course-7", "course-7", "course-8"]);
  expect(reads.n).toBe(1);
  expect(calls).toHaveLength(1);
  expect(calls[0]?.keys.slice(0, 2)).toEqual(["media", "public"]);
  expect(calls[0]?.tags).toEqual(["media", "media:courses", "media:course:course-7", "media:course:course-8"]);
  expect(calls.some((call) => call.keys.includes("all"))).toBe(false);
});

it("tags a single course and its lesson read, and skips an empty owner list", async () => {
  await courseMedia(["course-7"]);
  await lessonMedia("course-7");
  expect(calls.map((call) => call.tags)).toEqual([["media", "media:courses", "media:course:course-7"], ["media", "media:course:course-7"]]);
  calls.length = 0;
  await readPublicOwnerAssets([]);
  expect(calls).toEqual([]);
});

it("reads one shared descriptor per subarea for multiple provisional courses and resolves row-free lessons", async () => {
  fixtures.courses = [{ id: "course-7", subareaId: "shared", coverFrom: "subarea:shared" }, { id: "course-8", subareaId: "shared", coverFrom: "subarea:shared" }, { id: "course-9", subareaId: "shared", coverFrom: "own" }];
  fixtures.lessons = [{ id: "lesson-7", courseId: "course-7" }];
  const base = { id: "shared", ownerId: "shared", variant: "default", url: "https://media.example/cover.jpg", pathname: "cover.jpg", sha256: "a".repeat(64), width: 1200, height: 630, alt: "Shared", transform: null, designStatus: "approved" as const, version: 1, isActive: true, createdAt: new Date(0), updatedAt: new Date(0) };
  fixtures.shared = [{ ...base, kind: "poster_9x16" }, { ...base, kind: "lesson_default" }, { ...base, kind: "og" }];
  const courses = await courseMedia(fixtures.courses.map((course) => course.id));
  expect(courses.get("course-7")?.find((asset) => asset.kind === "poster_9x16")).toMatchObject({ ownerId: "shared", url: base.url, sha256: base.sha256, width: 1200, height: 630 });
  expect(courses.get("course-8")?.find((asset) => asset.kind === "poster_9x16")).toMatchObject({ sha256: base.sha256, url: base.url });
  expect(courses.get("course-9")).toBeUndefined();
  expect(courses.get("course-7")?.find((asset) => asset.variant === "og")).toMatchObject({ kind: "hero_desktop_16x9", sha256: base.sha256 });
  expect(calls.filter((call) => call.tags.includes("media:subarea:shared"))).toHaveLength(1);
  expect(reads.n).toBe(1);
  expect((await lessonMedia("course-7")).get("lesson-7")).toMatchObject([{ kind: "cover_16x9", sha256: base.sha256, url: base.url, ownerId: "shared" }]);
  expect(calls.filter((call) => call.keys[1] === "lesson")).toEqual([{ keys: ["media", "lesson", "course-7"], tags: ["media", "media:course:course-7"] }]);
});

it("keeps a cold list render to one table read however large the catalog grows", async () => {
  fixtures.courses = Array.from({ length: 600 }, (_, index) => ({ id: `course-${String(index)}`, ...(index % 2 ? { subareaId: `subarea-${String(index % 40)}`, coverFrom: `subarea:subarea-${String(index % 40)}` } : { coverFrom: "own" }) }));
  await courseMedia(fixtures.courses.map((course) => course.id));
  expect(reads.n).toBe(1);
  expect(calls.length).toBeGreaterThan(1);
  expect(calls.every((call) => call.keys[0] === "media" && call.keys[1] === "public" && call.tags.includes("media:courses"))).toBe(true);
  expect(calls.some((call) => call.keys.includes("all"))).toBe(false);
});

it("INV-M5: resolves area art in pages, OG and lessons without a subarea", async () => {
  fixtures.courses = [{ id: "course-7", areaId: "shared-area", coverFrom: "area:shared-area" }, { id: "course-8", areaId: "shared-area", coverFrom: "own" }];
  fixtures.lessons = [{ id: "lesson-7", courseId: "course-7" }];
  const base = { id: "area-cover", ownerId: "shared-area", variant: "default", url: "https://media.example/area.jpg", pathname: "area.jpg", sha256: "b".repeat(64), width: 1200, height: 630, alt: "Area", transform: null, designStatus: "approved" as const, version: 1, isActive: true, createdAt: new Date(0), updatedAt: new Date(0) };
  fixtures.area = [{ ...base, kind: "poster_9x16" }, { ...base, kind: "lesson_default" }, { ...base, kind: "og" }];
  const courses = await courseMedia(["course-7", "course-8"]);
  expect(courses.get("course-7")?.find((asset) => asset.kind === "poster_9x16")).toMatchObject({ url: base.url, sha256: base.sha256, ownerId: "shared-area" });
  expect(courses.get("course-7")?.find((asset) => asset.variant === "og")).toMatchObject({ kind: "hero_desktop_16x9", sha256: base.sha256 });
  expect(courses.get("course-8")).toBeUndefined();
  expect((await lessonMedia("course-7")).get("lesson-7")).toMatchObject([{ kind: "cover_16x9", sha256: base.sha256, url: base.url }]);
  expect(calls.some((call) => call.tags.includes("media:area:shared-area"))).toBe(true);
  expect(calls.some((call) => call.keys.includes("all"))).toBe(false);
});
