import { describe, expect, it } from "vitest";
import { homeRowKind, homeRowKinds, homeRowSheet, projectHomeRow } from "./home-row-kind.ts";

const cover = {
  url: `https://media.openuniversity.si/covers/mit/university_cover_9x16/${"a".repeat(40)}.webp`,
  width: 1080, height: 1920, sha256: "b".repeat(64), alt: "MIT", credit: "Test", sourceUrl: "https://example.org/mit", license: "test", note: null,
};

describe("home row kinds", () => {
  it("keeps the words and the order the home schemas already accept", () => {
    expect(homeRowKinds).toEqual([homeRowKind.continue, homeRowKind.author, homeRowKind.curated]);
    expect(homeRowKinds).toEqual(["continue", "author", "curated"]);
  });

  it("records the behavior the Home rules already apply", () => {
    expect(homeRowSheet.continue).toEqual({
      maxRows: 1, catalogCourses: false, titleRequired: false, author: false, institution: false,
      cover: "none", fullName: false, place: false, tab: null,
    });
    expect(homeRowSheet.author).toMatchObject({ catalogCourses: true, author: true, institution: false, cover: "author", tab: "authors" });
    expect(homeRowSheet.curated).toMatchObject({
      titleRequired: true, author: false, institution: true, cover: "own", fullName: true, place: true, tab: "universities",
    });
    expect(homeRowKinds.filter((kind) => homeRowSheet[kind].tab === null)).toEqual([homeRowKind.continue]);
  });

  it("emits a row cover, full name and place only when the sheet allows them", () => {
    const base = { id: "row", title: "Title", authorId: null, institutionId: null, courseIds: ["course-1"], cover, fullName: "Full name", place: "Place" };
    expect(projectHomeRow({ ...base, kind: "curated", institutionId: "inst-mit" })).toEqual({
      id: "row", kind: "curated", title: "Title", institutionId: "inst-mit", courseIds: ["course-1"], cover, fullName: "Full name", place: "Place",
    });
    expect(projectHomeRow({ ...base, kind: "author", authorId: "author-1" })).toEqual({
      id: "row", kind: "author", title: "Title", authorId: "author-1", courseIds: ["course-1"],
    });
    expect(projectHomeRow({ ...base, kind: "continue", courseIds: [] })).toEqual({
      id: "row", kind: "continue", title: "Title", courseIds: [],
    });
  });
});
