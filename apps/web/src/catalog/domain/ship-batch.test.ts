import { describe, expect, it } from "vitest";
import { validateCourseBundle, type CourseBundleV1 } from "./bundle.ts";
import { batchContentHash, chunkBundles } from "./ship-batch.ts";

function bundle(id: string): CourseBundleV1 {
  const parsed = validateCourseBundle({
    version: 1,
    author: { id: "author-a", slug: "ann", name: "Ann", monogram: "A", kind: "person" },
    course: { id, slug: id, title: "Title", authorId: "author-a", coverFrom: "own", sharedWith: [] },
    editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }],
    lessons: [{ id: `${id}-l`, editionId: `${id}-e`, slug: "intro", title: "Intro", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
  });
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

describe("batch ship identity", () => {
  it("hashes the same batch whatever order the bundles arrive in", () => {
    const first = bundle("course-a");
    const second = bundle("course-b");
    expect(batchContentHash([first, second])).toBe(batchContentHash([second, first]));
    expect(batchContentHash([first])).not.toBe(batchContentHash([second]));
  });

  it("keeps each chunk's JSON array inside the byte budget", () => {
    const bundles = [bundle("course-a"), bundle("course-b"), bundle("course-c")];
    const one = new TextEncoder().encode(JSON.stringify(bundles[0])).byteLength;
    const chunks = chunkBundles(bundles, one + 2);
    expect(chunks).toHaveLength(3);
    expect(chunkBundles(bundles, 1_000_000)).toHaveLength(1);
    for (const chunk of chunkBundles(bundles, one * 2 + 8)) {
      expect(new TextEncoder().encode(JSON.stringify(chunk)).byteLength).toBeLessThanOrEqual(one * 2 + 8);
    }
  });
});
