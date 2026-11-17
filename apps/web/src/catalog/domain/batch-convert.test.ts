import { describe, expect, it } from "vitest";
import { batchFromBundlesV1, type V1Entry } from "./batch-convert.ts";
import { validateCourseBundle } from "./bundle.ts";
import { planBatch } from "./batch-plan.ts";

const sha = (seed: string) => seed.repeat(64);

function entry(id: string, author: Record<string, unknown>, home: string | null, coverShas: Record<string, string> = { poster_9x16: sha("a") }): V1Entry {
  const parsed = validateCourseBundle({
    version: 1, author, home: home ? { rowId: home, expectedRevision: 1 } : null,
    course: { id, slug: id, title: id, authorId: author.id, areaId: "physics", coverFrom: "own", sharedWith: [] },
    editions: [{ id: `${id}-e`, slug: "original", label: "Original", position: 1, year: 2020 }],
    covers: [{ kind: "poster_9x16", path: `${id}/poster.jpg` }],
  });
  if (!parsed.ok) throw parsed.error;
  return { file: `${id}.json`, bundle: parsed.value, coverShas };
}
const ann = { id: "ann-lee", slug: "ann-lee", name: "Ann Lee", monogram: "AL", kind: "person" };
const ocw = { id: "mit-ocw", slug: "mit-ocw", name: "MIT OpenCourseWare", monogram: "MO", kind: "institution" };

describe("batchFromBundlesV1 (S07 converter)", () => {
  it("D-024: a placed course takes its row's institution; an institution author offers its own unplaced course", () => {
    const converted = batchFromBundlesV1([entry("mechanics", ann, "mit"), entry("waves", ann, "mit"), entry("ocw-only", ocw, null)], new Map([["mit", "mit"]]));
    if (!converted.ok) throw new Error(converted.failures.join("\n"));
    expect(converted.batch.lecturers).toEqual([ann]);
    expect(converted.batch.courses.map((item) => [item.course.id, item.institutionId, item.homeRowId, item.course.authorId])).toEqual([
      ["mechanics", "mit", "mit", "ann-lee"], ["waves", "mit", "mit", "ann-lee"], ["ocw-only", "mit-ocw", null, "mit-ocw"],
    ]);
    expect(converted.batch.courses[0]?.covers).toEqual([{ kind: "poster_9x16", sha: sha("a") }]);
  });

  it("lists every failure instead of guessing an institution or a cover", () => {
    const converted = batchFromBundlesV1([entry("lonely", ann, null), entry("unknown-row", ann, "nowhere"), entry("no-sha", ann, "mit", {})], new Map([["mit", "mit"]]));
    expect(converted).toEqual({ ok: false, failures: [
      "lonely.json: course lonely is on no University row and its author ann-lee is a person; name its institution (D-024).",
      "unknown-row.json: row nowhere has no institution in the catalog.",
      "no-sha.json: cover poster_9x16 (no-sha/poster.jpg) has no content address.",
    ] });
  });

  it("feeds the planner: the converted batch plans against a catalog holding the institution and its row", () => {
    const converted = batchFromBundlesV1([entry("mechanics", ann, "mit")], new Map([["mit", "mit"]]));
    if (!converted.ok) throw new Error(converted.failures.join("\n"));
    const plan = planBatch(converted.batch, {
      sources: new Map(), authors: new Map([["mit", { slug: "mit", name: "MIT", monogram: "MIT", kind: "institution" }]]), areas: new Map([["physics", { title: "Physics" }]]),
      subareas: new Map(), homeRows: new Map([["mit", { institutionId: "mit", title: "MIT" }]]), courses: new Map(), licenses: new Set(),
      covers: new Map([["course:mechanics", ["hero_desktop_16x9", "hero_present", "hero_mobile_9x16"]]]), media: new Set([sha("a")]),
    });
    expect(plan.failures).toEqual([]);
    expect(plan.ops.map((op) => `${op.step} ${op.action}`)).toEqual(["lecturer create", "media attach", "course create", "placement attach", "release create"]);
  });
});
