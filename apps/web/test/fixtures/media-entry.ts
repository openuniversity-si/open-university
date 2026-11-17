import "server-only";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fakeCatalog, TEST_EDITIONS_COURSE } from "../../src/catalog/testing/fake.ts";
import { FakeMedia } from "../../src/media/testing/fake.ts";
import "../../src/media/server/public-hosts.ts";
import { assetSchema, type MediaAsset } from "../../src/media/domain/types.ts";

function fixtureMedia() {
  const manifest = resolve(process.cwd(), ".fidelity-cache/media/manifest.json");
  const assets: MediaAsset[] = existsSync(manifest) ? assetSchema.array().parse(JSON.parse(readFileSync(manifest, "utf8")) as unknown) : [];
  assets.push({ id: "test-inherited-cover", ownerId: TEST_EDITIONS_COURSE.id, kind: "lesson_default", variant: "default",
    url: "/brand/og.jpg", pathname: `covers/${TEST_EDITIONS_COURSE.id}/lesson_default/${"0".repeat(40)}.jpg`, sha256: "0".repeat(64),
    width: 1200, height: 630, alt: "Shared lecture fixture", transform: null, designStatus: "approved", version: 1, isActive: true, createdAt: new Date(0), updatedAt: new Date(0) });
  return new FakeMedia(assets, { courses: fakeCatalog.courses, lessons: fakeCatalog.lessons });
}
export function getCourseMedia(courseIds?: readonly string[]) {
  const media = fixtureMedia().courses();
  return Promise.resolve(courseIds ? new Map([...media].filter(([id]) => courseIds.includes(id))) : media);
}
export function getLessonMedia(courseId: string) { return Promise.resolve(fixtureMedia().lessons(courseId)); }
