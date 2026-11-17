import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { FakeMedia } from "./fake.ts";
import { getCourseMedia, getLessonMedia } from "../../../test/fixtures/media-entry.ts";
import { MEDIA_PUBLIC_HOST, type MediaAsset } from "../domain/types.ts";
const asset: MediaAsset = {
  id: "fixture", ownerId: "course-1", kind: "poster_9x16", variant: "default", url: `https://${MEDIA_PUBLIC_HOST}/covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`, pathname: `covers/course-1/poster_9x16/${"1".repeat(40)}.jpg`,
  width: 540, height: 960, sha256: "1".repeat(64), alt: "Genesis poster", transform: null, designStatus: "legacy", version: 1, isActive: true, createdAt: new Date(), updatedAt: new Date(),
};
describe("FakeMedia isolation", () => {
  it("uses local cached bytes for a real descriptor", () => {
    expect(new FakeMedia([asset]).courses().get("course-1")?.[0]?.url).toBe(`/api/media/fixture/${asset.sha256}`);
  });
  it("reads the real manifest relative to the app working directory after relocation", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tower-fake-media-"));
    const media = join(directory, ".fidelity-cache/media");
    mkdirSync(media, { recursive: true });
    const cover = { ...asset, id: "fixture-lesson", ownerId: "lesson-1", kind: "cover_16x9" as const };
    writeFileSync(join(media, "manifest.json"), JSON.stringify([asset, cover]));
    const cwd = vi.spyOn(process, "cwd").mockReturnValue(directory);
    try {
      expect((await getCourseMedia(["course-1"])).get("course-1")?.[0]?.url).toBe(`/api/media/fixture/${asset.sha256}`);
      expect((await getLessonMedia("course-1")).get("lesson-1")?.[0]?.url).toBe(`/api/media/fixture/${cover.sha256}`);
    } finally { cwd.mockRestore(); rmSync(directory, { recursive: true, force: true }); }
  });
  it("keeps missing media empty for the placeholder", () => {
    expect(new FakeMedia().courses().get("course-1")).toBeUndefined();
    expect(new FakeMedia([asset]).courses().get("course-2")).toBeUndefined();
    expect(new FakeMedia([asset]).lessons("course-1").size).toBe(0);
  });
  it("groups lesson covers by course through the snapshot", () => {
    const cover = { ...asset, ownerId: "lesson-1", kind: "cover_16x9" as const };
    const snapshot = { courses: [{ id: "course-1" }, { id: "course-2" }], lessons: [{ id: "lesson-1", courseId: "course-1" }] };
    expect([...new FakeMedia([asset, cover], snapshot).lessons("course-1").keys()]).toEqual(["lesson-1"]);
    expect(new FakeMedia([cover], snapshot).lessons("course-2").size).toBe(0);
  });
});
