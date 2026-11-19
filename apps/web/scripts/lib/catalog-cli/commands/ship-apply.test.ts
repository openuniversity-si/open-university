import { describe, expect, it } from "vitest";
import { catalogBatchV2Schema } from "../../../../src/catalog/domain/schema/batch-v2.ts";
import { declaredCovers, strictestKind } from "./ship-apply.ts";

// Verifies: D-035
const sha = (seed: string) => seed.repeat(64).slice(0, 64);

describe("ship cover upload (D-035)", () => {
  it("D-035: ship uploads every declared cover", () => {
    const poster = sha("a");
    const hero = sha("b");
    const still = sha("c");
    const lesson = sha("d");
    const shared = sha("e");
    const batch = catalogBatchV2Schema.parse({
      version: 2,
      institutions: [{ id: "usp", slug: "usp", name: "USP", monogram: "USP", kind: "institution", cover: { poster, og: shared } }],
      lecturers: [{ id: "ana", slug: "ana", name: "Ana", monogram: "A", kind: "person" }],
      areas: [{ id: "physics", title: "Physics", cover: { poster: shared, heroDesktop: hero, heroPresent: hero, heroMobile: hero, og: shared, still, lessonDefault: lesson } }],
      subareas: [{ id: "mechanics", areaId: "physics", title: "Mechanics", cover: { poster, heroDesktop: hero, heroPresent: hero, heroMobile: hero, lessonDefault: lesson } }],
      courses: [{
        institutionId: "usp",
        course: { id: "course-a", slug: "course-a", title: "Course", authorId: "ana", areaId: "physics", coverFrom: "own", sharedWith: [] },
        editions: [{ id: "course-a-e", slug: "2021", label: "2021", position: 1, year: 2021 }],
        lessons: [{ id: "course-a-1", editionId: "course-a-e", slug: "aula-1", title: "Aula 1", position: 1, youtubeId: "abcdefghijk", durationSeconds: 60 }],
        covers: [{ kind: "still_16x9", sha: still }, { kind: "poster_9x16", sha: poster }],
      }],
    });
    const pairs = declaredCovers(batch).map((cover) => `${cover.kind}:${cover.sha.slice(0, 2)}`);
    expect(pairs).toEqual(expect.arrayContaining([
      `poster_9x16:${poster.slice(0, 2)}`,
      `og:${shared.slice(0, 2)}`,
      `hero_desktop_16x9:${hero.slice(0, 2)}`,
      `hero_present:${hero.slice(0, 2)}`,
      `hero_mobile_9x16:${hero.slice(0, 2)}`,
      `still_16x9:${still.slice(0, 2)}`,
      `lesson_default:${lesson.slice(0, 2)}`,
    ]));
    expect(pairs.filter((pair) => pair.startsWith("still_16x9:"))).toHaveLength(2);
    expect(strictestKind(batch, shared)).toBe("poster_9x16");
    expect(strictestKind(batch, still)).toBe("still_16x9");
  });
});
