import { describe, expect, it } from "vitest";
import type { CuratedV1 } from "./curated.ts";
import { GENERATOR_ACTOR, REVIEWER_ACTOR, generateTexts, parseFactoryTexts, reviewTexts, textsFromCurated } from "./texts.ts";

// Verifies: D-019
const courses = [{
  id: "usp-mecanica-geral",
  title: "Mecânica Geral",
  lessons: [
    { youtubeId: "abcdefghijk", title: "Mecânica Geral - Aula 01" },
    { youtubeId: "bcdefghijkl", title: "Aula de 22/10/2026" },
  ],
}];

const options = { language: "Portuguese", noun: "Aula" };

describe("factory texts", () => {
  it("never approves what the generator writes", () => {
    const texts = generateTexts(courses, options);
    expect(texts.length).toBeGreaterThan(0);
    expect(texts.every((text) => !text.approved && text.approvedBy === null && text.approvedAt === null)).toBe(true);
    expect(texts.map((text) => text.actor)).toEqual(texts.map(() => GENERATOR_ACTOR));
    expect(parseFactoryTexts(texts).ok).toBe(true);
  });

  it("flags a title shaped Aula de dd/mm/aaaa and keeps the original words", () => {
    const texts = generateTexts(courses, options);
    const flagged = texts.find((text) => text.entityId.endsWith("/bcdefghijkl"));
    const kept = texts.find((text) => text.entityId.endsWith("/abcdefghijk"));
    expect(flagged?.flags).toEqual(["placeholder-title"]);
    expect(flagged?.text).toBe("Aula de 22/10/2026");
    expect(kept?.flags).toEqual([]);
    expect(kept?.text).toBe("Mecânica Geral - Aula 01");
  });

  it("rejects an approval by the generator actor", () => {
    const [first] = generateTexts(courses, options);
    const parsed = parseFactoryTexts([{ ...first, approved: true, approvedBy: GENERATOR_ACTOR, approvedAt: "2026-10-22T13:00:00.000Z" }]);
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.issues.some((issue) => issue.name.endsWith("approvedBy"))).toBe(true);
    expect(parsed.issues.map((issue) => issue.message).join("\n")).toMatch(/generator/i);
  });

  it("D-032: a skipped course is named by its id or title, never by a playlist id", () => {
    const curated = {
      courses: [
        { sourcePlaylistId: "PLalgebra001", decision: "hold", title: "Álgebra" },
        { sourcePlaylistId: "PLbare000001", decision: "include" },
        { sourcePlaylistId: "PLnamed00001", decision: "include", id: "usp-x", title: "X", lessons: [] },
      ],
    } as CuratedV1;
    expect(textsFromCurated(curated, options).skipped).toEqual(["Álgebra", "unnamed"]);
  });

  it("stamps approval with the reviewer and leaves the placeholder unapproved", () => {
    const reviewed = reviewTexts(generateTexts(courses, options), "2026-10-22T13:00:00.000Z");
    expect(parseFactoryTexts(reviewed).ok).toBe(true);
    const approved = reviewed.filter((text) => text.approved);
    expect(approved.length).toBeGreaterThan(0);
    expect(approved.every((text) => text.approvedBy === REVIEWER_ACTOR && text.approvedAt === "2026-10-22T13:00:00.000Z")).toBe(true);
    expect(approved.map((text) => text.actor)).toEqual(approved.map(() => GENERATOR_ACTOR));
    const flagged = reviewed.find((text) => text.flags.includes("placeholder-title"));
    expect(flagged?.approved).toBe(false);
    expect(flagged?.approvedBy).toBeNull();
    expect(flagged?.text).toBe("Aula de 22/10/2026");
  });
});
